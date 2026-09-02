package com.aether.worker

import android.app.Application
import android.content.Context
import android.os.BatteryManager
import android.os.Build
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.*
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow
import okhttp3.MediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody
import org.json.JSONObject
import java.io.File
import java.text.SimpleDateFormat
import java.util.*
import java.util.concurrent.TimeUnit

data class WorkerUiState(
    val controllerUrl: String = "http://192.168.1.100:8080",
    val deviceId: String = Build.MODEL.replace("\\s".toRegex(), "-"),
    val displayName: String = "${Build.MANUFACTURER} ${Build.MODEL}",
    val isRunning: Boolean = false,
    val isConnected: Boolean = false,
    val lastReportTime: String = "",
    val cpuUtil: Int = 0,
    val memoryUtil: Int = 0,
    val batteryLevel: Int = 100,
    val temperature: Int = 0,
    val networkSpeed: String = "unknown",
    val activeInferences: Int = 0,
    val logs: List<String> = emptyList()
)

class WorkerViewModel(application: Application) : AndroidViewModel(application) {
    private val _uiState = MutableStateFlow(WorkerUiState())
    val uiState: StateFlow<WorkerUiState> = _uiState.asStateFlow()

    private var reportingJob: Job? = null
    private val client = OkHttpClient.Builder()
        .connectTimeout(10, TimeUnit.SECONDS)
        .writeTimeout(10, TimeUnit.SECONDS)
        .readTimeout(10, TimeUnit.SECONDS)
        .build()

    private fun addLog(msg: String) {
        val ts = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
        _uiState.value = _uiState.value.copy(
            logs = _uiState.value.logs + "[$ts] $msg"
        )
    }

    fun updateControllerUrl(url: String) {
        _uiState.value = _uiState.value.copy(controllerUrl = url)
    }

    fun updateDeviceId(id: String) {
        _uiState.value = _uiState.value.copy(deviceId = id)
    }

    fun updateDisplayName(name: String) {
        _uiState.value = _uiState.value.copy(displayName = name)
    }

    fun startReporting() {
        val state = _uiState.value
        if (state.isRunning) return

        _uiState.value = state.copy(isRunning = true)
        addLog("Starting reporter...")

        reportingJob = viewModelScope.launch(Dispatchers.IO) {
            while (isActive) {
                try {
                    reportOnce()
                } catch (e: Exception) {
                    addLog("Error: ${e.message}")
                    _uiState.value = _uiState.value.copy(isConnected = false)
                }
                delay(5000L)
            }
        }
    }

    fun stopReporting() {
        reportingJob?.cancel()
        reportingJob = null
        _uiState.value = _uiState.value.copy(isRunning = false, isConnected = false)
        addLog("Stopped")
    }

    private suspend fun reportOnce() = withContext(Dispatchers.IO) {
        val state = _uiState.value
        val baseUrl = state.controllerUrl.trimEnd('/')

        // Register worker
        val registerJson = JSONObject().apply {
            put("device_id", state.deviceId)
            put("display_name", state.displayName)
            put("capabilities", org.json.JSONArray(listOf("cpu", "npu", "gpu")))
        }

        val registerReq = Request.Builder()
            .url("$baseUrl/api/v1/workers")
            .post(RequestBody.create(MediaType.parse("application/json"), registerJson.toString()))
            .build()

        client.newCall(registerReq).execute().use { response ->
            if (response.isSuccessful) {
                addLog("Registered: ${state.deviceId}")
            }
        }

        // Collect telemetry
        val cpu = getCpuUtilization()
        val mem = getMemoryUtilization()
        val battery = getBatteryLevel()
        val temp = getTemperature()
        val network = getNetworkSpeed()

        val telemetryJson = JSONObject().apply {
            put("device_id", state.deviceId)
            put("cpu_util", cpu)
            put("memory_util", mem)
            put("temperature_c", temp)
            put("network_mbps", network)
            put("active_inferences", 0)
        }

        val telemetryReq = Request.Builder()
            .url("$baseUrl/api/v1/telemetry")
            .post(RequestBody.create(MediaType.parse("application/json"), telemetryJson.toString()))
            .build()

        client.newCall(telemetryReq).execute().use { response ->
            if (response.isSuccessful) {
                val ts = SimpleDateFormat("HH:mm:ss", Locale.US).format(Date())
                _uiState.value = _uiState.value.copy(
                    isConnected = true,
                    lastReportTime = ts,
                    cpuUtil = cpu,
                    memoryUtil = mem,
                    batteryLevel = battery,
                    temperature = temp,
                    networkSpeed = "$network Mbps"
                )
            } else {
                _uiState.value = _uiState.value.copy(isConnected = false)
            }
        }
    }

