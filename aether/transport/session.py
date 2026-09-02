"""
Aether Transport — TCP session abstraction and server.
"""
from __future__ import annotations
import asyncio
import logging
import struct
import time
import zlib
from dataclasses import dataclass, field
from typing import Optional, Callable, Awaitable

from aether.transport.protocol import (
    Message, MessageType, MAGIC, VERSION, HEADER_SIZE,
    FLAG_COMPRESSED, FLAG_ENCRYPTED, FLAG_ACK_REQUESTED, FLAG_ACK_RESPONSE,
)

logger = logging.getLogger(__name__)


# ─── AetherSession ──────────────────────────────────────────────────────────

class SessionState:
    CONNECTING = 0
    HELLO_SENT = 1
    HELLO_ACKED = 2
    AUTHENTICATED = 3
    READY = 4
    CLOSING = 5
    CLOSED = 6


@dataclass
class Session:
    session_id: str
    reader: asyncio.StreamReader
    writer: asyncio.StreamWriter
    state: int = 0
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    remote_addr: tuple = ("", 0)
    _buffer: bytearray = field(default_factory=bytearray)

    def touch(self):
        self.last_activity = time.time()

    @property
    def idle_seconds(self) -> float:
        return time.time() - self.last_activity

    def close(self):
        self.state = 5
        if self.writer and not self.writer.is_closing():
            self.writer.close()


@dataclass
class AetherSession:
    """Bidirectional session wrapping a TCP connection."""

    def __init__(self, session_id: str, reader: asyncio.StreamReader,
                 writer: asyncio.StreamWriter):
        self.session_id = session_id
        self.reader = reader
        self.writer = writer
        self.created_at = time.time()
        self.last_activity = time.time()
        self._peer_addr = writer.get_extra_info("peername", ("", 0))
        self._handlers: dict = {}
        self._receive_task = None
        self._keepalive_task = None
        self._closed = False

    @property
    def peer_addr(self) -> str:
        return f"{self._peer_addr[0]}:{self._peer_addr[1]}"

    def touch(self):
        self.last_activity = time.time()

    def on(self, msg_type, handler):
        self._handlers.setdefault(msg_type, []).append(handler)

    async def send(self, msg) -> bool:
        if self._closed or self.writer.is_closing():
            return False
        try:
            data = msg.to_bytes()
            self.writer.write(data)
            await self.writer.drain()
            self.touch()
            return True
        except Exception as exc:
            logger.debug("Send error on %s: %s", self.session_id, exc)
            return False

    async def start_receive_loop(self):
        if self._receive_task:
            return
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def start_keepalive(self, interval_s: float = 30.0):
        if self._keepalive_task:
            return
        self._keepalive_task = asyncio.create_task(self._keepalive_loop(interval_s))

    async def _receive_loop(self):
        buf = bytearray()
        while not self._closed:
            try:
                data = await asyncio.wait_for(self.reader.read, timeout=60.0)
            except asyncio.TimeoutError:
                continue
            if not data:
                break
            buf.extend(data)
            self.touch()
            while True:
                msg = _decode(buf)
                if msg is None:
                    break
                del buf[:len(msg.raw_bytes)]
                await self._dispatch(msg)

    async def _keepalive_loop(self, interval_s: float):
        while not self._closed:
            await asyncio.sleep(interval_s)
            if self._closed:
                break
            await self.send(Message(msg_type=MessageType.HEARTBEAT, session_id=self.session_id))

    async def _dispatch(self, msg):
        handlers = self._handlers.get(msg.msg_type, [])
        for h in handlers:
            try:
                await h(self, msg)
            except Exception:
                logger.exception("Handler error for %s", msg.msg_type)

    async def close(self):
        self._closed = True
        if self._keepalive_task:
            self._keepalive_task.cancel()
        if self._receive_task:
            self._receive_task.cancel()
        if self.writer and not self.writer.is_closing():
            try:
                await self.send(Message(msg_type=MessageType.GOODBYE, session_id=self.session_id))
            except Exception:
                pass
            self.writer.close()
            try:
                await self.writer.wait_closed()
            except Exception:
                pass


# ─── Session Manager ────────────────────────────────────────────────────────

