"""Tests for download and upload CLI commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest
import yaml
from typer.testing import CliRunner

from skynet.cli import app
from skynet.config import CALIBRATION_PARAMS
from skynet.exceptions import MowerProvisionerError

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
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_basic_download(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 2),
            _make_param_msg("WP_RADIUS", 3.0, 1, 2),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        assert data["hostname"] == "blueos"
        assert data["autopilot_params"]["CRUISE_SPEED"] == 2.0
        assert data["autopilot_params"]["WP_RADIUS"] == 3.0
        mock_mavlink.assert_called_once_with("tcp:192.168.2.2:5760")

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_filters_calibration_by_default(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        cal_param = next(iter(CALIBRATION_PARAMS))
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 2),
            _make_param_msg(cal_param, 0.5, 1, 2),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        assert "CRUISE_SPEED" in data["autopilot_params"]
        assert cal_param not in data["autopilot_params"]

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_includes_calibration_when_flagged(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        cal_param = next(iter(CALIBRATION_PARAMS))
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 2),
            _make_param_msg(cal_param, 0.5, 1, 2),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(
            app, ["config", "download", "192.168.2.2", "-o", str(out), "--include-calibration"]
        )
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        assert cal_param in data["autopilot_params"]

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_default_output_filename(self, mock_cls, mock_mavlink, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 1),
        ])

        result = runner.invoke(app, ["config", "download", "blueos.local"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "blueos.local.yaml").exists()

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_params_are_sorted(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("ZZZ_PARAM", 9.0, 0, 3),
            _make_param_msg("AAA_PARAM", 1.0, 1, 3),
            _make_param_msg("MMM_PARAM", 5.0, 2, 3),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        keys = list(data["autopilot_params"].keys())
        assert keys == sorted(keys)

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_download_includes_mediamtx(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 1),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output

        data = yaml.safe_load(out.read_text())
        assert data["mediamtx"] is not None
        assert "config_path" in data["mediamtx"]
        assert data["mediamtx"]["config"]["logLevel"] == "info"

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_download_mediamtx_not_found(self, mock_cls, mock_mavlink, tmp_path):
        mock_client = _mock_blueos_client()
        mock_client.get_file.return_value = None  # MediaMTX not found
        mock_cls.return_value = mock_client
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 1),
        ])

        out = tmp_path / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", str(out)])
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

    @patch("skynet.cli.write_params", return_value=["CRUISE_SPEED", "WP_RADIUS"])
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_basic_upload(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        mock_client = _mock_blueos_client()
        mock_cls.return_value = mock_client

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_mavlink.return_value = mock_conn

        cfg = tmp_path / "config.yaml"
        self._write_config(cfg, params={"CRUISE_SPEED": 2.0, "WP_RADIUS": 3.0})

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output

        mock_client.set_hostname.assert_called_once_with("mower-01")
        mock_client.set_vehicle_name.assert_called_once_with("Mower-01")
        mock_client.set_bag.assert_called_once_with("key1", "value1")
        mock_mavlink.assert_called_once_with("tcp:192.168.2.2:5760")
        mock_write.assert_called_once()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_dry_run(self, mock_cls, tmp_path):
        mock_cls.return_value = _mock_blueos_client()

        cfg = tmp_path / "config.yaml"
        self._write_config(cfg, params={"CRUISE_SPEED": 2.0})

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output

    def test_empty_config(self, tmp_path):
        cfg = tmp_path / "empty.yaml"
        cfg.write_text(yaml.dump({"network": {"hotspot": True}}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg)])
        assert result.exit_code == 0
        assert "Nothing to upload" in result.output

    @patch("skynet.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_filters_calibration(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        mock_cls.return_value = _mock_blueos_client()

        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_mavlink.return_value = mock_conn

        cal_param = next(iter(CALIBRATION_PARAMS))
        cfg = tmp_path / "config.yaml"
        self._write_config(cfg, params={"CRUISE_SPEED": 2.0, cal_param: 0.5})

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output

        call_params = mock_write.call_args[0][1]
        assert "CRUISE_SPEED" in call_params
        assert cal_param not in call_params

    @patch("skynet.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
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

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert "Failed to set hostname" in result.output

    @patch("skynet.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
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

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert mock_client.set_bag.call_count == 2

    @patch("skynet.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
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

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert "mediamtx config" in result.output

        mock_client.put_file.assert_called_once()
        call_path = mock_client.put_file.call_args[0][0]
        assert call_path == "/etc/mediamtx/mediamtx.yml"

    @patch("skynet.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
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

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert "Failed to push MediaMTX config" in result.output


class TestUploadProvisioning:
    """Extensions, DHCP servers, DHCP reservations and reboot."""

    CAMERA = {"mac": "64:35:1c:00:f0:79", "ip": "192.168.10.2", "hostname": "routecam"}

    def _client(self, dnsmasq_stdout: str | None = None, bind_stdout: str = "unchanged"):
        client = _mock_blueos_client()
        client.install_extension.return_value = True
        client.add_ip.return_value = True
        client.add_dhcp_server.return_value = True
        client.reboot.return_value = True

        def run_host_command(cmd: str):
            if cmd.startswith("cat "):
                if dnsmasq_stdout is None:
                    return {"stdout": "", "stderr": "No such file", "return_code": 1}
                return {"stdout": dnsmasq_stdout, "stderr": "", "return_code": 0}
            if cmd.startswith("sudo python3"):
                return {"stdout": bind_stdout + "\n", "stderr": "", "return_code": 0}
            return {"stdout": "", "stderr": "", "return_code": 0}

        client.run_host_command.side_effect = run_host_command
        return client

    def _upload(self, mock_cls, client, tmp_path, config, *extra):
        mock_cls.return_value = client
        cfg = tmp_path / "config.yaml"
        cfg.write_text(yaml.dump(config))
        return runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y", *extra])

    @patch("skynet.blueos_api.BlueOSClient")
    def test_installs_only_missing_extensions(self, mock_cls, tmp_path):
        client = self._client()
        client.get_extensions.return_value = [
            {"identifier": "bluerobotics.cockpit", "tag": "v1.16.0"},
            {"identifier": "williangalvani.mediamtx", "tag": "v1.10.0"},  # wrong tag
        ]
        config = {"extensions": [
            {"identifier": "bluerobotics.cockpit", "tag": "v1.16.0"},
            {"identifier": "williangalvani.mediamtx", "tag": "v1.11.4"},
        ]}
        result = self._upload(mock_cls, client, tmp_path, config)
        assert result.exit_code == 0, result.output
        client.install_extension.assert_called_once()
        assert client.install_extension.call_args[0][0]["tag"] == "v1.11.4"
        assert "extensions (2)" in result.output
        client.reboot.assert_not_called()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_starts_dhcp_server_only_when_not_serving(self, mock_cls, tmp_path):
        client = self._client()
        client.get_ethernet.return_value = [
            {"name": "usb0", "addresses": [{"ip": "192.168.3.1", "mode": "server"}]},
            {"name": "eth1", "addresses": []},
        ]
        config = {"network": {"ethernet": [
            {"name": "usb0", "addresses": [{"ip": "192.168.3.1", "mode": "server"}]},
            {"name": "eth1", "addresses": [{"ip": "192.168.10.1", "mode": "server"}]},
            {"name": "eth0", "addresses": [{"ip": "192.168.1.117", "mode": "client"}]},
        ]}}
        result = self._upload(mock_cls, client, tmp_path, config)
        assert result.exit_code == 0, result.output
        client.add_dhcp_server.assert_called_once_with("eth1", "192.168.10.1")
        client.add_ip.assert_not_called()
        assert "DHCP servers (2)" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_writes_reservations_and_reboots(self, mock_cls, tmp_path):
        client = self._client(dnsmasq_stdout=None, bind_stdout="changed")
        config = {"network": {"dhcp_reservations": [self.CAMERA]}}
        result = self._upload(mock_cls, client, tmp_path, config)
        assert result.exit_code == 0, result.output

        cmds = [c.args[0] for c in client.run_host_command.call_args_list]
        assert any("base64 -d | sudo tee /etc/blueos/dnsmasq.conf" in c for c in cmds)
        assert any(c.startswith("sudo python3 -c") for c in cmds)
        client.reboot.assert_called_once()
        assert "rebooting" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_no_reboot_when_reservations_unchanged(self, mock_cls, tmp_path):
        from skynet.host_config import render_dnsmasq_conf

        client = self._client(
            dnsmasq_stdout=render_dnsmasq_conf([self.CAMERA]), bind_stdout="unchanged",
        )
        config = {"network": {"dhcp_reservations": [self.CAMERA]}}
        result = self._upload(mock_cls, client, tmp_path, config)
        assert result.exit_code == 0, result.output
        cmds = [c.args[0] for c in client.run_host_command.call_args_list]
        assert not any("sudo tee" in c for c in cmds)
        client.reboot.assert_not_called()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_reservation_failure_warns_without_reboot(self, mock_cls, tmp_path):
        client = self._client()
        client.run_host_command.side_effect = None
        client.run_host_command.return_value = None
        config = {"network": {"dhcp_reservations": [self.CAMERA]}}
        result = self._upload(mock_cls, client, tmp_path, config)
        assert result.exit_code == 0, result.output
        assert "Failed to apply DHCP reservations" in result.output
        client.reboot.assert_not_called()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_dry_run_makes_no_calls(self, mock_cls, tmp_path):
        client = self._client()
        config = {
            "extensions": [{"identifier": "williangalvani.mediamtx", "tag": "v1.11.4"}],
            "network": {
                "ethernet": [{"name": "eth1", "addresses": [{"ip": "192.168.10.1", "mode": "server"}]}],
                "dhcp_reservations": [self.CAMERA],
            },
        }
        result = self._upload(mock_cls, client, tmp_path, config, "--dry-run")
        assert result.exit_code == 0, result.output
        assert "DHCP servers: eth1 (192.168.10.1)" in result.output
        assert "64:35:1c:00:f0:79 -> 192.168.10.2" in result.output
        client.install_extension.assert_not_called()
        client.add_dhcp_server.assert_not_called()
        client.run_host_command.assert_not_called()
        client.reboot.assert_not_called()


class TestDownloadReservations:
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_download_includes_dhcp_reservations(self, mock_cls, mock_mavlink, tmp_path):
        client = _mock_blueos_client()
        client.run_host_command.return_value = {
            "stdout": "# x\ndhcp-host=64:35:1c:00:f0:79,192.168.10.2,routecam\n",
            "stderr": "", "return_code": 0,
        }
        mock_cls.return_value = client
        mock_mavlink.side_effect = MowerProvisionerError("no mav")

        out = tmp_path / "out.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", str(out)])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(out.read_text())
        assert data["network"]["dhcp_reservations"] == [
            {"mac": "64:35:1c:00:f0:79", "ip": "192.168.10.2", "hostname": "routecam"}
        ]
