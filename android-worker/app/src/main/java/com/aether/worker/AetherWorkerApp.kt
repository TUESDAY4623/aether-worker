package com.aether.worker

import android.app.Application

class AetherWorkerApp : Application() {
    private lateinit var workerService: AetherWorkerService

    override fun onCreate() {
        super.onCreate()
        workerService = AetherWorkerService()
    }

    fun getWorkerService(): AetherWorkerService = workerService
}
