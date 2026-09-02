"""
Aether Controller — Main application tying all components together.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import time
from typing import Optional

import uvicorn

from aether.config import (
    AetherConfig,
    get_config,
    init_config,
    setup_logging,
)
from aether.memory.manager import MemoryManager
from aether.security.auth import SessionKeyManager
from aether.security.pairing import PairingManager
from aether.telemetry.collector import TelemetryCollector
from aether.thermal.manager import ThermalManager
from aether.transport.discovery import DiscoveryServer
from aether.transport.protocol import MessageType, make_message
from aether.transport.session import AetherSession, AetherServer
from aether.transport.tensor_transfer import TensorTransferManager
from aether.scheduler.rule_based import RuleBasedScheduler
from aether.workers.registry import WorkerDevice, WorkerRegistry
from aether.controller.api import app as fastapi_app

logger = logging.getLogger(__name__)


class AetherController:
    """Main Controller service — the brain of the Aether distributed fabric."""

    def __init__(self, config: Optional[AetherConfig] = None):
        self.config = config or get_config()
        self.host = self.config.controller_host
        self.port = self.config.controller_port
        self.memory = MemoryManager()
        self.key_manager = SessionKeyManager()
        self.pairing = PairingManager(key_manager=self.key_manager)
        self.telemetry = TelemetryCollector()
        self.thermal = ThermalManager(telemetry=self.telemetry)
        self.workers = WorkerRegistry(discovery_timeout_s=self.config.discovery_timeout_s)
        self.scheduler = RuleBasedScheduler(
            thermal_manager=self.thermal, telemetry=self.telemetry,
        )
        self.transfer_mgr = TensorTransferManager(chunk_size=self.config.tensor_chunk_size)
        self.transport: Optional[AetherServer] = None
        self.discovery: Optional[DiscoveryServer] = None
        self._sessions: dict[str, AetherSession] = {}
        self._shutdown = False
        self._background_tasks: list[asyncio.Task] = []
        self.thermal.add_listener(self._on_thermal_event)
        self._api_server: Optional[uvicorn.Server] = None
        self._api_task: Optional[asyncio.Task] = None

    def _wire_api_state(self) -> None:
        """Share controller state with the FastAPI app."""
        st = fastapi_app.state
        st.config = self.config
        st.start_time = time.time()
        st.workers = self.workers
        st.telemetry = self.telemetry
        st.thermal = self.thermal
        st.transfer_mgr = self.transfer_mgr
        st.key_manager = self.key_manager
        st.pairing = self.pairing
        st._sessions = self._sessions
        st.transport_running = True

    async def start(self) -> None:
        """Start all controller subsystems."""
        self._wire_api_state()
        logger.info("=" * 60)
        logger.info("  Aether Controller v0.1.0 — Phase 1")
        logger.info("  Listening on %s:%d", self.host, self.port)
        logger.info("  Discovery on UDP %d", self.config.discovery_port)
        if self.config.api_enabled:
            logger.info("  REST API on http://%s:%d", self.config.api_host, self.config.api_port)
        logger.info("=" * 60)

        # Transport layer
        self.transport = AetherServer(
            host=self.host, port=self.port,
            on_message=self._on_session_message,
        )
        await self.transport.start()

        # Discovery layer
        self.discovery = DiscoveryServer(
            port=self.config.discovery_port,
            on_discover=self._on_worker_discovered,
        )
        await self.discovery.start()

        # REST API
        if self.config.api_enabled:
            api_cfg = uvicorn.Config(
                fastapi_app,
                host=self.config.api_host,
                port=self.config.api_port,
                log_level="warning",
                access_log=False,
            )
            self._api_server = uvicorn.Server(api_cfg)
            self._api_task = asyncio.create_task(self._api_server.serve())

        # Background loops
        self._background_tasks = [
            asyncio.create_task(self._thermal_loop()),
            asyncio.create_task(self._stale_check_loop()),
            asyncio.create_task(self._pairing_cleanup_loop()),
        ]
        logger.info("Aether Controller ready. Waiting for workers...")

    async def run(self) -> None:
        """Run the controller until shutdown signal."""
        await self.start()
        stop = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:
                signal.signal(sig, lambda s, f: loop.call_soon_threadsafe(stop.set))
        try:
            await stop.wait()
        except asyncio.CancelledError:
            pass
        finally:
            await self.shutdown()

    async def shutdown(self, timeout: float = 10.0) -> None:
        """Graceful shutdown with timeout enforcement."""
        if self._shutdown:
            return
        self._shutdown = True
        logger.info("Shutting down Aether Controller...")

        # Cancel background tasks
        for task in self._background_tasks:
            task.cancel()
        if self._background_tasks:
            await asyncio.gather(*self._background_tasks, return_exceptions=True)
            self._background_tasks.clear()

        # Close all sessions
        if self._sessions:
            logger.info("Closing %d active sessions...", len(self._sessions))
            close_tasks = [asyncio.wait_for(s.close(), timeout=timeout) for s in self._sessions.values()]
            results = await asyncio.gather(*close_tasks, return_exceptions=True)
            failed = sum(1 for r in results if isinstance(r, Exception))
            if failed:
                logger.warning("%d sessions failed to close cleanly", failed)
            self._sessions.clear()

        # Stop REST API
        if self._api_server is not None:
            logger.info("Stopping REST API...")
            self._api_server.should_exit = True
            if self._api_task is not None:
                try:
                    await asyncio.wait_for(self._api_task, timeout=timeout)
                except asyncio.TimeoutError:
                    logger.warning("REST API did not stop within timeout")
            self._api_server = None
            self._api_task = None

        # Stop transport and discovery
        if self.transport:
            await asyncio.wait_for(self.transport.stop(), timeout=timeout)
            self.transport = None
        if self.discovery:
            await asyncio.wait_for(self.discovery.stop(), timeout=timeout)
            self.discovery = None

        logger.info("Aether Controller stopped.")

    # ── Session handling ─────────────────────────────────────────────────────

    async def _on_session_message(self, session: AetherSession, msg):
        if not session.session_id:
            session.session_id = msg.session_id
            self._sessions[session.session_id] = session
            logger.info("New session %s from %s", msg.session_id, session.remote_addr)
        session.touch()
        try:
            if msg.msg_type == MessageType.HELLO:
                await session.send(make_message(MessageType.HELLO_ACK, session.session_id))
            elif msg.msg_type == MessageType.PAIRING_REQUEST:
                data = json.loads(msg.payload)
                code_info = self.pairing.initiate_pairing(session.session_id, data.get("device_id", "unknown"))
                self.workers.register(WorkerDevice(
                    device_id=data.get("device_id", "unknown"),
                    display_name=data.get("display_name", ""),
                    session_id=session.session_id,
                    peer_addr=f"{session.remote_addr[0]}:{session.remote_addr[1]}",
                ))
                logger.info("Pairing %s — code: %s", data.get("device_id"), code_info["code"])
            elif msg.msg_type == MessageType.PAIRING_CONFIRM:
                data = json.loads(msg.payload)
                success, key_hex = self.pairing.confirm_pairing(session.session_id, data.get("code", ""))
                if success:
                    for w in self.workers.all_workers:
                        if w.session_id == session.session_id:
                            w.paired = True
                            break
                    await session.send(make_message(
                        MessageType.PAIRING_CONFIRM, session.session_id,
                        json.dumps({"key": key_hex}).encode(),
                    ))
                else:
                    await session.send(make_message(MessageType.PAIRING_REJECT, session.session_id))
            elif msg.msg_type == MessageType.TELEMETRY_REPORT:
                data = json.loads(msg.payload)
                tel = DeviceTelemetry(
                    device_id=data.get("device_id", session.session_id),
                    temperature_c=data.get("temperature_c", 0.0),
                    memory_total_mb=data.get("memory_total_mb", 0),
                    memory_available_mb=data.get("memory_available_mb", 0),
                    memory_aether_reserved_mb=data.get("memory_aether_reserved_mb", 0),
                    cpu_utilization_pct=data.get("cpu_utilization_pct", 0.0),
                    npu_utilization_pct=data.get("npu_utilization_pct", 0.0),
                    battery_pct=data.get("battery_pct", 0.0),
                    is_charging=data.get("is_charging", False),
                    network_latency_ms=data.get("network_latency_ms", 0.0),
                    tensor_bandwidth_mbps=data.get("tensor_bandwidth_mbps", 0.0),
                    available=data.get("available", True),
                )
                self.telemetry.report(tel)
                for w in self.workers.all_workers:
                    if w.device_id == tel.device_id:
                        w.last_seen = time.time()
            elif msg.msg_type == MessageType.GOODBYE:
                for w in self.workers.all_workers:
                    if w.session_id == session.session_id:
                        self.workers.mark_unavailable(w.device_id)
                        break
        except Exception as exc:
            logger.error("Message handling error: %s", exc, exc_info=True)

    def _on_worker_discovered(self, payload: dict, addr: tuple):
        device_id = payload.get("device_id", "unknown")
        display_name = payload.get("display_name", device_id)
        logger.info("Discovered: %s (%s) at %s:%s",
                     device_id, display_name, addr[0], payload.get("port", "?"))

    def _on_thermal_event(self, event):
        if event.new_state.value == "critical":
            logger.warning("Device %s CRITICAL — withdrawing compute", event.device_id)

    # ── Background loops ─────────────────────────────────────────────────────

    async def _thermal_loop(self):
        while not self._shutdown:
            try:
                for device_id in list(self.telemetry.all_latest().keys()):
                    if self._shutdown:
                        break
                    self.thermal.update_device(device_id)
                await asyncio.sleep(5.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Thermal loop error: %s", exc, exc_info=True)
                await asyncio.sleep(5.0)

    async def _stale_check_loop(self):
        while not self._shutdown:
            try:
                stale_ids = self.workers.check_stale()
                for device_id in stale_ids:
                    logger.info("Worker %s is stale, marking unavailable", device_id)
                    self.workers.mark_unavailable(device_id)
                await asyncio.sleep(self.config.discovery_interval_s)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Stale check loop error: %s", exc, exc_info=True)
                await asyncio.sleep(self.config.discovery_interval_s)

    async def _pairing_cleanup_loop(self):
        while not self._shutdown:
            try:
                self.pairing.cleanup_expired()
                await asyncio.sleep(30.0)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Pairing cleanup loop error: %s", exc, exc_info=True)
                await asyncio.sleep(30.0)


def main() -> None:
    """Entry point: initialize config, logging, and run the controller."""
    # Initialize configuration (validates, applies env overrides)
    config = init_config()
    setup_logging(config)
    logger.info("Aether Controller starting with config", extra={
        "controller_host": config.controller_host,
        "controller_port": config.controller_port,
        "discovery_port": config.discovery_port,
        "log_level": config.log_level,
        "tls_enabled": config.tls_enabled,
    })

    controller = AetherController(config=config)
    try:
        asyncio.run(controller.run())
    except KeyboardInterrupt:
        logger.info("Interrupted by user")


if __name__ == "__main__":
    main()
