"""
Security: pairing, session keys, HMAC auth.
"""
from __future__ import annotations
import hashlib
import hmac
import secrets
import time
import threading
import logging
from typing import Optional

from aether._secrets import load_device_secret, SecretError

logger = logging.getLogger(__name__)

PAIRING_CODE_LENGTH = 6
SESSION_KEY_LENGTH = 32
CHALLENGE_LENGTH = 32


class DeviceIdentity:
    def __init__(self, device_id: str, device_name: str, device_type: str = "worker"):
        self.device_id = device_id
        self.device_name = device_name
        self.device_type = device_type
        self.public_key = secrets.token_bytes(32)


class SessionKey:
    def __init__(self, key: bytes):
        self.key = key
        self.created_at = time.time()
        self.expires_at = time.time() + 3600
        self.nonce = 0

    @property
    def valid(self) -> bool:
        return time.time() < self.expires_at


class SessionKeyManager:
    def __init__(self):
        self._sessions: dict[str, SessionKey] = {}
        self._device_secrets: dict[str, bytes] = {}
        self._lock = threading.Lock()

    def create_session_keys(self, session_id: str) -> bytes:
        key = secrets.token_bytes(SESSION_KEY_LENGTH)
        with self._lock:
            self._sessions[session_id] = SessionKey(key=key)
        return key

    def get_key(self, session_id: str) -> Optional[bytes]:
        with self._lock:
            session = self._sessions.get(session_id)
        if session and session.valid:
            return session.key
        return None

    def rotate_key(self, session_id: str) -> Optional[bytes]:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            new_key = secrets.token_bytes(SESSION_KEY_LENGTH)
            session.key = new_key
            session.created_at = time.time()
            session.nonce += 1
            return new_key

    def destroy_session(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    def sign_message(self, session_id: str, message: bytes) -> bytes:
        key = self.get_key(session_id)
        if key is None:
            raise ValueError(f"No session: {session_id}")
        return hmac.new(key, message, hashlib.blake2b).digest()

    def verify_signature(self, session_id: str, message: bytes, signature: bytes) -> bool:
        key = self.get_key(session_id)
        if key is None:
            return False
        expected = hmac.new(key, message, hashlib.blake2b).digest()
        return hmac.compare_digest(expected, signature)

    def register_device(self, device_id: str, secret: Optional[bytes] = None) -> bytes:
        if secret is None:
            try:
                secret = load_device_secret(device_id)
                logger.info("Loaded device secret from secrets store", extra={"device_id": device_id})
            except SecretError:
                secret = secrets.token_bytes(32)
                logger.warning(
                    "No device secret found for %s — generated ephemeral secret. "
                    "Set AETHER_SECRET_<DEVICE_ID> or mount secrets for production.",
                    extra={"device_id": device_id},
                )
        self._device_secrets[device_id] = secret
        return secret

    def compute_hmac(self, device_id: str, message: bytes) -> bytes:
        secret = self._device_secrets.get(device_id, b"")
        return hmac.new(secret, message, hashlib.blake2b).digest()

    def verify_hmac(self, device_id: str, message: bytes, signature: bytes) -> bool:
        expected = self.compute_hmac(device_id, message)
        return hmac.compare_digest(expected, signature)

    def verify_pairing_code(self, code: str, expected: str) -> bool:
        return hmac.compare_digest(code, expected)
