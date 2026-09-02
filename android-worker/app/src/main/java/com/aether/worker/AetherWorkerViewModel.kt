package com.aether.worker

import android.app.Application
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

class AetherWorkerViewModel(private val service: AetherWorkerService) : ViewModel() {
    private val _uiState = MutableStateFlow(WorkerUiState())
    val uiState: StateFlow<WorkerUiState> = _uiState

    init {
        viewModelScope.launch {
            service.state.collect { state ->
                _uiState.value = _uiState.value.copy(
                    state = state,
                    statusText = "Status: ${state.name}\nDevice: ${service.deviceId}",
                    deviceId = service.deviceId,
                )
            }
        }
    }

    fun start() {
        _uiState.value = _uiState.value.copy(error = null)
        service.start()
    }

    fun stop() {
        service.stop()
    }

    fun setControllerHost(host: String) {
        service.controllerHost = host
        _uiState.value = _uiState.value.copy(controllerHost = host)
    }
}

data class WorkerUiState(
    val state: WorkerState = WorkerState.IDLE,
    val statusText: String = "Idle",
    val deviceId: String = "",
    val controllerHost: String = "192.168.1.100",
    val error: String? = null,
)
