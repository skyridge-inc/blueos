"""BlueOS REST API client for configuration extraction."""

from __future__ import annotations

from typing import Any

import httpx

from .exceptions import BlueOSConnectionError

DEFAULT_TIMEOUT = httpx.Timeout(10.0, read=30.0)


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

    # -- Identity --

    def get_hostname(self) -> str | None:
        return self._get_json("/beacon/v1.0/hostname")

    def get_vehicle_name(self) -> str | None:
        return self._get_json("/beacon/v1.0/vehicle_name")

    # -- BlueOS version --

    def get_version(self) -> dict[str, Any] | None:
        return self._get_json("/version-chooser/v1.0/version/current")

    # -- Autopilot --

    def get_board(self) -> dict[str, Any] | None:
        return self._get_json("/ardupilot-manager/v1.0/board")

    def get_firmware_info(self) -> dict[str, Any] | None:
        return self._get_json("/ardupilot-manager/v1.0/firmware_info")

    def get_serials(self) -> list[Any] | None:
        return self._get_json("/ardupilot-manager/v1.0/serials")

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

    # -- System --

    def get_web_services(self) -> list[Any] | None:
        return self._get_json("/helper/v1.0/web_services")
