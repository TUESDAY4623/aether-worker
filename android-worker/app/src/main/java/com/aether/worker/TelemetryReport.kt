package com.aether.worker

data class TelemetryReport(
    val deviceId: String,
    val temperatureC: Float,
    val memoryTotalMb: Int,
    val memoryAvailableMb: Int,
    val memoryAetherReservedMb: Int,
    val cpuUtilizationPct: Float,
    val npuUtilizationPct: Float,
    val batteryPct: Float,
    val isCharging: Boolean,
    val networkLatencyMs: Long,
    val tensorBandwidthMbps: Float,
    val available: Boolean,
) {
    fun toJson(): String {
        return """{"device_id":"$deviceId","temperature_c":$temperatureC,"memory_total_mb":$memoryTotalMb,"memory_available_mb":$memoryAvailableMb,"memory_aether_reserved_mb":$memoryAetherReservedMb,"cpu_utilization_pct":$cpuUtilizationPct,"npu_utilization_pct":$npuUtilizationPct,"battery_pct":$batteryPct,"is_charging":$isCharging,"network_latency_ms":$networkLatencyMs,"tensor_bandwidth_mbps":$tensorBandwidthMbps,"available":$available}"""
    }
}
