"""BlueOS REST API client for configuration extraction."""

from __future__ import annotations

import ast
from typing import Any

import httpx

from .exceptions import BlueOSConnectionError

DEFAULT_TIMEOUT = httpx.Timeout(10.0, read=30.0)


def _unrepr(value: Any) -> str:
    """Decode a Python repr() of str/bytes back to text."""
    if not isinstance(value, str):
        return ""
    try:
        decoded = ast.literal_eval(value)
    except (ValueError, SyntaxError):
        return value
    if isinstance(decoded, bytes):
        return decoded.decode("utf-8", errors="replace")
    return str(decoded)


class BlueOSClient:
    """Thin HTTP client wrapping BlueOS REST endpoints.

    Each method returns parsed JSON on success or None on failure.
    Connection errors on the first call raise BlueOSConnectionError;
    subsequent per-endpoint failures return None so extraction can
    continue with partial data.
    """

    def __init__(self, base_url: str, timeout: httpx.Timeout = DEFAULT_TIMEOUT) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=timeout)
        self._connected = False

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> BlueOSClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _get_text(self, path: str) -> str | None:
        """GET an endpoint and return response text, or None on failure."""
        try:
            resp = self._client.get(path)
            resp.raise_for_status()
            self._connected = True
            return resp.text
        except httpx.ConnectError as e:
            if not self._connected:
                raise BlueOSConnectionError(
                    f"Cannot reach {self._base_url}: {e}"
                ) from e
            return None
        except (httpx.HTTPStatusError, httpx.HTTPError):
            return None

    def _put_text(self, path: str, content: str) -> bool:
        """PUT text content to an endpoint. Returns True on success."""
        try:
            resp = self._client.put(
                path,
                content=content.encode("utf-8"),
                headers={"Content-Type": "text/plain"},
            )
            resp.raise_for_status()
            self._connected = True
            return True
        except httpx.ConnectError as e:
            if not self._connected:
                raise BlueOSConnectionError(
                    f"Cannot reach {self._base_url}: {e}"
                ) from e
            return False
        except (httpx.HTTPStatusError, httpx.HTTPError):
            return False

    def _get_json(self, path: str) -> Any | None:
        """GET an endpoint and return parsed JSON, or None on failure."""
        try:
            resp = self._client.get(path)
            resp.raise_for_status()
            self._connected = True
            return resp.json()
        except httpx.ConnectError as e:
            if not self._connected:
                raise BlueOSConnectionError(
                    f"Cannot reach {self._base_url}: {e}"
                ) from e
            return None
        except (httpx.HTTPStatusError, httpx.HTTPError, ValueError):
            return None

    def _post(self, path: str, **kwargs: Any) -> bool:
        """POST to an endpoint. Returns True on success, False on failure."""
        try:
            resp = self._client.post(path, **kwargs)
            resp.raise_for_status()
            self._connected = True
            return True
        except httpx.ConnectError as e:
            if not self._connected:
                raise BlueOSConnectionError(
                    f"Cannot reach {self._base_url}: {e}"
                ) from e
            return False
        except (httpx.HTTPStatusError, httpx.HTTPError):
            return False

    # -- Identity --

    def get_hostname(self) -> str | None:
        return self._get_json("/beacon/v1.0/hostname")

    def get_vehicle_name(self) -> str | None:
        return self._get_json("/beacon/v1.0/vehicle_name")

    # -- Extensions (Kraken v2) --

    def get_extensions(self) -> list[Any] | None:
        return self._get_json("/kraken/v2.0/extension/")

    # -- Config store (Bag of Holding) --

    def get_bag(self) -> dict[str, Any] | None:
        return self._get_json("/bag/v1.0/get/*")

    # -- Networking --

    def get_ethernet(self) -> list[Any] | None:
        return self._get_json("/cable-guy/v1.0/ethernet")

    def get_wifi_saved(self) -> list[Any] | None:
        return self._get_json("/wifi-manager/v1.0/saved")

    def get_hotspot(self) -> Any | None:
        return self._get_json("/wifi-manager/v1.0/hotspot")

    def connect_wifi(self, ssid: str, password: str, timeout: float = 60.0) -> bool:
        """Save and connect to a WiFi network.

        BlueOS switches wlan0 to this network immediately, which can drop
        the HTTP connection if the device is reached over another WiFi.
        """
        return self._post(
            "/wifi-manager/v1.0/connect",
            params={"hidden": False},
            json={"ssid": ssid, "password": password},
            timeout=httpx.Timeout(timeout),
        )

    # -- Network (Cable Guy) --

    def add_ip(self, interface_name: str, ip_address: str) -> bool:
        """Add a static (unmanaged) IP address to an interface."""
        return self._post(
            "/cable-guy/v1.0/address",
            params={"interface_name": interface_name, "ip_address": ip_address},
        )

    def add_dhcp_server(self, interface_name: str, ipv4_gateway: str) -> bool:
        """Run a BlueOS DHCP server (dnsmasq) on an interface.

        BlueOS persists this in its settings and assigns the gateway IP
        to the interface; leases are .101-.200 of the gateway's /24.
        """
        return self._post(
            "/cable-guy/v1.0/dhcp",
            params={
                "interface_name": interface_name,
                "ipv4_gateway": ipv4_gateway,
                "is_backup_server": False,
            },
        )

    # -- Extensions (Kraken v2) --

    def install_extension(self, extension: dict[str, Any], timeout: float = 600.0) -> bool:
        """Install an extension. Blocks while Kraken streams the image pull."""
        body = {
            k: extension.get(k)
            for k in ("identifier", "tag", "name", "docker", "enabled",
                      "permissions", "user_permissions", "auth")
        }
        body["user_permissions"] = body["user_permissions"] or ""
        return self._post(
            "/kraken/v2.0/extension/",
            json=body,
            timeout=httpx.Timeout(timeout),
        )

    # -- Host access (Commander) --

    def run_host_command(self, command: str) -> dict[str, Any] | None:
        """Run a shell command on the host (as pi, with sudo available).

        Returns {"stdout", "stderr", "return_code"} with the output decoded,
        or None if the request failed.
        """
        try:
            resp = self._client.post(
                "/commander/v1.0/command/host",
                params={"command": command, "i_know_what_i_am_doing": True},
            )
            resp.raise_for_status()
            self._connected = True
            data = resp.json()
        except httpx.ConnectError as e:
            if not self._connected:
                raise BlueOSConnectionError(
                    f"Cannot reach {self._base_url}: {e}"
                ) from e
            return None
        except (httpx.HTTPStatusError, httpx.HTTPError, ValueError):
            return None
        if not isinstance(data, dict):
            return None
        # Commander returns stdout/stderr as Python repr() strings.
        return {
            "stdout": _unrepr(data.get("stdout")),
            "stderr": _unrepr(data.get("stderr")),
            "return_code": data.get("return_code"),
        }

    def reboot(self) -> bool:
        """Reboot the host (Commander delays ~5 s before rebooting)."""
        return self._post(
            "/commander/v1.0/shutdown",
            params={"shutdown_type": "reboot", "i_know_what_i_am_doing": True},
        )

    # -- Setters --

    def set_hostname(self, name: str) -> bool:
        return self._post("/beacon/v1.0/hostname", params={"hostname": name})

    def set_vehicle_name(self, name: str) -> bool:
        return self._post("/beacon/v1.0/vehicle_name", params={"name": name})

    def set_bag(self, key: str, value: Any) -> bool:
        return self._post(f"/bag/v1.0/set/{key}", json=value)

    # -- File browser (filebrowser.org API, requires auth) --

    _fb_token: str | None = None

    def _fb_auth(self) -> str | None:
        """Login to the file browser and cache the JWT token."""
        if self._fb_token is not None:
            return self._fb_token
        try:
            resp = self._client.post(
                "/file-browser/api/login",
                json={"username": "admin", "password": "admin"},
            )
            resp.raise_for_status()
            self._connected = True
            self._fb_token = resp.text.strip().strip('"')
            return self._fb_token
        except (httpx.ConnectError, httpx.HTTPStatusError, httpx.HTTPError):
            return None

    def get_file(self, device_path: str) -> str | None:
        """Fetch a file from the device via the file browser API.

        device_path is relative to the file browser root scope
        (e.g. "extensions/mediamtx/mediamtx.yml").
        """
        token = self._fb_auth()
        if token is None:
            return None
        path = device_path.lstrip("/")
        try:
            resp = self._client.get(
                f"/file-browser/api/raw/{path}",
                headers={"X-Auth": token},
            )
            resp.raise_for_status()
            return resp.text
        except (httpx.HTTPStatusError, httpx.HTTPError):
            return None

    def put_file(self, device_path: str, content: str) -> bool:
        """Write a file to the device via the file browser API.

        device_path is relative to the file browser root scope.
        """
        token = self._fb_auth()
        if token is None:
            return False
        path = device_path.lstrip("/")
        try:
            resp = self._client.put(
                f"/file-browser/api/resources/{path}",
                content=content.encode("utf-8"),
                headers={"X-Auth": token, "Content-Type": "text/plain"},
            )
            resp.raise_for_status()
            return True
        except (httpx.HTTPStatusError, httpx.HTTPError):
            return False