class SessionManager:
    def __init__(self, max_sessions: int = 100, idle_timeout_s: float = 300.0):
        self._sessions: dict[str, Session] = {}
        self._max = max_sessions
        self._idle_timeout = idle_timeout_s
        self._lock = asyncio.Lock()

    async def add(self, session: Session) -> bool:
        async with self._lock:
            if len(self._sessions) >= self._max:
                return False
            self._sessions[session.session_id] = session
            return True

    async def remove(self, session_id: str):
        async with self._lock:
            self._sessions.pop(session_id, None)

    async def get(self, session_id: str):
        async with self._lock:
            return self._sessions.get(session_id)

    async def cleanup_idle(self) -> int:
        import time as _time
        now = _time.time()
        async with self._lock:
            dead = [sid for sid, s in self._sessions.items() if now - s.last_activity > self._idle_timeout]
        count = 0
        for sid in dead:
            s = await self.get(sid)
            if s:
                s.close()
                await self.remove(sid)
                count += 1
        return count

    async def all_sessions(self):
        async with self._lock:
            return dict(self._sessions)

    @property
    def count(self) -> int:
        return len(self._sessions)


# ─── TCP Server ─────────────────────────────────────────────────────────────

class AetherServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8765,
                 session_mgr: Optional[SessionManager] = None,
                 on_message: Optional[Callable] = None):
        self.host = host
        self.port = port
        self.session_mgr = session_mgr or SessionManager()
        self.on_message = on_message
        self._server = None
        self._cleanup_task = None
        self._running = False

    async def start(self):
        self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
        self._running = True
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        logger.info("Aether TCP server on %s:%d", self.host, self.port)

    async def stop(self):
        self._running = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for session in (await self.session_mgr.all_sessions()).values():
            session.close()

    async def _cleanup_loop(self):
        while self._running:
            await asyncio.sleep(30)
            n = await self.session_mgr.cleanup_idle()
            if n:
                logger.info("Cleaned up %d idle sessions", n)

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info("peername")
        session = Session(session_id="", reader=reader, writer=writer, remote_addr=addr)
        try:
            await self._session_loop(session)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.warning("Session error: %s", exc)
        finally:
            session.close()
            if session.session_id:
                await self.session_mgr.remove(session.session_id)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

    async def _session_loop(self, session: Session):
        buf = session._buffer
        while session.state != 6:
            try:
                data = await asyncio.wait_for(session.reader.read, timeout=60.0)
            except asyncio.TimeoutError:
                if session.idle_seconds > 300:
                    break
                continue
            if not data:
                break
            buf.extend(data)
            session.touch()
            while True:
                msg = _decode(buf)
                if msg is None:
                    break
                del buf[:len(msg.raw_bytes)]
                if not session.session_id:
                    session.session_id = msg.session_id
                    await self.session_mgr.add(session)
                    logger.info("Session established: %s from %s", msg.session_id, session.remote_addr)
                if self.on_message:
                    await self.on_message(session, msg)


# ─── Protocol decode helper ─────────────────────────────────────────────────

def _decode(buf: bytearray) -> Optional[Message]:
    if len(buf) < HEADER_SIZE:
        return None
    if struct.unpack("!I", buf[:4])[0] != MAGIC:
        return None
    _, _, msg_type, flags, _ = struct.unpack("!IBBBf", buf[:HEADER_SIZE])
    offset = HEADER_SIZE
    if offset + 2 > len(buf):
        return None
    sid_len = struct.unpack("!H", buf[offset:offset+2])[0]
    offset += 2
    if offset + sid_len + 4 > len(buf):
        return None
    session_id = buf[offset:offset+sid_len].decode("utf-8", errors="replace")
    offset += sid_len
    length = struct.unpack("!I", buf[offset:offset+4])[0]
    offset += 4
    total = offset + length
    if total > len(buf):
        return None
    payload = bytes(buf[offset:total])
    if flags & FLAG_COMPRESSED:
        payload = zlib.decompress(payload)
    msg = Message(msg_type=MessageType(msg_type), session_id=session_id, payload=payload, flags=flags)
    msg.raw_bytes = bytes(buf[:total])
    return msg
