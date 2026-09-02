package dev.aether.worker

import java.io.BufferedReader
import java.io.FileReader

object ThermalUtils {

    fun readCpuTemperature(): Double {
        return try {
            for (i in 0 until 20) {
                val typeFile = "/sys/class/thermal/thermal_zone$i/type"
                val tempFile = "/sys/class/thermal/thermal_zone$i/temp"
                if (File(tempFile).exists()) {
                    val type = BufferedReader(FileReader(typeFile)).use { it.readLine() }
                    if (type?.contains("cpu", ignoreCase = true) == true ||
                        type?.contains("soc", ignoreCase = true) == true) {
                        return BufferedReader(FileReader(tempFile)).use { it.readLine()?.toLongOrNull()?.div(1000.0) ?: 40.0 }
                    }
                }
            }
            40.0
        } catch (e: Exception) {
            40.0
        }
    }
}
