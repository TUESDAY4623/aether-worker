package dev.aether.worker

import java.io.BufferedReader
import java.io.FileReader

object CpuUtils {

    private var lastTotal: Long = 0
    private var lastIdle: Long = 0

    fun getCpuUsage(): Double {
        return try {
            val reader = BufferedReader(FileReader("/proc/stat"))
            val line = reader.readLine()
            reader.close()
            val parts = line.split("\\s+".toRegex())
            val idle = parts[4].toLong()
            val total = parts.drop(1).take(7).sumOf { it.toLong() }
            val dt = total - lastTotal
            val di = idle - lastIdle
            lastTotal = total
            lastIdle = idle
            if (dt == 0L) 0.0 else (1.0 - di.toDouble() / dt) * 100
        } catch (e: Exception) {
            0.0
        }
    }
}
