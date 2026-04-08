"""Tests for download and upload CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import yaml
from typer.testing import CliRunner

from mower_provisioner.cli import app
from mower_provisioner.config import CALIBRATION_PARAMS

runner = CliRunner()


def _make_param_msg(name: str, value: float, index: int, count: int):
    msg = MagicMock()
    msg.param_id = name.encode("utf-8")
    msg.param_value = value
    msg.param_index = index
    msg.param_count = count
    return msg


def _mock_blueos_client():
    """Create a mock BlueOSClient with all getters returning sample data."""
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get_hostname.return_value = "blueos"
    client.get_vehicle_name.return_value = "Mower-01"
    client.get_extensions.return_value = [{"identifier": "ext.test"}]
    client.get_bag.return_value = {"key1": "value1"}
    client.get_ethernet.return_value = []
    client.get_wifi_saved.return_value = []
    client.get_hotspot.return_value = None
    # file browser — default: MediaMTX config found at first candidate
    client.get_file.return_value = "logLevel: info\nrtspAddress: ':8555'\n"
    client.put_file.return_value = True
    # setters
    client.set_hostname.return_value = True
    client.set_vehicle_name.return_value = True
    client.set_bag.return_value = True
    return client


def _mock_mavlink_conn(param_msgs):
    """Create a mock MAVLink connection that yields param messages."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.mav = MagicMock()
    conn.recv_match.side_effect = param_msgs
    return conn


