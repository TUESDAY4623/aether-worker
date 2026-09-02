package com.aether.worker

import android.app.Service
import android.content.Intent
import android.os.Binder
import android.os.IBinder
import android.util.Log
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import java.io.*
import java.net.*
import java.util.concurrent.atomic.AtomicBoolean
import kotlin.random.Random

class AetherWorkerService : Service() {
    private val binder = LocalBinder()
    private val serviceScope = CoroutineScope(
        SupervisorJob() + Dispatchers.IO + CoroutineExceptionHandler { _, exc ->
            Log.e(TAG, "Unhandled coroutine exception", exc)
        }
    )
    private val _state = MutableStateFlow(WorkerState.IDLE)
    val state: StateFlow<WorkerState> = _state

    private var controllerSocket: Socket? = null
    private var writer: BufferedOutputStream? = null
    private var reader: BufferedInputStream? = null
    private var discoveryJob: Job? = null
    private var telemetryJob: Job? = null
    private var receiveJob: Job? = null
    private val running = AtomicBoolean(false)
    private var reconnectAttempts = 0
    private val MAX_RECONNECT_DELAY_MS = 30000L

    var deviceId: String = generateDeviceId()
    var displayName: String = "Android-${Build.MODEL.replace(" ", "-")}"
    var controllerHost: String = "192.168.1.100"
    var controllerPort: Int = 8765
    var discoveryPort: Int = 8766
    var onStatusUpdate: ((String) -> Unit)? = null

    inner class LocalBinder : Binder() {
        fun getService(): AetherWorkerService = this@AetherWorkerService
    }

    override fun onBind(intent: Intent): IBinder = binder

    override fun onCreate() {
        super.onCreate()
        Log.d(TAG, "AetherWorkerService created, deviceId=$deviceId")
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        return START_STICKY
    }

    fun start() {
        if (running.compareAndSet(false, true)) {
            _state.value = WorkerState.CONNECTING
            onStatusUpdate?.invoke("Connecting to controller...")
            reconnectAttempts = 0
            serviceScope.launch { connectAndRun() }
        }
    }

    fun stop() {
        if (running.compareAndSet(true, false)) {
            discoveryJob?.cancel()
            telemetryJob?.cancel()
            receiveJob?.cancel()
            controllerSocket?.close()
            controllerSocket = null
            writer = null
            reader = null
            _state.value = WorkerState.STOPPED
            onStatusUpdate?.invoke("Stopped")
        }
    }

    private suspend fun connectAndRun() {
        while (running.get()) {
            try {
                connectToController()
                _state.value = WorkerState.CONNECTED
                onStatusUpdate?.invoke("Connected to controller")
                startDiscovery()
                startTelemetryLoop()
                startReceiveLoop()
                reconnectAttempts = 0
                awaitCancellation()
            } catch (e: CancellationException) {
                break
            } catch (e: Exception) {
                Log.w(TAG, "Connection error: ${e.message}", e)
                if (running.get()) {
                    _state.value = WorkerState.RECONNECTING
                    val delayMs = minOf(1000L * (1 shl reconnectAttempts), MAX_RECONNECT_DELAY_MS)
                    reconnectAttempts++
                    onStatusUpdate?.invoke("Reconnecting in ${delayMs / 1000}s...")
                    delay(delayMs)
                }
            }
        }
    }

    private fun connectToController() {
        Log.d(TAG, "Connecting to ${controllerHost}:${controllerPort}")
        val socket = Socket()
        socket.connect(InetSocketAddress(controllerHost, controllerPort), 5000)
        socket.soTimeout = 10000
        controllerSocket = socket
        writer = BufferedOutputStream(socket.getOutputStream())
        reader = BufferedInputStream(socket.getInputStream())
        sendHello()
    }

    private fun startDiscovery() {
        discoveryJob = serviceScope.launch {
            while (running.get() && isActive) {
                try {
                    broadcastDiscovery()
                } catch (e: Exception) {
                    Log.w(TAG, "Discovery error: ${e.message}", e)
                }
                delay(3000L)
            }
        }
    }

    private suspend fun broadcastDiscovery() {
        withContext(Dispatchers.IO) {
            DatagramSocket().use { sock ->
                sock.broadcast = true
                sock.soTimeout = 2000
                val magic = "AETHER_DISCOVERY".toByteArray(Charsets.UTF_8)
                val payload = """{"device_id":"$deviceId","display_name":"$displayName","timestamp":${System.currentTimeMillis()},"port":$discoveryPort}""".toByteArray(Charsets.UTF_8)
                val packet = DatagramPacket(magic + payload, magic.size + payload.size, InetAddress.getByName("255.255.255.255"), discoveryPort)
                sock.send(packet)
            }
        }
    }

    private fun startTelemetryLoop() {
        telemetryJob = serviceScope.launch {
            while (running.get() && isActive) {
                try {
                    sendTelemetry()
                } catch (e: Exception) {
                    Log.w(TAG, "Telemetry error: ${e.message}", e)
                }
                delay(5000L)
            }
        }
    }

