"""Tests for blueos_api module — HTTP client with mocked responses."""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from skynet.blueos_api import BlueOSClient
from skynet.exceptions import BlueOSConnectionError

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
        respx.get(f"{BASE_URL}/kraken/v2.0/extension/").mock(
            return_value=httpx.Response(500)
        )
        client.get_hostname()  # establish connection
        assert client.get_extensions() is None

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
        respx.get(f"{BASE_URL}/kraken/v2.0/extension/").mock(
            side_effect=httpx.ConnectError("refused")
        )
        client.get_hostname()  # establish connection
        assert client.get_extensions() is None

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


class TestSetters:
    """Verify setter methods POST to correct endpoints."""

    @respx.mock
    def test_set_hostname(self, client):
        route = respx.post(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            return_value=httpx.Response(200)
        )
        assert client.set_hostname("mower-01") is True
        assert route.called

    @respx.mock
    def test_set_vehicle_name(self, client):
        route = respx.post(f"{BASE_URL}/beacon/v1.0/vehicle_name").mock(
            return_value=httpx.Response(200)
        )
        assert client.set_vehicle_name("Mower-01") is True
        assert route.called

    @respx.mock
    def test_set_bag(self, client):
        route = respx.post(f"{BASE_URL}/bag/v1.0/set/my_key").mock(
            return_value=httpx.Response(200)
        )
        assert client.set_bag("my_key", {"data": 1}) is True
        assert route.called

    @respx.mock
    def test_set_hostname_failure(self, client):
        # Establish connection first
        respx.get(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            return_value=httpx.Response(200, json="blueos")
        )
        client.get_hostname()
        respx.post(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            return_value=httpx.Response(500)
        )
        assert client.set_hostname("mower-01") is False

    @respx.mock
    def test_set_connection_error_raises_on_first_call(self, client):
        respx.post(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            side_effect=httpx.ConnectError("refused")
        )
        with pytest.raises(BlueOSConnectionError, match="Cannot reach"):
            client.set_hostname("mower-01")

    @respx.mock
    def test_set_connection_error_returns_false_after_connected(self, client):
        respx.get(f"{BASE_URL}/beacon/v1.0/hostname").mock(
            return_value=httpx.Response(200, json="blueos")
        )
        client.get_hostname()
        respx.post(f"{BASE_URL}/beacon/v1.0/vehicle_name").mock(
            side_effect=httpx.ConnectError("refused")
        )
        assert client.set_vehicle_name("test") is False


class TestFileBrowser:
    """Verify file browser API methods with auth."""

    def _mock_login(self):
        respx.post(f"{BASE_URL}/file-browser/api/login").mock(
            return_value=httpx.Response(200, text='"test-jwt-token"')
        )

    @respx.mock
    def test_get_file_success(self, client):
        self._mock_login()
        route = respx.get(f"{BASE_URL}/file-browser/api/raw/extensions/mediamtx/mediamtx.yml").mock(
            return_value=httpx.Response(200, text="logLevel: info\n")
        )
        result = client.get_file("extensions/mediamtx/mediamtx.yml")
        assert result == "logLevel: info\n"
        assert route.called
        # Verify auth header was sent
        assert route.calls[0].request.headers["x-auth"] == "test-jwt-token"

    @respx.mock
    def test_get_file_not_found(self, client):
        self._mock_login()
        respx.get(f"{BASE_URL}/file-browser/api/raw/nope.yml").mock(
            return_value=httpx.Response(404)
        )
        assert client.get_file("nope.yml") is None

    @respx.mock
    def test_get_file_login_failure(self, client):
        respx.post(f"{BASE_URL}/file-browser/api/login").mock(
            return_value=httpx.Response(403)
        )
        assert client.get_file("extensions/mediamtx/mediamtx.yml") is None

    @respx.mock
    def test_put_file_success(self, client):
        self._mock_login()
        route = respx.put(f"{BASE_URL}/file-browser/api/resources/extensions/test.yml").mock(
            return_value=httpx.Response(200)
        )
        assert client.put_file("extensions/test.yml", "content") is True
        assert route.called
        assert route.calls[0].request.headers["x-auth"] == "test-jwt-token"

    @respx.mock
    def test_put_file_failure(self, client):
        self._mock_login()
        respx.put(f"{BASE_URL}/file-browser/api/resources/extensions/test.yml").mock(
            return_value=httpx.Response(500)
        )
        assert client.put_file("extensions/test.yml", "content") is False

    @respx.mock
    def test_token_cached(self, client):
        login_route = respx.post(f"{BASE_URL}/file-browser/api/login").mock(
            return_value=httpx.Response(200, text='"cached-token"')
        )
        respx.get(f"{BASE_URL}/file-browser/api/raw/a.yml").mock(
            return_value=httpx.Response(200, text="a")
        )
        respx.get(f"{BASE_URL}/file-browser/api/raw/b.yml").mock(
            return_value=httpx.Response(200, text="b")
        )
        client.get_file("a.yml")
        client.get_file("b.yml")
        # Login should only have been called once
        assert login_route.call_count == 1


