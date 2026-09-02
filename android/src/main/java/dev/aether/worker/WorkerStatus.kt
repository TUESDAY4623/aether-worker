package dev.aether.worker

sealed class WorkerStatus(val displayName: String) {
    object DISCONNECTED : WorkerStatus("Disconnected")
    object DISCOVERING : WorkerStatus("Discovering...")
    object CONNECTING : WorkerStatus("Connecting...")
    object PAIRING : WorkerStatus("Pairing...")
    object CONNECTED : WorkerStatus("Connected")
    object ERROR : WorkerStatus("Error")
}
