"""
Tests for aether.transport.tensor_transfer — Chunked transfer.
"""

from __future__ import annotations

import asyncio
import json
import base64
import pytest

from aether.transport.tensor_transfer import TensorTransferManager, TransferJob


class FakeSession:
    def __init__(self):
        self.session_id = "test_session"
        self.sent = []

    async def send(self, msg):
        self.sent.append(msg)
        return True


class TestTensorTransferManager:
    @pytest.mark.asyncio
    async def test_send_tensor(self):
        mgr = TensorTransferManager(chunk_size=1024)
        session = FakeSession()
        data = b"x" * 2500
        transfer_id = mgr.send_tensor(session, "tensor_1", data, "phone_1")
        assert transfer_id
        assert transfer_id in mgr._outgoing
        await asyncio.sleep(0.1)
        assert len(session.sent) >= 4  # header + chunks + complete

    @pytest.mark.asyncio
    async def test_handle_chunk_reassembly(self):
        mgr = TensorTransferManager(chunk_size=1024)
        data = b"hello world"
        payload = json.dumps({
            "transfer_id": "tx1", "tensor_id": "t1",
            "total_size": len(data), "chunk_size": 1024,
            "checksum": "abc123", "destination": "phone_1",
            "sequence": 0,
            "payload": base64.b64encode(data).decode(),
        }).encode("utf-8")
        result = mgr.handle_chunk("s1", payload)
        assert result == data

    def test_handle_chunk_invalid_json(self):
        mgr = TensorTransferManager()
        assert mgr.handle_chunk("s1", b"not json") is None

    def test_cancel_transfer(self):
        mgr = TensorTransferManager()
        job = TransferJob(
            transfer_id="tx1", tensor_id="t1", session_id="s1",
            total_size=100, chunk_size=1024, destination="d1",
        )
        mgr._outgoing["tx1"] = job
        mgr._incoming["tx2"] = job
        mgr.cancel("tx1")
        assert "tx1" not in mgr._outgoing
        assert "tx1" not in mgr._incoming

    def test_active_transfers_count(self):
        mgr = TensorTransferManager()
        assert mgr.active_transfers == 0
        job = TransferJob(
            transfer_id="tx1", tensor_id="t1", session_id="s1",
            total_size=100, chunk_size=1024, destination="d1",
        )
        mgr._outgoing["tx1"] = job
        mgr._incoming["tx2"] = job
        assert mgr.active_transfers == 2
