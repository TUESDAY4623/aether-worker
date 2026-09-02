package com.aether.worker

import android.app.Activity
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.cardview.widget.CardView
import kotlinx.coroutines.*
import okhttp3.*
import okhttp3.MediaType.Companion.toMediaType
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.*

class MainActivity : AppCompatActivity() {

    private var job: Job? = null
    private val handler = Handler(Looper.getMainLooper())

    // UI refs
    private lateinit var urlInput: EditText
    private lateinit var deviceIdInput: EditText
    private lateinit var displayNameInput: EditText
    private lateinit var btnStart: Button
    private lateinit var btnStop: Button
    private lateinit var statusDot: View
    private lateinit var statusText: TextView

    // Stat card refs
    private lateinit var cpuValue: TextView
    private lateinit var memValue: TextView
    private lateinit var battValue: TextView
    private lateinit var tempValue: TextView
    private lateinit var netValue: TextView
    private lateinit var lastValue: TextView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        // Bind views
        urlInput = findViewById(R.id.urlInput)
        deviceIdInput = findViewById(R.id.deviceIdInput)
        displayNameInput = findViewById(R.id.displayNameInput)
        btnStart = findViewById(R.id.btnStart)
        btnStop = findViewById(R.id.btnStop)
        statusDot = findViewById(R.id.statusDot)
        statusText = findViewById(R.id.statusText)

        // Stat cards — inflate label/value from stat_card.xml include
        fun bindStat(id: Int): TextView {
            val root = findViewById<View>(id)
            return root.findViewById(R.id.statValue)
        }

        cpuValue = bindStat(R.id.statCpu)
        memValue = bindStat(R.id.statMem)
        battValue = bindStat(R.id.statBatt)
        tempValue = bindStat(R.id.statTemp)
        netValue = bindStat(R.id.statNet)
        lastValue = bindStat(R.id.statLast)

        btnStart.setOnClickListener {
            val url = urlInput.text.toString().trim()
            val id = deviceIdInput.text.toString().trim()
            val name = displayNameInput.text.toString().trim()
            if (url.isEmpty()) { toast("Enter controller URL"); return@setOnClickListener }
            startTelemetry(url, id.ifEmpty { "android-device" }, name.ifEmpty { "Android Device" })
        }

