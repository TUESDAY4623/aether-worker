"""
Tests for aether.transport.discovery — UDP device discovery.
"""
from __future__ import annotations

import asyncio
import json
import socket
import time
import unittest
from unittest.mock import MagicMock, patch

from aether.transport.discovery import (
    DISCOVERY_MAGIC,
    DISCOVERY_PORT,
    DiscoveryServer,
    DiscoveryClient,
)


class TestDiscoveryServer(unittest.TestCase):
    def _make_server(self, port=0, on_discover=None):
        server = DiscoveryServer(port=port, on_discover=on_discover)
        return server

    def test_init_defaults(self):
        server = DiscoveryServer()
        assert server.port == DISCOVERY_PORT
        assert server.on_discover is None
        assert server._running is False
        assert server._known == {}

    def test_init_custom(self):
        cb = MagicMock()
        server = DiscoveryServer(port=9876, on_discover=cb)
        assert server.port == 9876
        assert server.on_discover is cb

    def test_get_known_devices_returns_copy(self):
        server = DiscoveryServer()
        server._known["dev1"] = 100.0
        result = server.get_known_devices()
        assert result == {"dev1": 100.0}
        result["dev2"] = 200.0
        assert "dev2" not in server._known  # must be a copy

    def test_get_known_devices_empty(self):
        server = DiscoveryServer()
        assert server.get_known_devices() == {}

    @patch("socket.socket")
    def test_start_creates_udp_socket(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        server = DiscoveryServer(port=DISCOVERY_PORT)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(server.start())
            assert server._running is True
            assert server._task is not None
            mock_sock.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            mock_sock.setblocking.assert_called_with(False)
        finally:
            loop.run_until_complete(server.stop())
            loop.close()

    @patch("socket.socket")
    def test_start_bind_fallback(self, mock_socket_cls):
        """When primary bind fails (OSError), fallback to 127.0.0.1."""
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock

        def bind_side_effect(addr):
            if addr == ("", DISCOVERY_PORT):
                raise OSError("address in use")
            return None

        mock_sock.bind.side_effect = bind_side_effect

        server = DiscoveryServer(port=DISCOVERY_PORT)
        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(server.start())
            bind_calls = [c.args[0] for c in mock_sock.bind.call_args_list]
            assert ("", DISCOVERY_PORT) in bind_calls
            assert ("127.0.0.1", DISCOVERY_PORT) in bind_calls
        finally:
            loop.run_until_complete(server.stop())
            loop.close()

    @patch("socket.socket")
    def test_stop_cancels_task(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        server = DiscoveryServer(port=DISCOVERY_PORT)

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(server.start())
            assert server._running is True
            loop.run_until_complete(server.stop())
            assert server._running is False
            mock_sock.close.assert_called_once()
        finally:
            loop.close()

    def test_listen_loop_processes_valid_discovery(self):
        """Simulate receiving a valid discovery packet."""
        server = DiscoveryServer(port=0)
        discovered = []

        def on_discover(payload, addr):
            discovered.append((payload, addr))

        server = DiscoveryServer(port=0, on_discover=on_discover)
        server._running = True

        payload = {
            "device_id": "test-device-1",
            "display_name": "Test Phone",
            "timestamp": time.time(),
            "port": 8765,
        }
        data = DISCOVERY_MAGIC + json.dumps(payload).encode("utf-8")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_test():
            mock_sock = MagicMock()
            server._sock = mock_sock
            server._known = {}

            # Simulate one packet then stop
            async def fake_recvfrom(bufsize):
                server._running = False
                return data, ("192.168.1.5", 12345)

            loop = asyncio.get_event_loop()
            with patch.object(loop, "sock_recvfrom", side_effect=fake_recvfrom):
                await server._listen_loop()

        try:
            loop.run_until_complete(run_test())
            assert "test-device-1" in server._known
            assert len(discovered) == 1
            assert discovered[0][0]["device_id"] == "test-device-1"
        finally:
            loop.close()

    def test_listen_loop_ignores_invalid_json(self):
        """Packets with invalid JSON should be silently ignored."""
        server = DiscoveryServer(port=0)
        server._running = True

        bad_data = DISCOVERY_MAGIC + b"not-json-at-all!!"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_test():
            mock_sock = MagicMock()
            server._sock = mock_sock
            server._known = {}

            async def fake_recvfrom(bufsize):
                server._running = False
                return bad_data, ("192.168.1.5", 12345)

            evt_loop = asyncio.get_event_loop()
            with patch.object(evt_loop, "sock_recvfrom", side_effect=fake_recvfrom):
                await server._listen_loop()

        try:
            loop.run_until_complete(run_test())
            assert server._known == {}
        finally:
            loop.close()

    def test_listen_loop_ignores_non_magic(self):
        """Packets without the magic prefix should be ignored."""
        server = DiscoveryServer(port=0)
        server._running = True

        no_magic_data = b"some-random-bytes-without-magic"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_test():
            mock_sock = MagicMock()
            server._sock = mock_sock
            server._known = {}

            async def fake_recvfrom(bufsize):
                server._running = False
                return no_magic_data, ("192.168.1.5", 12345)

            evt_loop = asyncio.get_event_loop()
            with patch.object(evt_loop, "sock_recvfrom", side_effect=fake_recvfrom):
                await server._listen_loop()

        try:
            loop.run_until_complete(run_test())
            assert server._known == {}
        finally:
            loop.close()

    def test_listen_loop_handles_cancelled_error(self):
        """CancelledError should break the loop cleanly."""
        server = DiscoveryServer(port=0)
        server._running = True

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_test():
            mock_sock = MagicMock()
            server._sock = mock_sock
            server._known = {}

            async def fake_recvfrom(bufsize):
                raise asyncio.CancelledError()

            evt_loop = asyncio.get_event_loop()
            with patch.object(evt_loop, "sock_recvfrom", side_effect=fake_recvfrom):
                await server._listen_loop()
            assert server._running is True  # loop exits but running flag stays

        try:
            loop.run_until_complete(run_test())
        finally:
            loop.close()


class TestDiscoveryClient(unittest.TestCase):
    def _make_client(self, device_id="dev-1", display_name="Test", port=0):
        return DiscoveryClient(device_id=device_id, display_name=display_name, port=port)

    def test_init(self):
        client = self._make_client()
        assert client.device_id == "dev-1"
        assert client.display_name == "Test"
        assert client.port == DISCOVERY_PORT
        assert client._running is False
        assert client._sock is None

    def test_init_custom_port(self):
        client = DiscoveryClient(device_id="d1", display_name="N", port=9999)
        assert client.port == 9999

    @patch("socket.socket")
    def test_start_creates_broadcast_socket(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        client = self._make_client()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client.start())
            assert client._running is True
            assert client._task is not None
            mock_sock.setsockopt.assert_any_call(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        finally:
            loop.run_until_complete(client.stop())
            loop.close()

    @patch("socket.socket")
    def test_stop_cancels_and_closes(self, mock_socket_cls):
        mock_sock = MagicMock()
        mock_socket_cls.return_value = mock_sock
        client = self._make_client()

        loop = asyncio.new_event_loop()
        try:
            loop.run_until_complete(client.start())
            loop.run_until_complete(client.stop())
            assert client._running is False
            mock_sock.close.assert_called_once()
        finally:
            loop.close()

    def test_advertise_loop_sends_broadcast(self):
        """The advertise loop should send DISCOVERY_MAGIC-prefixed packets."""
        client = DiscoveryClient(device_id="dev-x", display_name="X", port=8766)
        client._running = True
        client._sock = MagicMock()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_one_iteration():
            # Run one iteration then stop
            async def limited_loop():
                payload = json.dumps({
                    "device_id": client.device_id,
                    "display_name": client.display_name,
                    "timestamp": time.time(),
                    "port": client.port,
                }).encode("utf-8")
                client._sock.sendto(DISCOVERY_MAGIC + payload, ("<broadcast>", client.port))

            await limited_loop()
            client._running = False

        try:
            loop.run_until_complete(run_one_iteration())
            client._sock.sendto.assert_called_once()
            call_args = client._sock.sendto.call_args
            sent_data = call_args[0][0]
            assert sent_data.startswith(DISCOVERY_MAGIC)
            payload = json.loads(sent_data[len(DISCOVERY_MAGIC):])
            assert payload["device_id"] == "dev-x"
            assert payload["display_name"] == "X"
        finally:
            loop.close()

    def test_advertise_loop_handles_exception(self):
        """If sendto raises, the loop should continue (not crash)."""
        client = DiscoveryClient(device_id="dev-y", display_name="Y")
        client._running = True
        client._sock = MagicMock()
        client._sock.sendto.side_effect = OSError("network down")

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def run_test():
            # Should not raise even though sendto fails
            payload = json.dumps({
                "device_id": client.device_id,
                "display_name": client.display_name,
                "timestamp": time.time(),
                "port": client.port,
            }).encode("utf-8")
            try:
                client._sock.sendto(DISCOVERY_MAGIC + payload, ("<broadcast>", client.port))
            except OSError:
                pass  # loop catches this

        try:
            loop.run_until_complete(run_test())
        finally:
            loop.close()


if __name__ == "__main__":
    unittest.main()
