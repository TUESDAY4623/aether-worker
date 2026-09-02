"""
Aether Secrets — Secret loading from environment variables or file-based secrets store.

Secrets are NEVER logged or returned in API responses. Use this module for:
- Device identity secrets
- TLS private keys (loaded by config/transport, not here)
- API keys for external services
- Any sensitive credential

Production: mount secrets via `AETHER_SECRETS_DIR` (Kubernetes Secret volume,
systemd EnvironmentFile with mode 600, or Docker secret).
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)


class SecretError(Exception):
    """Raised when a required secret cannot be loaded."""


def _secrets_dir() -> Optional[str]:
    return os.environ.get("AETHER_SECRETS_DIR")


def load_secret(name: str, default: Optional[bytes] = None, required: bool = False) -> bytes:
    """
    Load a secret by name.

    Resolution order:
    1. Environment variable `AETHER_SECRET_{name.upper()}` (hex string or raw)
    2. File `{secrets_dir}/{name}` if `AETHER_SECRETS_DIR` is set
    3. Return `default` if not required

    Raises SecretError if required and not found.
    Never logs the secret value.
    """
    # 1. Environment variable
    env_var = f"AETHER_SECRET_{name.upper()}"
    env_val = os.environ.get(env_var)
    if env_val is not None:
        logger.info("Secret loaded from env: %s", env_var)
        return env_val.encode("utf-8")

    # 2. File-based secrets
    sdir = _secrets_dir()
    if sdir:
        secret_path = os.path.join(sdir, name)
        if os.path.isfile(secret_path):
            try:
                with open(secret_path, "rb") as f:
                    data = f.read().strip()
                logger.info("Secret loaded from file: %s", secret_path)
                return data
            except OSError as exc:
                raise SecretError(f"Cannot read secret file {secret_path}: {exc}") from exc

    # 3. Required check
    if required:
        raise SecretError(
            f"Required secret '{name}' not found. Set env var {env_var} or "
            f"place it in {sdir}/{name} if AETHER_SECRETS_DIR is configured."
        )
    if default is not None:
        return default
    raise SecretError(f"Secret '{name}' not found and no default provided.")


def load_device_secret(device_id: str) -> bytes:
    """Load the per-device identity secret for authentication."""
    safe_id = device_id.replace("/", "_").replace(":", "_")
    return load_secret(f"device_secret_{safe_id}", required=True)


def has_secrets_dir() -> bool:
    """Check if a secrets directory is configured."""
    return _secrets_dir() is not None and os.path.isdir(_secrets_dir())