        btnStop.setOnClickListener { stopTelemetry() }
        resetUI()
    }

    override fun onDestroy() {
        job?.cancel()
        super.onDestroy()
    }

    private fun startTelemetry(baseUrl: String, deviceId: String, displayName: String) {
        stopTelemetry()
        btnStart.isEnabled = false
        setStatus(false, "Starting...")

        job = CoroutineScope(Dispatchers.IO).launch {
            runTelemetryLoop(baseUrl, deviceId, displayName)
        }
    }

    private fun stopTelemetry() {
        job?.cancel()
        job = null
        handler.post { resetUI() }
    }

    private fun resetUI() {
        btnStart.isEnabled = true
        btnStop.isEnabled = false
        setStatus(false, "Stopped")
        cpuValue.text = "--"
        memValue.text = "--"
        battValue.text = "--"
        tempValue.text = "--"
        netValue.text = "--"
        lastValue.text = "Never"
    }

    private fun setStatus(connected: Boolean, msg: String) {
        handler.post {
            statusDot.setBackgroundColor(if (connected) 0xFF4CAF50.toInt() else 0xFFF44336.toInt())
            statusText.text = msg
            btnStop.isEnabled = connected
        }
    }

    private fun updateStat(valueView: TextView, text: String, color: Int) {
        handler.post {
            valueView.text = text
            valueView.setTextColor(color)
        }
    }

    private fun toast(msg: String) = handler.post {
        Toast.makeText(this, msg, Toast.LENGTH_SHORT).show()
    }

    // ── Sensor Readers ──────────────────────────────────────────────────────────

    private fun readBattery(): Pair<Int, Boolean> = try {
        val intent = registerReceiver(null, android.content.IntentFilter(android.content.Intent.ACTION_BATTERY_CHANGED))
        val level = intent?.getIntExtra(android.os.BatteryManager.EXTRA_LEVEL, -1) ?: -1
        val scale = intent?.getIntExtra(android.os.BatteryManager.EXTRA_SCALE, -1) ?: -1
        val pct = if (level >= 0 && scale > 0) level * 100 / scale else -1
        val status = intent?.getIntExtra(android.os.BatteryManager.EXTRA_STATUS, -1) ?: -1
        val charging = status == android.os.BatteryManager.BATTERY_STATUS_CHARGING ||
                status == android.os.BatteryManager.BATTERY_STATUS_FULL
        pct.coerceAtLeast(0) to charging
    } catch (_: Exception) { -1 to false }

    @Volatile private var cpuPrev: LongArray? = null
    private fun readCpu(): Int {
        return try {
            val line = java.io.File("/proc/stat").readText().lineSequence().first { it.startsWith("cpu ") }
            val parts = line.split(Regex("\\s+")).drop(1).mapNotNull { it.toLongOrNull() }
            val total = parts.sum()
            val idle = parts.getOrElse(3) { 0L }
            val prev = cpuPrev
            cpuPrev = longArrayOf(total, idle)
            if (prev == null) return -1
            val dt = total - prev[0]
            val di = idle - prev[1]
            if (dt <= 0) return -1
            ((dt - di).toDouble() / dt * 100).toInt().coerceIn(0, 100)
        } catch (_: Exception) { -1 }
    }

    private data class MemInfo(val total: Long, val avail: Long) {
        val util: Int get() = if (total <= 0) -1 else ((total - avail).toDouble() / total * 100).toInt()
    }

    private fun readMem(): MemInfo = try {
        val text = java.io.File("/proc/meminfo").readText()
        fun kb(key: String) = Regex("$key:\\s+(\\d+)").find(text)?.groups?.get(1)?.value?.toLongOrNull() ?: 0L
        MemInfo(kb("MemTotal") * 1024, kb("MemAvailable") * 1024)
    } catch (_: Exception) { MemInfo(0, 0) }

    private fun readTemp(): Int {
        val zones = listOf(
            "/sys/class/thermal/thermal_zone0/temp",
            "/sys/class/thermal/thermal_zone1/temp",
            "/sys/devices/virtual/thermal/thermal_zone0/temp"
        )
        for (z in zones) {
            try { return (java.io.File(z).readText().trim().toLong() / 1000).toInt() } catch (_: Exception) {}
        }
        return -1
    }

    @Volatile private var netLastBytes: Long = -1
    @Volatile private var netLastTime: Long = -1
    private fun readNet(): String = try {
        val rx = java.io.File("/proc/net/dev").readText()
            .lineSequence().filter { ":" in it }
            .mapNotNull { it.split(":").getOrNull(1)?.trim()?.split(Regex("\\s+"))?.getOrNull(0)?.toLongOrNull() }
            .sum()
        val now = System.currentTimeMillis()
        val mbps = if (netLastBytes > 0 && netLastTime > 0) {
            val dt = (now - netLastTime) / 1000.0
            val db = (rx - netLastBytes).coerceAtLeast(0)
            "%.1f Mbps".format((db * 8.0 / 1_000_000.0) / dt)
        } else "--"
        netLastBytes = rx
        netLastTime = now
        mbps
    } catch (_: Exception) { "--" }

    // ── Telemetry Loop ──────────────────────────────────────────────────────────

    private suspend fun runTelemetryLoop(baseUrl: String, deviceId: String, displayName: String) {
        setStatus(false, "Starting...")

        val client = OkHttpClient.Builder()
            .connectTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
            .writeTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
            .readTimeout(5, java.util.concurrent.TimeUnit.SECONDS)
            .build()
        val media = "application/json".toMediaType()
        val base = baseUrl.trimEnd('/')

        fun post(path: String, body: JSONObject): Boolean = try {
            val req = Request.Builder().url(base + path)
                .post(RequestBody.create(media, body.toString())).build()
            client.newCall(req).execute().use { it.isSuccessful }
        } catch (_: Exception) { false }

        val regBody = JSONObject().apply {
            put("device_id", deviceId)
            put("display_name", displayName)
            put("capabilities", org.json.JSONArray(listOf("cpu", "npu", "gpu")))
        }
        val registered = post("/api/v1/workers", regBody)
        setStatus(registered, if (registered) "Registered: $deviceId" else "Registration failed")

        val fmt = SimpleDateFormat("HH:mm:ss", Locale.getDefault())

        while (currentCoroutineContext().isActive) {
            try {
                val (battPct, charging) = readBattery()
                val cpu = readCpu().coerceAtLeast(0)
                val mem = readMem()
                val temp = readTemp().coerceAtLeast(0)
                val net = readNet()
                val ts = fmt.format(Date())

                val battStr = if (battPct >= 0) "$battPct%" + if (charging) " ++" else "" else "--"
                val tempStr = if (temp >= 0) "$temp°C" else "--"

                updateStat(cpuValue, "$cpu%", 0xFF4CAF50.toInt())
                updateStat(memValue, "${mem.util}%", 0xFF4CAF50.toInt())
                updateStat(battValue, battStr, 0xFFFF9800.toInt())
                updateStat(tempValue, tempStr, 0xFFE91E63.toInt())
                updateStat(netValue, net, 0xFF7C6AEF.toInt())
                updateStat(lastValue, ts, 0xFF888888.toInt())

                val mbps = net.replace(" Mbps", "").toDoubleOrNull() ?: 10.0
                val telBody = JSONObject().apply {
                    put("device_id", deviceId)
                    put("cpu_util", cpu)
                    put("memory_util", mem.util.coerceAtLeast(0))
                    put("temperature_c", temp)
                    put("network_mbps", mbps)
                    put("active_inferences", 0)
                }
                val sent = post("/api/v1/telemetry", telBody)
                setStatus(sent, if (sent) "Connected ($deviceId)" else "Send failed")

                delay(5000L)
            } catch (_: CancellationException) { break }
            catch (e: Exception) {
                setStatus(false, "Error: ${e.message}")
                delay(5000L)
            }
        }
    }
}
