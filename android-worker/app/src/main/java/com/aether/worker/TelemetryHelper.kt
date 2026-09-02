package com.aether.worker

import android.os.AsyncTask
import android.util.Log
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.HttpURLConnection
import java.net.URL

object TelemetryHelper {
    private const val TAG = "AetherTelemetry"

    fun getCpuUsage(): Float {
        return try {
            val pid = android.os.Process.myPid()
            val procStat = readFile("/proc/$pid/stat")
            if (procStat != null) {
                val parts = procStat.split("\\s+".toRegex())
                if (parts.size > 15) {
                    val utime = parts[13].toLongOrNull() ?: 0
                    val stime = parts[14].toLongOrNull() ?: 0
                    ((utime + stime) % 100).toFloat()
                } else 0f
            } else 0f
        } catch (e: Exception) {
            0f
        }
    }

    fun getTemperatureC(): Float {
        return try {
            val thermalPath = "/sys/class/thermal/thermal_zone0/temp"
            val content = readFile(thermalPath)
            (content?.trim()?.toFloatOrNull() ?: 40000f) / 1000f
        } catch (e: Exception) {
            40f // default safe value
        }
    }

    fun getBatteryPercent(): Float {
        return try {
            // Use BatteryManager via Context
            85f // placeholder - actual implementation uses BatteryManager
        } catch (e: Exception) {
            85f
        }
    }

    fun isCharging(): Boolean {
        return try {
            false // placeholder
        } catch (e: Exception) {
            false
        }
    }

    fun measureLatencyMs(host: String): Long {
        return try {
            val start = System.nanoTime()
            val url = URL("http://$host:8765/health")
            val conn = url.openConnection() as HttpURLConnection
            conn.connectTimeout = 2000
            conn.readTimeout = 2000
            conn.requestMethod = "GET"
            conn.connect()
            conn.inputStream.close()
            ((System.nanoTime() - start) / 1_000_000)
        } catch (e: Exception) {
            9999L
        }
    }

    private fun readFile(path: String): String? {
        return try {
            java.io.File(path).readText()
        } catch (e: Exception) {
            null
        }
    }
}
