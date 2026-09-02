package com.aether.worker

import android.app.Application
import android.os.Bundle
import android.widget.Button
import android.widget.EditText
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.ViewModelProvider

class MainActivity : AppCompatActivity() {
    private lateinit var viewModel: AetherWorkerViewModel

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        val service = (application as AetherWorkerApp).getWorkerService()
        viewModel = ViewModelProvider(this, AetherWorkerViewModelFactory(service))
            .get(AetherWorkerViewModel::class.java)

        val statusText = findViewById<TextView>(R.id.status_text)
        val startBtn = findViewById<Button>(R.id.start_btn)
        val stopBtn = findViewById<Button>(R.id.stop_btn)
        val hostInput = findViewById<EditText>(R.id.controller_host)
        val pairingView = findViewById<TextView>(R.id.pairing_code)
        val logView = findViewById<TextView>(R.id.log_text)

        hostInput.setText(viewModel.uiState.value.controllerHost)

        lifecycleScope.launchWhenStarted {
            viewModel.uiState.collect { state ->
                statusText.text = state.statusText
                if (state.state == WorkerState.PAIRING) {
                    pairingView.visibility = android.view.View.VISIBLE
                }
            }
        }

        startBtn.setOnClickListener {
            val host = hostInput.text.toString().trim()
            if (host.isNotEmpty()) {
                viewModel.setControllerHost(host)
            }
            viewModel.start()
        }

        stopBtn.setOnClickListener { viewModel.stop() }
    }
}