class TestDownload:
    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_basic_download(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 2),
            _make_param_msg("WP_RADIUS", 3.0, 1, 2),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        assert data["hostname"] == "blueos"
        assert data["autopilot_params"]["CRUISE_SPEED"] == 2.0
        assert data["autopilot_params"]["WP_RADIUS"] == 3.0
        mock_mavlink.assert_called_once_with("tcp:192.168.2.2:5760")

    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_filters_calibration_by_default(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        cal_param = next(iter(CALIBRATION_PARAMS))
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 2),
            _make_param_msg(cal_param, 0.5, 1, 2),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        assert "CRUISE_SPEED" in data["autopilot_params"]
        assert cal_param not in data["autopilot_params"]

    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_includes_calibration_when_flagged(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        cal_param = next(iter(CALIBRATION_PARAMS))
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 2),
            _make_param_msg(cal_param, 0.5, 1, 2),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(
            app, ["download", "192.168.2.2", "-o", str(out), "--include-calibration"]
        )
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        assert cal_param in data["autopilot_params"]

    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_default_output_filename(self, mock_cls, mock_mavlink, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 1),
        ])

        result = runner.invoke(app, ["download", "blueos.local"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "blueos.local.yaml").exists()

    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_params_are_sorted(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("ZZZ_PARAM", 9.0, 0, 3),
            _make_param_msg("AAA_PARAM", 1.0, 1, 3),
            _make_param_msg("MMM_PARAM", 5.0, 2, 3),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        keys = list(data["autopilot_params"].keys())
        assert keys == sorted(keys)

    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_download_includes_mediamtx(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 1),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        assert data["mediamtx"] is not None
        assert "config_path" in data["mediamtx"]
        assert data["mediamtx"]["config"]["logLevel"] == "info"

    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_download_mediamtx_not_found(self, mock_cls, mock_mavlink, tmp_path):
        mock_client = _mock_blueos_client()
        mock_client.get_file.return_value = None  # MediaMTX not found
        mock_cls.return_value = mock_client
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 1),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        assert data["mediamtx"] is None
        assert "not found" in result.output


class TestUpload:
    def _write_config(self, path: Path, params: dict | None = None, **kwargs):
        config = {}
        if "hostname" in kwargs or params is not None:
            config["hostname"] = kwargs.get("hostname", "mower-01")
        if "vehicle_name" in kwargs or params is not None:
            config["vehicle_name"] = kwargs.get("vehicle_name", "Mower-01")
        if "bag" in kwargs:
            config["bag"] = kwargs["bag"]
        elif params is not None:
            config["bag"] = {"key1": "value1"}
        if params is not None:
            config["autopilot_params"] = params
        path.write_text(yaml.dump(config))

    @patch("mower_provisioner.cli.write_params", return_value=["CRUISE_SPEED", "WP_RADIUS"])
    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_basic_upload(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        mock_client = _mock_blueos_client()
        mock_cls.return_value = mock_client

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_mavlink.return_value = mock_conn

        cfg = tmp_path / "config.yaml"
        self._write_config(cfg, params={"CRUISE_SPEED": 2.0, "WP_RADIUS": 3.0})

        result = runner.invoke(app, ["upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output

        mock_client.set_hostname.assert_called_once_with("mower-01")
        mock_client.set_vehicle_name.assert_called_once_with("Mower-01")
        mock_client.set_bag.assert_called_once_with("key1", "value1")
        mock_mavlink.assert_called_once_with("tcp:192.168.2.2:5760")
        mock_write.assert_called_once()

    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_dry_run(self, mock_cls, tmp_path):
        mock_cls.return_value = _mock_blueos_client()

        cfg = tmp_path / "config.yaml"
        self._write_config(cfg, params={"CRUISE_SPEED": 2.0})

        result = runner.invoke(app, ["upload", "192.168.2.2", str(cfg), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output

    def test_empty_config(self, tmp_path):
        cfg = tmp_path / "empty.yaml"
        cfg.write_text(yaml.dump({"network": {"hotspot": True}}))

        result = runner.invoke(app, ["upload", "192.168.2.2", str(cfg)])
        assert result.exit_code == 0
        assert "Nothing to upload" in result.output

    @patch("mower_provisioner.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_filters_calibration(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        mock_cls.return_value = _mock_blueos_client()

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_mavlink.return_value = mock_conn

        cal_param = next(iter(CALIBRATION_PARAMS))
        cfg = tmp_path / "config.yaml"
        self._write_config(cfg, params={"CRUISE_SPEED": 2.0, cal_param: 0.5})

        result = runner.invoke(app, ["upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output

        call_params = mock_write.call_args[0][1]
        assert "CRUISE_SPEED" in call_params
        assert cal_param not in call_params

    @patch("mower_provisioner.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_warns_on_setter_failure(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        mock_client = _mock_blueos_client()
        mock_client.set_hostname.return_value = False  # simulate failure
        mock_cls.return_value = mock_client

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_mavlink.return_value = mock_conn

        cfg = tmp_path / "config.yaml"
        self._write_config(cfg, params={"CRUISE_SPEED": 2.0})

        result = runner.invoke(app, ["upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert "Failed to set hostname" in result.output

    @patch("mower_provisioner.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_upload_multiple_bag_entries(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        mock_client = _mock_blueos_client()
        mock_cls.return_value = mock_client

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_mavlink.return_value = mock_conn

        cfg = tmp_path / "config.yaml"
        self._write_config(
            cfg,
            params={"CRUISE_SPEED": 2.0},
            bag={"ext.cam": {"res": "1080p"}, "ext.gps": {"rate": 10}},
        )

        result = runner.invoke(app, ["upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert mock_client.set_bag.call_count == 2

    @patch("mower_provisioner.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_upload_mediamtx_config(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        mock_client = _mock_blueos_client()
        mock_cls.return_value = mock_client

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_mavlink.return_value = mock_conn

        cfg = tmp_path / "config.yaml"
        config = {
            "hostname": "mower-01",
            "vehicle_name": "Mower-01",
            "bag": {"key1": "value1"},
            "mediamtx": {
                "config_path": "/etc/mediamtx/mediamtx.yml",
                "config": {"logLevel": "info", "rtspAddress": ":8555"},
            },
            "autopilot_params": {"CRUISE_SPEED": 2.0},
        }
        cfg.write_text(yaml.dump(config))

        result = runner.invoke(app, ["upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert "mediamtx config" in result.output

        mock_client.put_file.assert_called_once()
        call_path = mock_client.put_file.call_args[0][0]
        assert call_path == "/etc/mediamtx/mediamtx.yml"

    @patch("mower_provisioner.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("mower_provisioner.cli.mavlink_connection")
    @patch("mower_provisioner.blueos_api.BlueOSClient")
    def test_upload_mediamtx_failure_warns(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        mock_client = _mock_blueos_client()
        mock_client.put_file.return_value = False
        mock_cls.return_value = mock_client

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_mavlink.return_value = mock_conn

        cfg = tmp_path / "config.yaml"
        config = {
            "hostname": "mower-01",
            "vehicle_name": "Mower-01",
            "bag": {"key1": "value1"},
            "mediamtx": {
                "config_path": "/etc/mediamtx/mediamtx.yml",
                "config": {"logLevel": "info"},
            },
            "autopilot_params": {"CRUISE_SPEED": 2.0},
        }
        cfg.write_text(yaml.dump(config))

        result = runner.invoke(app, ["upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert "Failed to push MediaMTX config" in result.output
