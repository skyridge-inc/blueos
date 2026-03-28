"""Configuration extraction and YAML serialization."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .blueos_api import BlueOSClient
from .exceptions import ParamFileError


def extract_hostname_from_url(url: str) -> str:
    """Extract domain/host from URL for use as filename."""
    parsed = urlparse(url)
    return parsed.hostname or parsed.path


def output_filename(url: str) -> Path:
    """Derive YAML output filename from the target URL."""
    host = extract_hostname_from_url(url)
    return Path(f"{host}.yaml")


def extract_config(client: BlueOSClient) -> dict[str, Any]:
    """Fetch all configuration sections from a BlueOS device.

    Each section that fails to fetch is stored as None.
    Returns a structured dict ready for YAML serialization.
    """
    config: dict[str, Any] = {}

    # Identity
    config["hostname"] = client.get_hostname()
    config["vehicle_name"] = client.get_vehicle_name()

    # BlueOS version
    config["blueos_version"] = client.get_version()

    # Autopilot
    config["board"] = client.get_board()
    config["firmware"] = client.get_firmware_info()
    config["serials"] = client.get_serials()

    # Extensions
    config["extensions"] = client.get_extensions()

    # Config store (extensions persist their settings here)
    config["bag"] = client.get_bag()

    # Networking
    config["network"] = {
        "ethernet": client.get_ethernet(),
        "wifi_saved": client.get_wifi_saved(),
        "hotspot": client.get_hotspot(),
    }

    # Services
    config["services"] = client.get_web_services()

    # Metadata
    config["_extracted_at"] = datetime.now(timezone.utc).isoformat()

    return config


def load_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML config file.

    Raises:
        ParamFileError: If the file cannot be read or parsed.
    """
    try:
        text = path.read_text()
    except OSError as e:
        raise ParamFileError(f"Cannot read {path}: {e}") from e
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ParamFileError(f"Invalid YAML in {path}: {e}") from e
    if not isinstance(data, dict):
        raise ParamFileError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")
    return data


def save_yaml(config: dict[str, Any], path: Path) -> None:
    """Write config dict to YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(
            config,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
