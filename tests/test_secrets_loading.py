"""
Tests for aether.secrets — secret loading from env vars and mocked file store.
Uses unittest.mock exclusively to avoid filesystem path patterns.
"""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch, mock_open, MagicMock

from aether.secrets import (
    SecretError,
    has_secrets_dir,
    load_device_secret,
    load_secret,
)


class TestLoadSecretEnvVar(unittest.TestCase):
    def test_load_from_env_string(self):
        with patch.dict(os.environ, {"AETHER_SECRET_MY_KEY": "my-secret-value"}):
            result = load_secret("my_key")
        assert result == b"my-secret-value"

    def test_load_from_env_bytes_encoded(self):
        with patch.dict(os.environ, {"AETHER_SECRET_API_KEY": "hello-world"}):
            result = load_secret("api_key")
        assert result == b"hello-world"

    def test_load_missing_env_no_default_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SecretError):
                load_secret("nonexistent_key")

    def test_load_missing_env_with_default_returns_default(self):
        with patch.dict(os.environ, {}, clear=True):
            result = load_secret("optional_key", default=b"fallback")
        assert result == b"fallback"

    def test_load_missing_env_required_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SecretError) as ctx:
                load_secret("required_key", required=True)
        assert "required_key" in str(ctx.exception)

    def test_load_missing_env_not_required_no_default_raises(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SecretError):
                load_secret("x")

    def test_env_var_takes_priority_over_file(self):
        with patch.dict(os.environ, {
            "AETHER_SECRET_MY_KEY": "env-value",
            "AETHER_SECRETS_DIR": "/tmp/fake",
        }):
            result = load_secret("my_key")
        assert result == b"env-value"


class TestLoadSecretFromFile(unittest.TestCase):
    def test_file_content_returned(self):
        m = mock_open(read_data=b"file-secret")
        with patch("builtins.open", m):
            with patch("os.path.isfile", return_value=True):
                with patch.dict(os.environ, {"AETHER_SECRETS_DIR": "/tmp/fake"}):
                    result = load_secret("my_key")
        assert result == b"file-secret"

    def test_file_content_strips_whitespace(self):
        m = mock_open(read_data=b"  secret-with-spaces  ")
        with patch("builtins.open", m):
            with patch("os.path.isfile", return_value=True):
                with patch.dict(os.environ, {"AETHER_SECRETS_DIR": "/tmp/fake"}):
                    result = load_secret("my_key")
        assert result == b"secret-with-spaces"

    def test_file_not_found_raises_when_required(self):
        with patch("os.path.isfile", return_value=False):
            with patch.dict(os.environ, {"AETHER_SECRETS_DIR": "/tmp/fake"}):
                with self.assertRaises(SecretError):
                    load_secret("missing_key", required=True)

    def test_file_not_found_returns_default(self):
        with patch("os.path.isfile", return_value=False):
            with patch.dict(os.environ, {"AETHER_SECRETS_DIR": "/tmp/fake"}):
                result = load_secret("missing_key", default=b"default-val")
        assert result == b"default-val"


class TestLoadDeviceSecret(unittest.TestCase):
    def test_simple_device_id(self):
        with patch.dict(os.environ, {"AETHER_SECRET_DEVICE_SECRET_DEV-1": "dev-secret"}):
            result = load_device_secret("dev-1")
        assert result == b"dev-secret"

    def test_special_chars_sanitized(self):
        with patch.dict(os.environ, {"AETHER_SECRET_DEVICE_SECRET_DEV_1": "sanitized"}):
            result = load_device_secret("dev/1")
        assert result == b"sanitized"

    def test_required_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(SecretError):
                load_device_secret("unknown-device")


class TestHasSecretsDir(unittest.TestCase):
    def test_no_env_returns_false(self):
        with patch.dict(os.environ, {}, clear=True):
            assert has_secrets_dir() is False

    def test_nonexistent_path_returns_false(self):
        with patch.dict(os.environ, {"AETHER_SECRETS_DIR": "/nonexistent/path/xyz"}):
            assert has_secrets_dir() is False

    def test_real_dir_returns_true(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"AETHER_SECRETS_DIR": tmpdir}):
                assert has_secrets_dir() is True

    def test_file_path_returns_false(self):
        import tempfile
        with tempfile.NamedTemporaryFile() as tmpfile:
            with patch.dict(os.environ, {"AETHER_SECRETS_DIR": tmpfile.name}):
                assert has_secrets_dir() is False


if __name__ == "__main__":
    unittest.main()
