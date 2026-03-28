"""Tests for extract module — URL parsing, config assembly, YAML I/O."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from mower_provisioner.exceptions import ParamFileError
from mower_provisioner.extract import (
    extract_config,
    extract_hostname_from_url,
    load_yaml,
    output_filename,
    save_yaml,
)


class TestExtractHostnameFromUrl:
    def test_http_with_domain(self):
        assert extract_hostname_from_url("http://blueos.local") == "blueos.local"

    def test_http_with_ip(self):
        assert extract_hostname_from_url("http://192.168.2.2") == "192.168.2.2"

    def test_http_with_port(self):
        assert extract_hostname_from_url("http://192.168.2.2:80") == "192.168.2.2"

    def test_https(self):
        assert extract_hostname_from_url("https://blueos.local") == "blueos.local"

    def test_with_path(self):
        assert extract_hostname_from_url("http://blueos.local/foo") == "blueos.local"


class TestOutputFilename:
    def test_domain(self):
        assert output_filename("http://blueos.local") == Path("blueos.local.yaml")

    def test_ip(self):
        assert output_filename("http://192.168.2.2") == Path("192.168.2.2.yaml")


class TestExtractConfig:
    def _make_client(self, **overrides):
        """Create a mock BlueOSClient with configurable return values."""
        client = MagicMock()
        defaults = {
            "get_hostname": "blueos",
            "get_vehicle_name": "Mower-01",
            "get_version": {"tag": "1.5.0"},
            "get_board": {"name": "Pixhawk6X"},
            "get_firmware_info": {"version": "4.5.1", "type": "ArduRover"},
            "get_serials": [{"port": "/dev/ttyACM0"}],
            "get_extensions": [
                {"identifier": "ext.example", "tag": "1.0.0", "enabled": True}
            ],
            "get_bag": {"key1": "value1"},
            "get_ethernet": [{"name": "eth0"}],
            "get_wifi_saved": [],
            "get_hotspot": {"enabled": False},
            "get_web_services": [{"name": "kraken"}],
        }
        defaults.update(overrides)
        for method, value in defaults.items():
            getattr(client, method).return_value = value
        return client

    def test_all_sections_populated(self):
        client = self._make_client()
        config = extract_config(client)

        assert config["hostname"] == "blueos"
        assert config["vehicle_name"] == "Mower-01"
        assert config["blueos_version"] == {"tag": "1.5.0"}
        assert config["board"] == {"name": "Pixhawk6X"}
        assert config["firmware"] == {"version": "4.5.1", "type": "ArduRover"}
        assert config["serials"] == [{"port": "/dev/ttyACM0"}]
        assert len(config["extensions"]) == 1
        assert config["extensions"][0]["identifier"] == "ext.example"
        assert config["bag"] == {"key1": "value1"}
        assert config["network"]["ethernet"] == [{"name": "eth0"}]
        assert config["services"] == [{"name": "kraken"}]
        assert "_extracted_at" in config

    def test_partial_failure(self):
        client = self._make_client(
            get_board=None,
            get_firmware_info=None,
            get_wifi_saved=None,
        )
        config = extract_config(client)

        assert config["hostname"] == "blueos"
        assert config["board"] is None
        assert config["firmware"] is None
        assert config["extensions"] is not None
        assert config["network"]["wifi_saved"] is None

    def test_all_fail(self):
        client = self._make_client(
            **{m: None for m in [
                "get_hostname", "get_vehicle_name", "get_version",
                "get_board", "get_firmware_info", "get_serials",
                "get_extensions", "get_bag", "get_ethernet",
                "get_wifi_saved", "get_hotspot", "get_web_services",
            ]}
        )
        config = extract_config(client)
        assert config["hostname"] is None
        assert config["extensions"] is None
        assert "_extracted_at" in config


class TestSaveYaml:
    def test_writes_valid_yaml(self, tmp_path):
        path = tmp_path / "out.yaml"
        config = {"hostname": "blueos", "extensions": [{"id": "test"}]}
        save_yaml(config, path)

        loaded = yaml.safe_load(path.read_text())
        assert loaded["hostname"] == "blueos"
        assert loaded["extensions"][0]["id"] == "test"

    def test_preserves_key_order(self, tmp_path):
        path = tmp_path / "order.yaml"
        config = {"zzz": 1, "aaa": 2, "mmm": 3}
        save_yaml(config, path)

        keys = list(yaml.safe_load(path.read_text()).keys())
        assert keys == ["zzz", "aaa", "mmm"]

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "out.yaml"
        save_yaml({"a": 1}, path)
        assert path.exists()

    def test_round_trip_with_none_values(self, tmp_path):
        path = tmp_path / "nulls.yaml"
        config = {"hostname": "blueos", "board": None, "extensions": None}
        save_yaml(config, path)

        loaded = yaml.safe_load(path.read_text())
        assert loaded["board"] is None
        assert loaded["extensions"] is None


class TestLoadYaml:
    def test_valid_yaml(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("hostname: blueos\nautopilot_params:\n  CRUISE_SPEED: 2.0\n")
        data = load_yaml(path)
        assert data["hostname"] == "blueos"
        assert data["autopilot_params"]["CRUISE_SPEED"] == 2.0

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nope.yaml"
        with pytest.raises(ParamFileError, match="Cannot read"):
            load_yaml(path)

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(":\n  - :\n  invalid: [unterminated")
        with pytest.raises(ParamFileError, match="Invalid YAML"):
            load_yaml(path)

    def test_non_dict_yaml(self, tmp_path):
        path = tmp_path / "list.yaml"
        path.write_text("- item1\n- item2\n")
        with pytest.raises(ParamFileError, match="Expected a YAML mapping"):
            load_yaml(path)

    def test_round_trip_with_save_yaml(self, tmp_path):
        path = tmp_path / "rt.yaml"
        config = {"hostname": "blueos", "autopilot_params": {"WP_RADIUS": 3.0}}
        save_yaml(config, path)
        loaded = load_yaml(path)
        assert loaded == config
