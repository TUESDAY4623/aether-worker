"""
Tests for aether.transport.protocol — Binary message framing.
"""

from __future__ import annotations

import struct
import pytest

from aether.transport.protocol import (
    FLAG_ACK_REQUESTED, FLAG_ACK_RESPONSE, FLAG_COMPRESSED, FLAG_ENCRYPTED,
    MessageType, ack_flag, decode_message, encode_message, make_message,
)


class TestProtocol:
    def test_magic_bytes(self):
        from aether.transport.protocol import MAGIC
        assert MAGIC == 0xA3A5C7D1
        assert struct.pack(">I", MAGIC) == b"\xA3\xA5\xC7\xD1"

    def test_encode_hello(self):
        msg = make_message(MessageType.HELLO, "session_1", b"hello world")
        data = encode_message(msg)
        assert len(data) > 0
        assert data[:4] == b"\xA3\xA5\xC7\xD1"
        assert data[4] == 1  # version
        assert data[5] == MessageType.HELLO.value

    def test_roundtrip_simple(self):
        msg = make_message(MessageType.HELLO, "s1", b"payload")
        data = encode_message(msg)
        decoded = decode_message(data)
        assert decoded is not None
        assert decoded.msg_type == MessageType.HELLO
        assert decoded.session_id == "s1"
        assert decoded.payload == b"payload"

    def test_roundtrip_empty_payload(self):
        msg = make_message(MessageType.HELLO, "s1")
        data = encode_message(msg)
        decoded = decode_message(data)
        assert decoded is not None
        assert decoded.payload == b""

    def test_roundtrip_binary_payload(self):
        binary = bytes(range(256))
        msg = make_message(MessageType.TENSOR_CHUNK, "s1", binary)
        data = encode_message(msg)
        decoded = decode_message(data)
        assert decoded is not None
        assert decoded.payload == binary

    def test_roundtrip_all_message_types(self):
        for mt in MessageType:
            msg = make_message(mt, "s1", b"test")
            data = encode_message(msg)
            decoded = decode_message(data)
            assert decoded is not None, f"Failed {mt.name}"
            assert decoded.msg_type == mt

    def test_corrupt_magic_rejected(self):
        msg = make_message(MessageType.HELLO, "s1", b"test")
        data = bytearray(encode_message(msg))
        data[0] = 0xFF
        assert decode_message(bytes(data)) is None

    def test_truncated_rejected(self):
        msg = make_message(MessageType.HELLO, "s1", b"test")
        data = encode_message(msg)
        assert decode_message(data[:10]) is None

    def test_checksum_verification(self):
        msg = make_message(MessageType.HELLO, "s1", b"test")
        data = bytearray(encode_message(msg))
        data[-5] ^= 0xFF
        assert decode_message(bytes(data)) is None

    def test_ack_flag(self):
        msg = make_message(MessageType.HELLO, "s1")
        assert not msg.requires_ack
        msg.flags = FLAG_ACK_REQUESTED
        assert msg.requires_ack
        ack = ack_flag(msg)
        assert ack.is_ack

    def test_compression_flag(self):
        msg = make_message(MessageType.HELLO, "s1", b"test")
        data = encode_message(msg, compress=True)
        decoded = decode_message(data)
        assert decoded is not None
