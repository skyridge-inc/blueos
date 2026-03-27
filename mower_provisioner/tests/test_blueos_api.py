"""Tests for blueos_api module — HTTP client with mocked responses."""

from __future__ import annotations

import httpx
import pytest
import respx

from mower_provisioner.blueos_api import BlueOSClient
from mower_provisioner.exceptions import BlueOSConnectionError

BASE_URL = "http://blueos.local"


@pytest.fixture
def client():
    """Create a BlueOSClient with short timeout for tests."""
    c = BlueOSClient(BASE_URL, timeout=httpx.Timeout(1.0))
    yield c
    c.close()


class TestGetJson:
    @respx.mock
    def test_success(self, client):
        respx.get(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            return_value=httpx.Response(200, json="blueos")
        )
        assert client.get_hostname() == "blueos"

    @respx.mock
    def test_http_error_returns_none(self, client):
        # First call succeeds to mark as connected
        respx.get(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            return_value=httpx.Response(200, json="blueos")
        )
        respx.get(f"{BASE_URL}/ardupilot-manager/v1.0/board").mock(
            return_value=httpx.Response(500)
        )
        client.get_hostname()  # establish connection
        assert client.get_board() is None

    @respx.mock
    def test_connection_error_raises_on_first_call(self, client):
        respx.get(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            side_effect=httpx.ConnectError("refused")
        )
        with pytest.raises(BlueOSConnectionError, match="Cannot reach"):
            client.get_hostname()

    @respx.mock
    def test_connection_error_returns_none_after_connected(self, client):
        respx.get(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            return_value=httpx.Response(200, json="blueos")
        )
        respx.get(f"{BASE_URL}/ardupilot-manager/v1.0/board").mock(
            side_effect=httpx.ConnectError("refused")
        )
        client.get_hostname()  # establish connection
        assert client.get_board() is None

    @respx.mock
    def test_404_returns_none(self, client):
        respx.get(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            return_value=httpx.Response(200, json="blueos")
        )
        respx.get(f"{BASE_URL}/kraken/v2.0/extension/").mock(
            return_value=httpx.Response(404)
        )
        client.get_hostname()
        assert client.get_extensions() is None


class TestEndpointPaths:
    """Verify each method hits the correct URL path."""

    @respx.mock
    def _call_and_check(self, client, method_name, expected_path):
        route = respx.get(f"{BASE_URL}{expected_path}").mock(
            return_value=httpx.Response(200, json={"ok": True})
        )
        getattr(client, method_name)()
        assert route.called

    def test_get_hostname(self, client):
        self._call_and_check(client, "get_hostname", "/beacon/v1.0/hostname")

    def test_get_vehicle_name(self, client):
        self._call_and_check(client, "get_vehicle_name", "/beacon/v1.0/vehicle_name")

    def test_get_version(self, client):
        self._call_and_check(client, "get_version", "/version-chooser/v1.0/version/current")

    def test_get_board(self, client):
        self._call_and_check(client, "get_board", "/ardupilot-manager/v1.0/board")

    def test_get_firmware_info(self, client):
        self._call_and_check(client, "get_firmware_info", "/ardupilot-manager/v1.0/firmware_info")

    def test_get_serials(self, client):
        self._call_and_check(client, "get_serials", "/ardupilot-manager/v1.0/serials")

    def test_get_extensions(self, client):
        self._call_and_check(client, "get_extensions", "/kraken/v2.0/extension/")

    def test_get_bag(self, client):
        self._call_and_check(client, "get_bag", "/bag/v1.0/get/*")

    def test_get_ethernet(self, client):
        self._call_and_check(client, "get_ethernet", "/cable-guy/v1.0/ethernet")

    def test_get_wifi_saved(self, client):
        self._call_and_check(client, "get_wifi_saved", "/wifi-manager/v1.0/saved")

    def test_get_hotspot(self, client):
        self._call_and_check(client, "get_hotspot", "/wifi-manager/v1.0/hotspot")

    def test_get_web_services(self, client):
        self._call_and_check(client, "get_web_services", "/helper/v1.0/web_services")


class TestContextManager:
    def test_context_manager(self):
        with BlueOSClient(BASE_URL) as client:
            assert client is not None
