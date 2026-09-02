"""
Aether Transport — Chunked, resumable tensor transfer.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from aether.transport.protocol import MessageType, make_message

logger = logging.getLogger(__name__)


@dataclass
class TransferJob:
    transfer_id: str
    tensor_id: str
    session_id: str
    total_size: int
    chunk_size: int
    destination: str
    received_bytes: int = 0
    chunks: dict[int, bytes] = field(default_factory=dict)
    checksum: str = ""
    started_at: float = field(default_factory=time.time)
    completed: bool = False
    error: str = ""


class TensorTransferManager:
    """Manages chunked, resumable tensor transfers."""

    def __init__(self, chunk_size: int = 4 * 1024 * 1024):
        self.chunk_size = chunk_size
        self._incoming: dict[str, TransferJob] = {}
        self._outgoing: dict[str, TransferJob] = {}
        self._callbacks: dict[str, Callable] = {}

    def send_tensor(
        self, session, tensor_id: str, data: bytes, destination: str,
        on_complete: Callable | None = None,
    ) -> str:
        import uuid
        transfer_id = uuid.uuid4().hex[:12]
        checksum = hashlib.sha256(data).hexdigest()[:16]
        job = TransferJob(
            transfer_id=transfer_id, tensor_id=tensor_id, session_id=session.session_id,
            total_size=len(data), chunk_size=self.chunk_size,
            destination=destination, checksum=checksum,
        )
        self._outgoing[transfer_id] = job
        if on_complete:
            self._callbacks[transfer_id] = on_complete

        header = json.dumps({
            "transfer_id": transfer_id, "tensor_id": tensor_id,
            "total_size": len(data), "chunk_size": self.chunk_size,
            "checksum": checksum, "destination": destination,
        }).encode("utf-8")
        asyncio.create_task(session.send(
            make_message(MessageType.TENSOR_SEND, session.session_id, header)
        ))
        asyncio.create_task(self._send_chunks(session, job, data))
        logger.info("Transfer %s: %s, %.1f MB -> %s",
                     transfer_id, tensor_id, len(data) / 1e6, destination)
        return transfer_id

    async def _send_chunks(self, session, job: TransferJob, data: bytes):
        offset = 0
        seq = 0
        while offset < len(data):
            chunk = data[offset:offset + self.chunk_size]
            import base64
            chunk_msg = json.dumps({
                "transfer_id": job.transfer_id, "tensor_id": job.tensor_id,
                "sequence": seq, "offset": offset,
                "payload": base64.b64encode(chunk).decode("ascii"),
            }).encode("utf-8")
            ok = await session.send(make_message(MessageType.TENSOR_CHUNK, job.session_id, chunk_msg))
            if not ok:
                job.error = "connection_lost"
                break
            offset += len(chunk)
            seq += 1
            if seq % 4 == 0:
                await asyncio.sleep(0)

        if offset >= len(data):
            await session.send(make_message(
                MessageType.TENSOR_COMPLETE, job.session_id,
                json.dumps({"transfer_id": job.transfer_id, "checksum": job.checksum}).encode(),
            ))
            job.completed = True
            logger.info("Transfer %s complete", job.transfer_id)
            cb = self._callbacks.pop(job.transfer_id, None)
            if cb:
                cb(job)
        else:
            logger.error("Transfer %s failed at %d/%d", job.transfer_id, offset, len(data))

    def handle_chunk(self, session_id: str, payload: bytes) -> Optional[bytes]:
        """Process incoming chunk. Returns full tensor when complete, else None."""
        try:
            msg = json.loads(payload)
        except json.JSONDecodeError:
            return None
        transfer_id = msg.get("transfer_id", "")
        job = self._incoming.get(transfer_id)
        if not job:
            job = TransferJob(
                transfer_id=transfer_id, tensor_id=msg.get("tensor_id", ""),
                session_id=session_id, total_size=msg.get("total_size", 0),
                chunk_size=msg.get("chunk_size", 4 * 1024 * 1024),
                destination=msg.get("destination", ""), checksum=msg.get("checksum", ""),
            )
            self._incoming[transfer_id] = job
        import base64
        seq = msg.get("sequence", 0)
        job.chunks[seq] = base64.b64decode(msg.get("payload", b""))
        job.received_bytes += len(job.chunks[seq])
        if job.received_bytes >= job.total_size:
            full = b"".join(job.chunks[i] for i in sorted(job.chunks))
            del self._incoming[transfer_id]
            logger.info("Reassembled tensor %s: %d bytes, %d chunks",
                         job.tensor_id, len(full), len(job.chunks))
            return full
        return None

    @property
    def active_transfers(self) -> int:
        return len(self._outgoing) + len(self._incoming)

    def cancel(self, transfer_id: str):
        self._outgoing.pop(transfer_id, None)
        self._incoming.pop(transfer_id, None)