    private suspend fun sendTelemetry() {
        val memInfo = Runtime.getRuntime()
        val totalMem = memInfo.totalMemory() / (1024 * 1024)
        val freeMem = memInfo.freeMemory() / (1024 * 1024)
        val maxMem = memInfo.maxMemory() / (1024 * 1024)

        val tel = TelemetryReport(
            deviceId = deviceId,
            temperatureC = getTemperatureC(),
            memoryTotalMb = maxMem,
            memoryAvailableMb = maxMem - totalMem + freeMem,
            memoryAetherReservedMb = 0,
            cpuUtilizationPct = getCpuUsage(),
            npuUtilizationPct = 0f,
            batteryPct = getBatteryPercent(),
            isCharging = isCharging(),
            networkLatencyMs = measureLatencyMs(controllerHost),
            tensorBandwidthMbps = 0f,
            available = true,
        )
        val json = tel.toJson()
        sendMessage(MessageType.TELEMETRY_REPORT, json.toByteArray(Charsets.UTF_8))
    }

    private fun startReceiveLoop() {
        receiveJob = serviceScope.launch {
            while (running.get() && isActive && controllerSocket?.isClosed == false) {
                try {
                    val raw = readBinaryMessage() ?: break
                    val msg = AetherMessage.decode(raw)
                    if (msg != null) {
                        handleMessage(msg)
                    }
                } catch (e: CancellationException) {
                    break
                } catch (e: Exception) {
                    Log.w(TAG, "Receive error: ${e.message}", e)
                    break
                }
            }
            if (running.get()) {
                reconnect()
            }
        }
    }

    private fun readBinaryMessage(): ByteArray? {
        val input = reader ?: return null
        val header = ByteArray(AetherMessage.HEADER_SIZE)
        var read = 0
        while (read < header.size) {
            val n = input.read(header, read, header.size - read)
            if (n == -1) return null
            read += n
        }
        val buf = ByteBuffer.wrap(header)
        buf.int // magic
        buf.get() // version
        buf.get() // type
        buf.get() // flags
        buf.int // reserved
        val sidLen = buf.short.toInt() and 0xFFFF
        val extraHeaderSize = 2 + sidLen + 4
        val extraHeader = ByteArray(extraHeaderSize)
        read = 0
        while (read < extraHeader.size) {
            val n = input.read(extraHeader, read, extraHeader.size - read)
            if (n == -1) return null
            read += n
        }
        val bb = ByteBuffer.wrap(extraHeader)
        val sidBytes = ByteArray(sidLen)
        bb.get(sidBytes)
        val payloadLen = bb.int
        if (payloadLen > AetherMessage.MAX_PAYLOAD || payloadLen < 0) return null
        val payload = ByteArray(payloadLen)
        read = 0
        while (read < payload.size) {
            val n = input.read(payload, read, payload.size - read)
            if (n == -1) return null
            read += n
        }
        return header + extraHeader + payload
    }

    private suspend fun handleMessage(msg: AetherMessage) {
        when (msg.type) {
            MessageType.HELLO_ACK -> {
                _state.value = WorkerState.READY
                onStatusUpdate?.invoke("Ready")
            }
            MessageType.PAIRING_REQUEST -> {
                val code = Random.nextInt(100000, 999999).toString()
                pairingCode = code
                sendMessage(MessageType.PAIRING_CODE, """{"code":"$code"}""".toByteArray(Charsets.UTF_8))
                _state.value = WorkerState.PAIRING
                onStatusUpdate?.invoke("Pairing code: $code")
            }
            MessageType.GOODBYE -> {
                _state.value = WorkerState.IDLE
                onStatusUpdate?.invoke("Disconnected by controller")
                stop()
            }
            else -> {
                Log.d(TAG, "Unhandled message type: ${msg.type}")
            }
        }
    }

    private fun sendHello() {
        val hello = """{"device_id":"$deviceId","display_name":"$displayName","version":"0.1.0"}"""
        sendMessage(MessageType.HELLO, hello.toByteArray(Charsets.UTF_8))
    }

    private fun sendMessage(type: MessageType, payload: ByteArray) {
        val msg = AetherMessage(type = type, sessionId = deviceId, payload = payload, flags = 0)
        val wire = msg.encode()
        writer?.write(wire.size and 0xFF)
        writer?.write((wire.size shr 8) and 0xFF)
        writer?.write((wire.size shr 16) and 0xFF)
        writer?.write((wire.size shr 24) and 0xFF)
        writer?.write(wire)
        writer?.flush()
    }

    private fun reconnect() {
        controllerSocket?.close()
        controllerSocket = null
        writer = null
        reader = null
        if (running.get()) {
            serviceScope.launch {
                delay(1000L)
                if (running.get()) {
                    connectAndRun()
                }
            }
        }
    }

    override fun onDestroy() {
        super.onDestroy()
        stop()
        serviceScope.cancel()
    }

    companion object {
        const val TAG = "AetherWorker"
        var pairingCode: String? = null

        fun generateDeviceId(): String {
            return "worker-${Build.SERIAL ?: Random.nextLong().toString(16)}-${System.currentTimeMillis() % 10000}"
        }
    }
}

enum class WorkerState {
    IDLE, CONNECTING, CONNECTED, READY, PAIRING, RECONNECTING, STOPPED
}
