package dev.aether.worker

data class TelemetryData(
    val deviceId: String,
    val temperatureC: Double,
    val memoryTotalMb: Long,
    val memoryAvailableMb: Long,
    val memoryAetherReservedMb: Long = 0,
    val cpuUtilizationPct: Double,
    val batteryPct: Int,
    val isCharging: Boolean,
    val networkLatencyMs: Long,
    val tensorBandwidthMbps: Double = 0.0,
    val timestamp: Long = System.currentTimeMillis(),
)
