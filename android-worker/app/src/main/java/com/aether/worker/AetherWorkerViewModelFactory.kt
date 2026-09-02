package com.aether.worker

import androidx.lifecycle.ViewModel
import androidx.lifecycle.ViewModelProvider
import androidx.lifecycle.viewmodel.CreationExtras

class AetherWorkerViewModelFactory(private val service: AetherWorkerService) : ViewModelProvider.Factory {
    override fun <T : ViewModel> create(modelClass: Class<T>, extras: CreationExtras): T {
        return AetherWorkerViewModel(service) as T
    }
}