    private fun getCpuUtilization(): Int {
        return try {
            val idle1 = readCpuIdle()
            val total1 = readCpuTotal()
            Thread.sleep(1000L)
            val idle2 = readCpuIdle()
            val total2 = readCpuTotal()
            val totalDelta = total2 - total1
            val idleDelta = idle2 - idle1
            if (totalDelta == 0L) 50 else (((totalDelta - idleDelta).toDouble() / totalDelta) * 100).toInt().coerceIn(0, 100)
        } catch (e: Exception) {
            50
        }
    }

    private fun readCpuIdle(): Long {
        return try {
            val reader = java.io.BufferedReader(java.io.FileReader("/proc/stat"))
            val line = reader.readLine() ?: return 0
            reader.close()
            val parts = line.split("\\s+".toRegex())
            if (parts.size < 6 || !parts[0].startsWith("cpu")) return 0
            parts[4].toLong() + parts[5].toLong()
        } catch (e: Exception) {
            0
        }
    }

    private fun readCpuTotal(): Long {
        return try {
            val reader = java.io.BufferedReader(java.io.FileReader("/proc/stat"))
            val line = reader.readLine() ?: return 0
            reader.close()
            val parts = line.split("\\s+".toRegex())
            if (parts.size < 6 || !parts[0].startsWith("cpu")) return 0
            parts.drop(1).take(7).map { it.toLong() }.sum()
        } catch (e: Exception) {
            0
        }
    }

    private fun getMemoryUtilization(): Int {
        return try {
            val reader = java.io.BufferedReader(java.io.FileReader("/proc/meminfo"))
            var memTotal = 0L
            var memAvailable = 0L
            reader.forEachLine { line ->
                val parts = line.split("\\s+".toRegex())
                when {
                    line.startsWith("MemTotal:") -> memTotal = parts[1].toLong()
                    line.startsWith("MemAvailable:") -> memAvailable = parts[1].toLong()
                }
            }
            reader.close()
            if (memTotal == 0L) 50 else (((memTotal - memAvailable).toDouble() / memTotal) * 100).toInt()
        } catch (e: Exception) {
            50
        }
    }

    private fun getBatteryLevel(): Int {
        return try {
            val bm = getApplication<Application>().getSystemService(Context.BATTERY_SERVICE) as BatteryManager
            bm.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY)
        } catch (e: Exception) {
            100
        }
    }

    private fun getTemperature(): Int {
        return try {
            val thermalDir = File("/sys/class/thermal/")
            val files = thermalDir.listFiles() ?: return estimateTemp()
            files.filter { it.name.startsWith("thermal_zone") }.forEach { file ->
                val tempFile = File(file, "temp")
                if (tempFile.exists()) {
                    val temp = tempFile.readText().trim().toInt()
                    if (temp > 0 && temp < 100000) {
                        return temp / 1000
                    }
                }
            }
            estimateTemp()
        } catch (e: Exception) {
            35
        }
    }

    private fun estimateTemp(): Int {
        return 30 + (getCpuUtilization() * 40 / 100)
    }

    private fun getNetworkSpeed(): Int {
        return try {
            val cm = getApplication<Application>().getSystemService(Context.CONNECTIVITY_SERVICE)
                as android.net.ConnectivityManager
            val network = cm.activeNetwork
            val capabilities = cm.getNetworkCapabilities(network)
            val downlink = capabilities?.linkDownstreamBandwidthKbps ?: 10000
            (downlink / 1000).coerceAtLeast(1)
        } catch (e: Exception) {
            10
        }
    }

    override fun onCleared() {
        super.onCleared()
        reportingJob?.cancel()
    }
}
