package dev.aether.worker

import android.app.ActivityManager

object MemoryUtils {

    fun getTotalMemory(): Long {
        val memInfo = ActivityManager.MemoryInfo()
        return memInfo.totalMem / (1024 * 1024)
    }

    fun getAvailableMemory(): Long {
        val memInfo = ActivityManager.MemoryInfo()
        return memInfo.availMem / (1024 * 1024)
    }

    fun getAetherReservedMemoryMb(): Long = 0L
}