class TestContextManager:
    def test_context_manager(self):
        with BlueOSClient(BASE_URL) as client:
            assert client is not None


class TestProvisioningEndpoints:
    @respx.mock
    def test_add_dhcp_server(self, client):
        route = respx.post(f"{BASE_URL}/cable-guy/v1.0/dhcp").mock(
            return_value=httpx.Response(200, json=None)
        )
        assert client.add_dhcp_server("eth1", "192.168.10.1") is True
        params = route.calls.last.request.url.params
        assert params["interface_name"] == "eth1"
        assert params["ipv4_gateway"] == "192.168.10.1"
        assert params["is_backup_server"] == "false"

    @respx.mock
    def test_install_extension_body(self, client):
        route = respx.post(f"{BASE_URL}/kraken/v2.0/extension/").mock(
            return_value=httpx.Response(200, text="pulling...")
        )
        ext = {
            "identifier": "williangalvani.mediamtx", "tag": "v1.11.4", "name": "MediaMTX",
            "docker": "williangalvani/blueos-extension-mediamtx", "enabled": True,
            "permissions": "{}", "user_permissions": None, "auth": None, "extra": "x",
        }
        assert client.install_extension(ext) is True
        body = json.loads(route.calls.last.request.content)
        assert body["identifier"] == "williangalvani.mediamtx"
        assert body["user_permissions"] == ""
        assert "extra" not in body

    @respx.mock
    def test_run_host_command_decodes_repr(self, client):
        route = respx.post(f"{BASE_URL}/commander/v1.0/command/host").mock(
            return_value=httpx.Response(200, json={
                "stdout": repr("line1\nit's\n"), "stderr": "''", "return_code": 0,
            })
        )
        result = client.run_host_command("cat /etc/blueos/dnsmasq.conf")
        assert result == {"stdout": "line1\nit's\n", "stderr": "", "return_code": 0}
        params = route.calls.last.request.url.params
        assert params["command"] == "cat /etc/blueos/dnsmasq.conf"
        assert params["i_know_what_i_am_doing"] == "true"

    @respx.mock
    def test_run_host_command_decodes_bytes_repr(self, client):
        respx.post(f"{BASE_URL}/commander/v1.0/command/host").mock(
            return_value=httpx.Response(200, json={
                "stdout": repr(b"ok\n"), "stderr": repr(b""), "return_code": 0,
            })
        )
        assert client.run_host_command("true")["stdout"] == "ok\n"

    @respx.mock
    def test_run_host_command_http_error(self, client):
        respx.post(f"{BASE_URL}/commander/v1.0/command/host").mock(
            return_value=httpx.Response(500)
        )
        assert client.run_host_command("true") is None

    @respx.mock
    def test_reboot(self, client):
        route = respx.post(f"{BASE_URL}/commander/v1.0/shutdown").mock(
            return_value=httpx.Response(200, json=None)
        )
        assert client.reboot() is True
        assert route.calls.last.request.url.params["shutdown_type"] == "reboot"


class TestConnectWifi:
    @respx.mock
    def test_connect_wifi_body(self, client):
        route = respx.post(f"{BASE_URL}/wifi-manager/v1.0/connect").mock(
            return_value=httpx.Response(200, json=None)
        )
        assert client.connect_wifi("007", "pw") is True
        req = route.calls.last.request
        assert json.loads(req.content) == {"ssid": "007", "password": "pw"}
        assert req.url.params["hidden"] == "false"
