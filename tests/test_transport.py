"""
Tests for aether.transport.session and aether.api.server.
"""
from __future__ import annotations
import asyncio
import pytest
from unittest.mock import MagicMock, patch

from aether.transport.session import AetherServer, AetherSession, SessionManager
from aether.transport.protocol import MessageType, make_message
from aether.api.server import api


class TestSessionManager:
    @pytest.mark.asyncio
    async def test_add_remove(self):
        mgr = SessionManager()
        reader = MagicMock()
        writer = MagicMock()
        session = AetherSession("s1", reader, writer)
        ok = await mgr.add(session)
        assert ok is True
        assert mgr.count == 1
        await mgr.remove("s1")
        assert mgr.count == 0

    @pytest.mark.asyncio
    async def test_max_sessions(self):
        mgr = SessionManager(max_sessions=2)
        reader = MagicMock()
        writer = MagicMock()
        await mgr.add(AetherSession("s1", reader, writer))
        await mgr.add(AetherSession("s2", reader, writer))
        ok = await mgr.add(AetherSession("s3", reader, writer))
        assert ok is False

    @pytest.mark.asyncio
    async def test_cleanup_idle(self):
        from aether.transport.session import Session
        mgr = SessionManager(idle_timeout_s=1)
        reader = MagicMock()
        writer = MagicMock()
        session = Session(session_id="s1", reader=reader, writer=writer)
        session.last_activity = 0  # very old
        await mgr.add(session)
        n = await mgr.cleanup_idle()
        assert n == 1


class TestAetherServer:
    @pytest.mark.asyncio
    async def test_start_stop(self):
        server = AetherServer(host="127.0.0.1", port=18765)
        await server.start()
        assert server._server is not None
        await server.stop()
        assert server._running is False


class TestApiEndpoints:
    @pytest.fixture
    def client(self):
        from fastapi.testclient import TestClient
        return TestClient(api)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "version" in data

    def test_list_workers_empty(self, client):
        resp = client.get("/workers")
        assert resp.status_code == 503  # API not initialized

    def test_get_worker_not_found(self, client):
        resp = client.get("/workers/nonexistent")
        assert resp.status_code == 503

    def test_get_telemetry_not_found(self, client):
        resp = client.get("/telemetry/nonexistent")
        assert resp.status_code == 503

    def test_partition_not_initialized(self, client):
        resp = client.post("/partition", json={
            "model_id": "m1", "model_name": "Test", "layers": [],
            "device_ids": [], "strategy": "memory_only",
        })
        assert resp.status_code == 503
