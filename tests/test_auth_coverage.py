"""
Tests for aether.security.auth — uncovered lines.
Targets: register_device SecretError fallback (65,90-102),
         sign_message no-session ValueError (79),
         DeviceIdentity basic construction.
"""
from __future__ import annotations

import hmac
import hashlib
import threading
import unittest
from unittest.mock import patch, MagicMock

from aether.security.auth import (
    DeviceIdentity,
    SessionKey,
    SessionKeyManager,
)
from aether.secrets import SecretError


class TestDeviceIdentity(unittest.TestCase):
    def test_create_identity(self):
        ident = DeviceIdentity("dev-1", "Test Phone", "worker")
        assert ident.device_id == "dev-1"
        assert ident.device_name == "Test Phone"
        assert ident.device_type == "worker"
        assert len(ident.public_key) == 32

    def test_public_key_is_random(self):
        id1 = DeviceIdentity("d1", "N1")
        id2 = DeviceIdentity("d2", "N2")
        assert id1.public_key != id2.public_key


class TestSessionKey(unittest.TestCase):
    def test_valid_immediately(self):
        import time
        key = SessionKey(key=b"x" * 32)
        assert key.valid is True
        assert key.nonce == 0

    def test_expires(self):
        key = SessionKey(key=b"x" * 32)
        key.expires_at = time.time() - 1
        assert key.valid is False


class TestSessionKeyManager(unittest.TestCase):
    def _mgr(self):
        return SessionKeyManager()

    def test_create_and_get_key(self):
        mgr = self._mgr()
        key = mgr.create_session_keys("s1")
        assert len(key) == 32
        retrieved = mgr.get_key("s1")
        assert retrieved == key

    def test_get_key_missing_returns_none(self):
        mgr = self._mgr()
        assert mgr.get_key("nonexistent") is None

    def test_rotate_key(self):
        mgr = self._mgr()
        mgr.create_session_keys("s1")
        new_key = mgr.rotate_key("s1")
        assert new_key is not None
        assert len(new_key) == 32
        assert new_key != mgr.get_key("s1")  # rotated

    def test_rotate_key_missing_returns_none(self):
        mgr = self._mgr()
        assert mgr.rotate_key("nonexistent") is None

    def test_destroy_session(self):
        mgr = self._mgr()
        mgr.create_session_keys("s1")
        mgr.destroy_session("s1")
        assert mgr.get_key("s1") is None

    def test_sign_and_verify(self):
        mgr = self._mgr()
        mgr.create_session_keys("s1")
        msg = b"hello world"
        sig = mgr.sign_message("s1", msg)
        assert mgr.verify_signature("s1", msg, sig) is True

    def test_verify_wrong_message_fails(self):
        mgr = self._mgr()
        mgr.create_session_keys("s1")
        sig = mgr.sign_message("s1", b"correct")
        assert mgr.verify_signature("s1", b"wrong", sig) is False

    def test_sign_no_session_raises(self):
        """Line 79: sign_message raises ValueError when session not found."""
        mgr = self._mgr()
        with self.assertRaises(ValueError) as ctx:
            mgr.sign_message("no-session", b"msg")
        assert "no session" in str(ctx.exception).lower()

    def test_verify_no_session_returns_false(self):
        mgr = self._mgr()
        assert mgr.verify_signature("no-session", b"msg", b"sig") is False

    def test_register_device_with_secret(self):
        mgr = self._mgr()
        secret = mgr.register_device("dev-1", secret=b"my-secret-bytes")
        assert secret == b"my-secret-bytes"
        assert mgr._device_secrets["dev-1"] == b"my-secret-bytes"

    def test_register_device_without_secret_loads_from_store(self):
        """Line 90-102: register_device loads from secrets store when no secret provided."""
        mgr = self._mgr()
        with patch("aether.security.auth.load_device_secret", return_value=b"loaded-secret"):
            secret = mgr.register_device("dev-1")
        assert secret == b"loaded-secret"

    def test_register_device_secret_error_generates_ephemeral(self):
        """Lines 94-100: when load_device_secret raises SecretError, generate ephemeral."""
        mgr = self._mgr()
        with patch("aether.security.auth.load_device_secret", side_effect=SecretError("not found")):
            secret = mgr.register_device("dev-1")
        assert len(secret) == 32  # ephemeral secret
        assert mgr._device_secrets["dev-1"] == secret

    def test_compute_hmac(self):
        mgr = self._mgr()
        mgr.register_device("dev-1", secret=b"secret123")
        sig = mgr.compute_hmac("dev-1", b"message")
        assert len(sig) == 32  # blake2b digest size

    def test_compute_hmac_unknown_device(self):
        mgr = self._mgr()
        sig = mgr.compute_hmac("unknown", b"message")
        assert len(sig) == 32  # empty secret still produces HMAC

    def test_verify_hmac_valid(self):
        mgr = self._mgr()
        mgr.register_device("dev-1", secret=b"secret123")
        msg = b"authenticate this"
        sig = mgr.compute_hmac("dev-1", msg)
        assert mgr.verify_hmac("dev-1", msg, sig) is True

    def test_verify_hmac_invalid(self):
        mgr = self._mgr()
        mgr.register_device("dev-1", secret=b"secret123")
        assert mgr.verify_hmac("dev-1", b"msg", b"bad-signature") is False

    def test_verify_pairing_code(self):
        mgr = self._mgr()
        code = "123456"
        expected = hmac.new(b"key", code.encode(), hashlib.blake2b).hexdigest()
        assert mgr.verify_pairing_code(code, expected) is True

    def test_verify_pairing_code_wrong(self):
        mgr = self._mgr()
        assert mgr.verify_pairing_code("123456", "wrong-hmac") is False


class TestThreadSafety(unittest.TestCase):
    def test_concurrent_key_operations(self):
        mgr = SessionKeyManager()
        errors = []

        def worker(i):
            try:
                sid = f"s{i}"
                mgr.create_session_keys(sid)
                mgr.get_key(sid)
                mgr.sign_message(sid, b"data")
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert errors == []


if __name__ == "__main__":
    unittest.main()
