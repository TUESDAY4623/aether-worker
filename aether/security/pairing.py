"""
Pairing manager for device discovery and trust establishment.
"""
from __future__ import annotations
import secrets
import string
import time
import threading
from typing import Callable, Optional

from aether.security.auth import SessionKeyManager


PAIRING_CODE_LENGTH = 6
PAIRING_TIMEOUT_SECS = 120


class PairingManager:
    def __init__(self, key_manager: Optional[SessionKeyManager] = None, code_length: int = PAIRING_CODE_LENGTH):
        if key_manager is None:
            key_manager = SessionKeyManager()
        self._key_manager = key_manager
        self._code_length = code_length
        self._pending: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _generate_code(self) -> str:
        chars = string.ascii_uppercase + string.digits
        return "".join(secrets.choice(chars) for _ in range(self._code_length))

    def initiate_pairing(self, session_id: str, device_id: str) -> dict:
        code = self._generate_code()
        entry = {
            "code": code,
            "created_at": time.time(),
            "session_id": session_id,
            "device_id": device_id,
        }
        with self._lock:
            self._pending[session_id] = entry
        return {
            "session_id": session_id,
            "code": code,
        }

    def confirm_pairing(self, session_id: str, code: str) -> tuple[bool, Optional[str]]:
        with self._lock:
            entry = self._pending.get(session_id)
        if entry is None:
            return False, None
        valid = self._key_manager.verify_pairing_code(code, entry["code"])
        if valid:
            self._key_manager.create_session_keys(session_id)
            return True, session_id
        return False, None

    def cleanup_expired(self, max_age_s: int = PAIRING_TIMEOUT_SECS) -> None:
        now = time.time()
        with self._lock:
            expired = [sid for sid, entry in self._pending.items() if now - entry["created_at"] > max_age_s]
            for sid in expired:
                del self._pending[sid]
