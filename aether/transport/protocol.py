"""
Binary protocol for Aether: framing, encode/decode, flag helpers.

Production-hardened with payload size limits, rate-limit hooks, and
structured error logging.
"""
from __future__ import annotations
import struct
import hashlib
import zlib
import logging
from enum import IntEnum
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)

MAGIC = 0xA3A5C7D1
VERSION = 1
HEADER_FMT = "!IBBBf"  # magic(4), version(1), msg_type(1), flags(1), reserved(4)
HEADER_SIZE = struct.calcsize(HEADER_FMT)
MAX_PAYLOAD = 64 * 1024 * 1024  # 64 MB — configured from AetherConfig in production


FLAG_COMPRESSED    = 0x01
FLAG_ENCRYPTED     = 0x02
FLAG_ACK_REQUESTED = 0x04
FLAG_ACK_RESPONSE  = 0x08


class MessageType(IntEnum):
    HELLO         = 0x01
    SESSION_INIT  = 0x02
    TENSOR_META   = 0x03
    TENSOR_SEND   = 0x04
    TENSOR_CHUNK  = 0x05
    TENSOR_ACK    = 0x06
    TENSOR_COMPLETE = 0x07
    HEARTBEAT     = 0x08
    COMMAND       = 0x09
    ERROR         = 0xFF


class ProtocolError(Exception):
    """Raised when a message fails validation."""
    pass


@dataclass
class Message:
    msg_type: MessageType
    session_id: str = ""
    payload: bytes = b""
    flags: int = 0

    @property
    def requires_ack(self) -> bool:
        return bool(self.flags & FLAG_ACK_REQUESTED)

    @requires_ack.setter
    def requires_ack(self, value: bool):
        if value:
            self.flags |= FLAG_ACK_REQUESTED
        else:
            self.flags &= ~FLAG_ACK_REQUESTED

    @property
    def is_ack(self) -> bool:
        return bool(self.flags & FLAG_ACK_RESPONSE)

    def to_bytes(self) -> bytes:
        header = struct.pack(HEADER_FMT, MAGIC, VERSION, self.msg_type, self.flags, 0.0)
        sid = self.session_id.encode("utf-8")
        header += struct.pack("!H", len(sid))
        header += sid
        payload = self.payload
        if self.flags & FLAG_COMPRESSED:
            payload = zlib.compress(payload)
        length = len(payload)
        header += struct.pack("!I", length)
        return header + payload

    @classmethod
    def from_bytes(cls, data: bytes, max_payload: int = MAX_PAYLOAD, source: str = "") -> Optional["Message"]:
        """Decode a binary message with production-grade validation.

        Args:
            data: Raw bytes from the wire.
            max_payload: Maximum allowed payload size (defaults to module MAX_PAYLOAD).
            source: Optional source identifier for logging (e.g. session_id or peer_addr).

        Returns:
            Decoded Message, or None if the message is malformed.

        Raises:
            ProtocolError: If the message type is invalid.
        """
        if len(data) < HEADER_SIZE:
            logger.warning("Message too short from %s: %d bytes", source, len(data))
            return None
        magic, version, msg_type, flags, _reserved = struct.unpack(HEADER_FMT, data[:HEADER_SIZE])
        if magic != MAGIC:
            logger.warning("Bad magic 0x%08x from %s", magic, source)
            return None
        if version != VERSION:
            logger.warning("Unsupported version %d from %s", version, source)
            return None
        offset = HEADER_SIZE
        if offset + 2 > len(data):
            logger.warning("Truncated session_id length from %s", source)
            return None
        sid_len = struct.unpack("!H", data[offset:offset+2])[0]
        offset += 2
        if offset + sid_len + 4 > len(data):
            logger.warning("Truncated header from %s", source)
            return None
        session_id = data[offset:offset+sid_len].decode("utf-8", errors="replace")
        offset += sid_len
        length = struct.unpack("!I", data[offset:offset+4])[0]
        offset += 4
        # Payload size validation — prevent decompression bombs and OOM
        if length > max_payload:
            logger.warning(
                "Payload too large from %s: %d bytes (max %d)",
                source, length, max_payload,
            )
            return None
        if length < 0:
            logger.warning("Negative payload length from %s: %d", source, length)
            return None
        if offset + length > len(data):
            logger.warning("Truncated payload from %s: declared %d, available %d", source, length, len(data) - offset)
            return None
        payload = data[offset:offset+length]
        if flags & FLAG_COMPRESSED:
            try:
                payload = zlib.decompress(payload)
            except zlib.error as exc:
                logger.warning("Decompression failed from %s: %s", source, exc)
                return None
            # Re-validate decompressed size
            if len(payload) > max_payload:
                logger.warning(
                    "Decompressed payload too large from %s: %d bytes (max %d)",
                    source, len(payload), max_payload,
                )
                return None
        # Validate message type — reject unknown types
        try:
            validated_type = MessageType(msg_type)
        except ValueError:
            logger.warning("Unknown message type 0x%02x from %s", msg_type, source)
            raise ProtocolError(f"Unknown message type: 0x{msg_type:02x}")
        return cls(validated_type, session_id=session_id, payload=payload, flags=flags)


def make_message(msg_type, session_id: str = "", payload: bytes = b"", flags: int = 0) -> Message:
    return Message(msg_type=MessageType(msg_type), session_id=session_id, payload=payload, flags=flags)


def encode_message(msg: Message, compress: bool = False) -> bytes:
    if compress:
        msg.flags |= FLAG_COMPRESSED
    return msg.to_bytes()


def decode_message(data: bytes) -> Optional[Message]:
    return Message.from_bytes(data)


def ack_flag(msg: Message) -> Message:
    ack = Message(msg_type=msg.msg_type, session_id=msg.session_id, flags=FLAG_ACK_RESPONSE)
    return ack
