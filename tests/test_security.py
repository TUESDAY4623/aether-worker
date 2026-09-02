"""
Tests for aether.security — Pairing and session keys.
"""

from __future__ import annotations

import pytest

from aether.security.auth import SessionKeyManager
from aether.security.pairing import PairingManager


class TestPairingManager:
    def test_initiate_pairing(self):
        mgr = PairingManager(code_length=6)
        result = mgr.initiate_pairing("session_1", "worker_1")
        assert "code" in result
        assert len(result["code"]) == 6
        assert result["session_id"] == "session_1"

    def test_confirm_pairing_success(self):
        mgr = PairingManager()
        code = mgr.initiate_pairing("s1", "w1")["code"]
        success, key_hex = mgr.confirm_pairing("s1", code)
        assert success
        assert key_hex

    def test_confirm_pairing_wrong_code(self):
        mgr = PairingManager()
        mgr.initiate_pairing("s1", "w1")
        success, _ = mgr.confirm_pairing("s1", "000000")
        assert not success

    def test_confirm_no_pending(self):
        mgr = PairingManager()
        success, _ = mgr.confirm_pairing("nonexistent", "123456")
        assert not success

    def test_double_confirm(self):
        mgr = PairingManager()
        code = mgr.initiate_pairing("s1", "w1")["code"]
        mgr.confirm_pairing("s1", code)
        success, _ = mgr.confirm_pairing("s1", code)
        assert success

    def test_cleanup_expired(self):
        mgr = PairingManager()
        mgr.initiate_pairing("s1", "w1")
        assert len(mgr._pending) == 1
        mgr._pending["s1"]["created_at"] = 0
        mgr.cleanup_expired(max_age_s=1)
        assert len(mgr._pending) == 0


class TestSessionKeyManager:
    def test_create_keys(self):
        km = SessionKeyManager()
        key = km.create_session_keys("session_1")
        assert len(key) == 32

    def test_get_key(self):
        km = SessionKeyManager()
        key1 = km.create_session_keys("s1")
        assert km.get_key("s1") == key1

    def test_get_key_missing(self):
        km = SessionKeyManager()
        assert km.get_key("nonexistent") is None

    def test_sign_and_verify(self):
        km = SessionKeyManager()
        km.create_session_keys("s1")
        msg = b"test message"
        sig = km.sign_message("s1", msg)
        assert km.verify_signature("s1", msg, sig)
        assert not km.verify_signature("s1", b"wrong", sig)
        assert not km.verify_signature("nonexistent", msg, sig)

    def test_rotate_key(self):
        km = SessionKeyManager()
        km.create_session_keys("s1")
        key1 = km.get_key("s1")
        new_key = km.rotate_key("s1")
        assert new_key is not None
        assert new_key != key1

    def test_destroy_session(self):
        km = SessionKeyManager()
        km.create_session_keys("s1")
        km.destroy_session("s1")
        assert km.get_key("s1") is None
