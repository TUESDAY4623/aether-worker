package com.aether.worker

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.dp
import androidx.lifecycle.ViewModel
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            MaterialTheme {
                Surface(modifier = Modifier.fillMaxSize()) {
                    WorkerScreen()
                }
            }
        }
    }
}

@Composable
fun WorkerScreen(viewModel: WorkerViewModel = viewModel()) {
    val uiState by viewModel.uiState.collectAsStateWithLifecycle()

    Column(
        modifier = Modifier
            .fillMaxSize()
            .padding(16.dp)
            .verticalScroll(rememberScrollState()),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        // Header
        Text(
            text = "⚡ Aether Worker",
            style = MaterialTheme.typography.headlineMedium,
            color = MaterialTheme.colorScheme.primary
        )

        // Connection Card
        Card(
            colors = CardDefaults.cardColors(
                containerColor = MaterialTheme.colorScheme.primaryContainer
            )
        ) {
            Column(
                modifier = Modifier.padding(16.dp),
                verticalArrangement = Arrangement.spacedBy(8.dp)
            ) {
                Text(
                    text = "Controller Connection",
                    style = MaterialTheme.typography.titleMedium
                )

                OutlinedTextField(
                    value = uiState.controllerUrl,
                    onValueChange = { viewModel.updateControllerUrl(it) },
                    label = { Text("Controller URL") },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("http://192.168.1.100:8080") }
                )

                OutlinedTextField(
                    value = uiState.deviceId,
                    onValueChange = { viewModel.updateDeviceId(it) },
                    label = { Text("Device ID") },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("phone-1") }
                )

                OutlinedTextField(
                    value = uiState.displayName,
                    onValueChange = { viewModel.updateDisplayName(it) },
                    label = { Text("Display Name") },
                    modifier = Modifier.fillMaxWidth(),
                    placeholder = { Text("My Phone") }
                )

                Button(
                    onClick = {
                        if (uiState.isRunning) {
                            viewModel.stopReporting()
                        } else {
                            viewModel.startReporting()
                        }
                    },
                    modifier = Modifier.fillMaxWidth(),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = if (uiState.isRunning)
                            MaterialTheme.colorScheme.error
                        else
                            MaterialTheme.colorScheme.primary
                    )
                ) {
                    Text(if (uiState.isRunning) "Stop" else "Start Reporting")
                }

                // Status indicator
                Row(
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.spacedBy(8.dp)
                ) {
                    Icon(
                        imageVector = if (uiState.isConnected)
                            androidx.compose.material.icons.Icons.Default.CheckCircle
                        else
                            androidx.compose.material.icons.Icons.Default.Error,
                        contentDescription = null,
                        tint = if (uiState.isConnected)
                            MaterialTheme.colorScheme.primary
                        else
                            MaterialTheme.colorScheme.error
                    )
                    Text(
                        text = if (uiState.isConnected)
                            "Connected (${uiState.lastReportTime})"
                        else
                            "Disconnected",
                        style = MaterialTheme.typography.bodyMedium
                    )
                }
            }
        }

        // Telemetry Card
        if (uiState.isConnected) {
            TelemetryCard(uiState)
        }

        // Log Card
        if (uiState.logs.isNotEmpty()) {
            Card {
                Column(
                    modifier = Modifier.padding(16.dp),
                    verticalArrangement = Arrangement.spacedBy(4.dp)
                ) {
                    Text(
                        text = "Event Log",
                        style = MaterialTheme.typography.titleMedium
                    )
                    uiState.logs.takeLast(10).forEach { log ->
                        Text(
                            text = log,
                            style = MaterialTheme.typography.bodySmall,
                            color = MaterialTheme.colorScheme.onSurfaceVariant
                        )
                    }
                }
            }
        }
    }
}

@Composable
fun TelemetryCard(uiState: WorkerUiState) {
    Card {
        Column(
            modifier = Modifier.padding(16.dp),
            verticalArrangement = Arrangement.spacedBy(12.dp)
        ) {
            Text(
                text = "Live Telemetry",
                style = MaterialTheme.typography.titleMedium
            )

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                TelemetryItem("CPU", "${uiState.cpuUtil}%", uiState.cpuUtil)
                TelemetryItem("Memory", "${uiState.memoryUtil}%", uiState.memoryUtil)
                TelemetryItem("Battery", "${uiState.batteryLevel}%", null)
            }

            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text(
                        text = "Temperature",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        text = "${uiState.temperature}°C",
                        style = MaterialTheme.typography.headlineSmall,
                        color = when {
                            uiState.temperature > 70 -> MaterialTheme.colorScheme.error
                            uiState.temperature > 50 -> MaterialTheme.colorScheme.tertiary
                            else -> MaterialTheme.colorScheme.primary
                        }
                    )
                }
                Column {
                    Text(
                        text = "Network",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        text = uiState.networkSpeed,
                        style = MaterialTheme.typography.headlineSmall
                    )
                }
            }

            // Inference count
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween
            ) {
                Column {
                    Text(
                        text = "Active Inferences",
                        style = MaterialTheme.typography.bodySmall,
                        color = MaterialTheme.colorScheme.onSurfaceVariant
                    )
                    Text(
                        text = "${uiState.activeInferences}",
                        style = MaterialTheme.typography.headlineSmall
                    )
                }
            }
        }
    }
}

@Composable
fun TelemetryItem(label: String, value: String, percentage: Int?) {
    Column {
        Text(
            text = label,
            style = MaterialTheme.typography.bodySmall,
            color = MaterialTheme.colorScheme.onSurfaceVariant
        )
        Text(
            text = value,
            style = MaterialTheme.typography.headlineSmall
        )
        if (percentage != null) {
            LinearProgressIndicator(
                progress = { percentage / 100f },
                modifier = Modifier
                    .width(100.dp)
                    .padding(top = 4.dp),
                color = when {
                    percentage > 85 -> MaterialTheme.colorScheme.error
                    percentage > 60 -> MaterialTheme.colorScheme.tertiary
                    else -> MaterialTheme.colorScheme.primary
                }
            )
        }
    }
}
