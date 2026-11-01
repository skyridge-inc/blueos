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


@pytest.fixture(autouse=True)
def _in_tmp_cwd(tmp_path, monkeypatch):
    """`config download` always writes to ./config, so run each test from tmp_path."""
    monkeypatch.chdir(tmp_path)


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

        out = tmp_path / "config" / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", out.name])
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

        out = tmp_path / "config" / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", out.name])
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

        out = tmp_path / "config" / "test.yaml"
        result = runner.invoke(
            app, ["config", "download", "192.168.2.2", "-o", out.name, "--include-calibration"]
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
        assert (tmp_path / "config" / "blueos.yaml").exists()

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_params_are_sorted(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("ZZZ_PARAM", 9.0, 0, 3),
            _make_param_msg("AAA_PARAM", 1.0, 1, 3),
            _make_param_msg("MMM_PARAM", 5.0, 2, 3),
        ])

        out = tmp_path / "config" / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", out.name])
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

        out = tmp_path / "config" / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", out.name])
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

        out = tmp_path / "config" / "test.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", out.name])
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
        cfg.write_text(yaml.dump({"network": {"hotspot": None, "ethernet": []}}))

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

        out = tmp_path / "config" / "out.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", out.name])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(out.read_text())
        assert data["network"]["dhcp_reservations"] == [
            {"mac": "64:35:1c:00:f0:79", "ip": "192.168.10.2", "hostname": "routecam"}
        ]


class TestUploadWifi:
    def _client(self, saved_ssids: list[str]):
        client = _mock_blueos_client()
        client.get_wifi_saved.return_value = [{"networkid": 0, "ssid": s} for s in saved_ssids]
        client.connect_wifi.return_value = True
        return client

    def _upload(self, mock_cls, client, tmp_path, ssids, *extra, input=None):
        mock_cls.return_value = client
        cfg = tmp_path / "config.yaml"
        cfg.write_text(yaml.dump({"network": {"wifi_saved": [{"networkid": 0, "ssid": s} for s in ssids]}}))
        return runner.invoke(
            app, ["config", "upload", "192.168.2.2", str(cfg), "-y", *extra], input=input,
        )

    @patch("skynet.blueos_api.BlueOSClient")
    def test_prompts_and_connects_missing_network(self, mock_cls, tmp_path):
        client = self._client(saved_ssids=[])
        result = self._upload(mock_cls, client, tmp_path, ["007"], input="s3cret!!\ns3cret!!\n")
        assert result.exit_code == 0, result.output
        client.connect_wifi.assert_called_once_with("007", "s3cret!!")
        assert "WiFi (1)" in result.output
        assert "s3cret!!" not in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_skips_already_saved_network_without_prompt(self, mock_cls, tmp_path):
        client = self._client(saved_ssids=["007"])
        result = self._upload(mock_cls, client, tmp_path, ["007"], input="")
        assert result.exit_code == 0, result.output
        assert "already saved" in result.output
        client.connect_wifi.assert_not_called()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_blank_password_skips(self, mock_cls, tmp_path):
        client = self._client(saved_ssids=[])
        result = self._upload(mock_cls, client, tmp_path, ["guest"], input="\n")
        assert result.exit_code == 0, result.output
        client.connect_wifi.assert_not_called()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_connect_failure_warns(self, mock_cls, tmp_path):
        client = self._client(saved_ssids=[])
        client.connect_wifi.return_value = False
        result = self._upload(mock_cls, client, tmp_path, ["007"], input="pw123456\npw123456\n")
        assert result.exit_code == 0, result.output
        assert "No confirmation for WiFi '007'" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_dry_run_does_not_prompt(self, mock_cls, tmp_path):
        client = self._client(saved_ssids=[])
        result = self._upload(mock_cls, client, tmp_path, ["007"], "--dry-run", input="")
        assert result.exit_code == 0, result.output
        assert "WiFi networks: 007" in result.output
        assert "password for" not in result.output
        client.connect_wifi.assert_not_called()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_mismatched_confirmation_reprompts(self, mock_cls, tmp_path):
        client = self._client(saved_ssids=[])
        result = self._upload(
            mock_cls, client, tmp_path, ["007"],
            input="first111\nother222\nfinal333\nfinal333\n",
        )
        assert result.exit_code == 0, result.output
        assert "did not match" in result.output
        client.connect_wifi.assert_called_once_with("007", "final333")


class TestWifiPinsAndHotspot:
    """wifi_saved interface/band pins and the hotspot setting."""

    ENTRY = {"ssid": "007", "interface": "wlan1", "band": "bg"}

    def _client(self, profile_stdout: str | None = "wlan0\n\n", set_rc: int = 0, hotspot=False):
        client = _mock_blueos_client()
        client.get_wifi_saved.return_value = [{"networkid": 0, "ssid": "007"}]
        client.get_hotspot.return_value = hotspot
        client.set_hotspot.return_value = True

        def run_host_command(cmd: str):
            if "connection show" in cmd:
                if profile_stdout is None:
                    return {"stdout": "", "stderr": "no such connection profile", "return_code": 10}
                return {"stdout": profile_stdout, "stderr": "", "return_code": 0}
            if "connection modify" in cmd:
                return {"stdout": "", "stderr": "", "return_code": set_rc}
            return {"stdout": "", "stderr": "", "return_code": 0}

        client.run_host_command.side_effect = run_host_command
        return client

    def _upload(self, mock_cls, client, tmp_path, network, *extra):
        mock_cls.return_value = client
        cfg = tmp_path / "config.yaml"
        cfg.write_text(yaml.dump({"network": network}))
        return runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y", *extra])

    def _host_cmds(self, client):
        return [c.args[0] for c in client.run_host_command.call_args_list]

    @patch("skynet.blueos_api.BlueOSClient")
    def test_pins_profile_to_interface_and_band(self, mock_cls, tmp_path):
        client = self._client()
        result = self._upload(mock_cls, client, tmp_path, {"wifi_saved": [self.ENTRY]})
        assert result.exit_code == 0, result.output
        modify = [c for c in self._host_cmds(client) if "connection modify" in c]
        assert modify == [
            "sudo nmcli connection modify id 007 connection.interface-name wlan1 "
            "802-11-wireless.band bg && sudo nmcli --wait 20 connection up id 007"
        ]
        assert "WiFi pins (1)" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_already_pinned_is_not_modified(self, mock_cls, tmp_path):
        client = self._client(profile_stdout="wlan1\nbg\n")
        result = self._upload(mock_cls, client, tmp_path, {"wifi_saved": [self.ENTRY]})
        assert result.exit_code == 0, result.output
        assert not any("connection modify" in c for c in self._host_cmds(client))
        assert "WiFi pins (1)" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_missing_profile_warns(self, mock_cls, tmp_path):
        client = self._client(profile_stdout=None)
        result = self._upload(mock_cls, client, tmp_path, {"wifi_saved": [self.ENTRY]})
        assert result.exit_code == 0, result.output
        assert "Could not pin WiFi '007 (wlan1, 2.4 GHz)'" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_reconnect_failure_warns(self, mock_cls, tmp_path):
        client = self._client(set_rc=4)
        result = self._upload(mock_cls, client, tmp_path, {"wifi_saved": [self.ENTRY]})
        assert result.exit_code == 0, result.output
        assert "Could not pin WiFi" in result.output
        assert "WiFi pins" not in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_entry_without_pins_runs_no_host_commands(self, mock_cls, tmp_path):
        client = self._client()
        result = self._upload(mock_cls, client, tmp_path, {"wifi_saved": [{"ssid": "007"}]})
        assert result.exit_code == 0, result.output
        client.run_host_command.assert_not_called()

    def test_invalid_band_rejected_before_changes(self, tmp_path):
        cfg = tmp_path / "config.yaml"
        cfg.write_text(yaml.dump({"network": {"wifi_saved": [{"ssid": "007", "band": "2.4"}]}}))
        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 1
        assert "Invalid WiFi band" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_enables_hotspot_when_off(self, mock_cls, tmp_path):
        client = self._client(hotspot=False)
        result = self._upload(mock_cls, client, tmp_path, {"hotspot": True})
        assert result.exit_code == 0, result.output
        client.set_hotspot.assert_called_once_with(True)
        assert "hotspot (on)" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_hotspot_already_matching_not_set(self, mock_cls, tmp_path):
        client = self._client(hotspot=True)
        result = self._upload(mock_cls, client, tmp_path, {"hotspot": True})
        assert result.exit_code == 0, result.output
        client.set_hotspot.assert_not_called()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_hotspot_set_after_pins(self, mock_cls, tmp_path):
        client = self._client()
        order: list[str] = []
        client.run_host_command.side_effect = (
            lambda cmd, inner=client.run_host_command.side_effect: (order.append("pin"), inner(cmd))[1]
        )
        client.set_hotspot.side_effect = lambda enable: (order.append("hotspot"), True)[1]
        result = self._upload(mock_cls, client, tmp_path, {"wifi_saved": [self.ENTRY], "hotspot": True})
        assert result.exit_code == 0, result.output
        assert order[-1] == "hotspot" and "pin" in order

    @patch("skynet.blueos_api.BlueOSClient")
    def test_dry_run_shows_pins_and_hotspot(self, mock_cls, tmp_path):
        client = self._client()
        result = self._upload(
            mock_cls, client, tmp_path, {"wifi_saved": [self.ENTRY], "hotspot": True}, "--dry-run",
        )
        assert result.exit_code == 0, result.output
        assert "007 (wlan1, 2.4 GHz)" in result.output
        assert "Hotspot: on" in result.output
        client.run_host_command.assert_not_called()
        client.set_hotspot.assert_not_called()


class TestDownloadWifiPins:
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_download_adds_interface_and_band(self, mock_cls, mock_mavlink, tmp_path):
        client = _mock_blueos_client()
        client.get_wifi_saved.return_value = [{"networkid": 0, "ssid": "007"}]

        def run_host_command(cmd: str):
            if "connection show id 007" in cmd:
                return {"stdout": "wlan1\nbg\n", "stderr": "", "return_code": 0}
            return {"stdout": "", "stderr": "", "return_code": 1}

        client.run_host_command.side_effect = run_host_command
        mock_cls.return_value = client
        mock_mavlink.side_effect = MowerProvisionerError("no mav")

        out = tmp_path / "config" / "out.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", out.name])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(out.read_text())
        assert data["network"]["wifi_saved"] == [
            {"networkid": 0, "ssid": "007", "interface": "wlan1", "band": "bg"}
        ]


class TestAutopilotBase:
    def _write_base(self, path: Path, params: dict) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.dump({"autopilot_params": params}))
        return path

    @patch("skynet.cli.write_params", return_value=["CRUISE_SPEED", "WP_RADIUS", "GPS1_TYPE"])
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_upload_merges_sibling_base(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([])
        self._write_base(tmp_path / "autopilot_base.yaml", {"CRUISE_SPEED": 2.0, "WP_RADIUS": 3.0})
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"autopilot_params": {"WP_RADIUS": 1.5, "GPS1_TYPE": 26.0}}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert "base 2, rover overrides 1, added 1" in result.output
        written = mock_write.call_args[0][1]
        assert written == {"CRUISE_SPEED": 2.0, "GPS1_TYPE": 26.0, "WP_RADIUS": 1.5}

    @patch("skynet.blueos_api.BlueOSClient")
    def test_upload_base_only_dry_run(self, mock_cls, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        self._write_base(tmp_path / "autopilot_base.yaml", {"CRUISE_SPEED": 2.0})
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"hostname": "mower-01", "autopilot_params": {}}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Autopilot parameters: 1 (base 1, rover overrides 0, added 0)" in result.output
        assert "CRUISE_SPEED = 2.0" in result.output
        assert "(rover)" not in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_upload_dry_run_marks_rover_params(self, mock_cls, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        self._write_base(tmp_path / "autopilot_base.yaml", {"CRUISE_SPEED": 2.0})
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"autopilot_params": {"CRUISE_SPEED": 3.0}}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "CRUISE_SPEED = 3.0 (rover)" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_upload_explicit_base_missing_exits(self, mock_cls, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"hostname": "mower-01"}))

        result = runner.invoke(app, [
            "config", "upload", "192.168.2.2", str(cfg),
            "--base", str(tmp_path / "nope.yaml"), "--dry-run",
        ])
        assert result.exit_code == 1
        assert "Autopilot base not found" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_upload_filters_calibration_from_base(self, mock_cls, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        cal_param = sorted(CALIBRATION_PARAMS)[0]
        base = self._write_base(tmp_path / "fleet.yaml", {"CRUISE_SPEED": 2.0, cal_param: 1.0})
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"hostname": "mower-01"}))

        args = ["config", "upload", "192.168.2.2", str(cfg), "--base", str(base), "--dry-run"]
        result = runner.invoke(app, args)
        assert result.exit_code == 0, result.output
        assert f"{cal_param} =" not in result.output

        result = runner.invoke(app, args + ["--include-calibration"])
        assert f"{cal_param} =" in result.output

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_download_writes_only_diffs(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.return_value = _mock_mavlink_conn([
            _make_param_msg("CRUISE_SPEED", 2.0, 0, 2),
            _make_param_msg("WP_RADIUS", 1.5, 1, 2),
        ])
        self._write_base(tmp_path / "config" / "autopilot_base.yaml", {"CRUISE_SPEED": 2.0, "WP_RADIUS": 3.0})

        out = tmp_path / "config" / "rover.yaml"
        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", out.name])
        assert result.exit_code == 0, result.output
        assert yaml.safe_load(out.read_text())["autopilot_params"] == {"WP_RADIUS": 1.5}
        assert "2 read, 1 differ from" in result.output


class TestDownloadOutput:
    """`config download` writes ./config/<name>.yaml and never the base."""

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_drops_dhcp_client_leases(self, mock_cls, mock_mavlink, tmp_path):
        client = _mock_blueos_client()
        client.get_ethernet.return_value = [
            {"name": "eth0", "addresses": [
                {"ip": "192.168.1.13", "mode": "client"},
                {"ip": "192.168.2.2", "mode": "unmanaged"},
            ]},
            {"name": "eth1", "addresses": [{"ip": "192.168.10.1", "mode": "server"}]},
        ]
        mock_cls.return_value = client
        mock_mavlink.side_effect = MowerProvisionerError("no mav")

        result = runner.invoke(app, ["config", "download", "192.168.2.2"])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load((tmp_path / "config" / "blueos.yaml").read_text())
        assert data["network"]["ethernet"] == [
            {"name": "eth0", "addresses": [{"ip": "192.168.2.2", "mode": "unmanaged"}]},
            {"name": "eth1", "addresses": [{"ip": "192.168.10.1", "mode": "server"}]},
        ]

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_autopilot_offline_keeps_existing_params(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.side_effect = MowerProvisionerError("no mav")
        out = tmp_path / "config" / "rover.yaml"
        out.parent.mkdir()
        out.write_text(yaml.dump({"hostname": "old", "autopilot_params": {"GPS1_TYPE": 26.0}}))

        result = runner.invoke(app, ["config", "download", "192.168.2.2", "-o", "rover.yaml"])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(out.read_text())
        assert data["hostname"] == "blueos"  # rest of the file is refreshed
        assert data["autopilot_params"] == {"GPS1_TYPE": 26.0}
        assert "kept existing" in result.output

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_autopilot_offline_new_file_has_no_params(self, mock_cls, mock_mavlink, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        mock_mavlink.side_effect = MowerProvisionerError("no mav")

        result = runner.invoke(app, ["config", "download", "192.168.2.2"])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load((tmp_path / "config" / "blueos.yaml").read_text())
        assert "autopilot_params" not in data
        assert "none written" in result.output

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_falls_back_to_host_name(self, mock_cls, mock_mavlink, tmp_path):
        client = _mock_blueos_client()
        client.get_hostname.return_value = None
        mock_cls.return_value = client
        mock_mavlink.side_effect = MowerProvisionerError("no mav")

        result = runner.invoke(app, ["config", "download", "blueos.local"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "config" / "blueos.local.yaml").exists()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_output_config_prefix_accepted(self, mock_cls, tmp_path):
        mock_cls.return_value = _mock_blueos_client()
        with patch("skynet.cli.mavlink_connection", side_effect=MowerProvisionerError("x")):
            result = runner.invoke(app, ["config", "download", "h", "-o", "config/sky9.yaml"])
        assert result.exit_code == 0, result.output
        assert (tmp_path / "config" / "sky9.yaml").exists()

    @pytest.mark.parametrize("name", ["/tmp/x.yaml", "other/x.yaml", "autopilot_base.yaml"])
    @patch("skynet.blueos_api.BlueOSClient")
    def test_rejects_other_dirs_and_base(self, mock_cls, name, tmp_path):
        result = runner.invoke(app, ["config", "download", "h", "-o", name])
        assert result.exit_code == 1
        mock_cls.assert_not_called()
        assert not (tmp_path / "config" / "autopilot_base.yaml").exists()


class TestAutopilotStartAndHotplug:
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_download_starts_idle_autopilot(self, mock_cls, mock_mavlink, tmp_path):
        client = _mock_blueos_client()
        client.autopilot_running.side_effect = [False, True]
        client.start_autopilot.return_value = True
        mock_cls.return_value = client
        mock_mavlink.side_effect = MowerProvisionerError("no mav")

        result = runner.invoke(app, ["config", "download", "192.168.2.2"])
        assert result.exit_code == 0, result.output
        client.start_autopilot.assert_called_once()
        assert "started it" in result.output

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_download_leaves_running_autopilot(self, mock_cls, mock_mavlink, tmp_path):
        client = _mock_blueos_client()
        client.autopilot_running.return_value = True
        mock_cls.return_value = client
        mock_mavlink.side_effect = MowerProvisionerError("no mav")

        result = runner.invoke(app, ["config", "download", "192.168.2.2"])
        assert result.exit_code == 0, result.output
        client.start_autopilot.assert_not_called()

    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_download_records_hotplug_start(self, mock_cls, mock_mavlink, tmp_path):
        client = _mock_blueos_client()
        client.run_host_command.side_effect = lambda cmd: {
            "stdout": "", "stderr": "",
            "return_code": 0 if "90-skynet-autopilot.rules" in cmd else 1,
        }
        mock_cls.return_value = client
        mock_mavlink.side_effect = MowerProvisionerError("no mav")

        result = runner.invoke(app, ["config", "download", "192.168.2.2"])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load((tmp_path / "config" / "blueos.yaml").read_text())
        assert data["autopilot_autostart"] is True

    @patch("skynet.cli.write_params", return_value=["CRUISE_SPEED"])
    @patch("skynet.cli.mavlink_connection")
    @patch("skynet.blueos_api.BlueOSClient")
    def test_upload_starts_idle_autopilot_before_params(self, mock_cls, mock_mavlink, mock_write, tmp_path):
        client = _mock_blueos_client()
        client.autopilot_running.side_effect = [False, True]
        client.start_autopilot.return_value = True
        mock_cls.return_value = client
        mock_mavlink.return_value = _mock_mavlink_conn([])
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"autopilot_params": {"CRUISE_SPEED": 2.0}}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        client.start_autopilot.assert_called_once()
        mock_write.assert_called_once()

    @patch("skynet.blueos_api.BlueOSClient")
    def test_upload_without_params_does_not_start_autopilot(self, mock_cls, tmp_path):
        client = _mock_blueos_client()
        client.autopilot_running.return_value = False
        mock_cls.return_value = client
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"hostname": "mower-01"}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        client.start_autopilot.assert_not_called()

    @pytest.mark.parametrize("enable, marker", [(True, "install"), (False, "remove")])
    @patch("skynet.blueos_api.BlueOSClient")
    def test_upload_applies_hotplug_start(self, mock_cls, enable, marker, tmp_path):
        client = _mock_blueos_client()
        client.run_host_command.return_value = {"stdout": "changed\n", "stderr": "", "return_code": 0}
        mock_cls.return_value = client
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"autopilot_autostart": enable}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        assert f"Autopilot hot-plug start: {marker}" in result.output
        assert f"autopilot hot-plug start ({'on' if enable else 'off'})" in result.output
        client.run_host_command.assert_called_once()
        assert "sudo bash" in client.run_host_command.call_args[0][0]

    @patch("skynet.blueos_api.BlueOSClient")
    def test_upload_hotplug_dry_run_runs_nothing(self, mock_cls, tmp_path):
        client = _mock_blueos_client()
        mock_cls.return_value = client
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"autopilot_autostart": True}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "--dry-run"])
        assert result.exit_code == 0, result.output
        client.run_host_command.assert_not_called()
        client.start_autopilot.assert_not_called()


class TestUploadVideoStreams:
    FRONT = {"name": "front", "source": "Redirect", "endpoints": ["rtsp://127.0.0.1:8555/front"]}

    @patch("skynet.blueos_api.BlueOSClient")
    def test_creates_missing_stream(self, mock_cls, tmp_path):
        client = _mock_blueos_client()
        client.get_video_streams.return_value = []
        client.add_video_stream.return_value = True
        mock_cls.return_value = client
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"video_streams": [self.FRONT]}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        body = client.add_video_stream.call_args[0][0]
        assert body["name"] == "front"
        assert body["stream_information"]["configuration"] == {"type": "redirect"}
        assert "video streams (1)" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_skips_existing_stream(self, mock_cls, tmp_path):
        client = _mock_blueos_client()
        client.get_video_streams.return_value = [{"video_and_stream": {"name": "front"}}]
        mock_cls.return_value = client
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"video_streams": [self.FRONT]}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "-y"])
        assert result.exit_code == 0, result.output
        client.add_video_stream.assert_not_called()
        assert "already on device" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_dry_run_creates_nothing(self, mock_cls, tmp_path):
        client = _mock_blueos_client()
        mock_cls.return_value = client
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"video_streams": [self.FRONT]}))

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(cfg), "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "rtsp://127.0.0.1:8555/front" in result.output
        client.add_video_stream.assert_not_called()


class TestUploadCockpitStreamRename:
    KEY = "cockpit/settings/sky1/cockpit-streams-correspondency"
    PROFILES_KEY = "cockpit/settings/sky1/cockpit-saved-profiles-v8"

    @staticmethod
    def _device_bag():
        widgets = [{"options": {"internalStreamName": "Stream 1"}} for _ in range(2)]
        return {"cockpit": {"settings": {"sky1": {
            "cockpit-streams-correspondency": [{"name": "Stream 1", "externalId": "front"}],
            "cockpit-saved-profiles-v8": [{"views": [{"widgets": widgets}]}],
        }}}}

    def _write_cfg(self, tmp_path):
        cfg = tmp_path / "rover.yaml"
        cfg.write_text(yaml.dump({"bag": {self.KEY: [{"name": "front", "externalId": "front"}]}}))
        return cfg

    @patch("skynet.blueos_api.BlueOSClient")
    def test_repoints_widgets_before_renaming(self, mock_cls, tmp_path):
        client = _mock_blueos_client()
        client.get_bag.return_value = self._device_bag()
        mock_cls.return_value = client

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(self._write_cfg(tmp_path)), "-y"])
        assert result.exit_code == 0, result.output

        keys = [c.args[0] for c in client.set_bag.call_args_list]
        assert keys == [self.PROFILES_KEY, self.KEY]   # widgets first, then the rename
        profiles = client.set_bag.call_args_list[0].args[1]
        names = [w["options"]["internalStreamName"] for w in profiles[0]["views"][0]["widgets"]]
        assert names == ["front", "front"]
        assert "2 widgets re-pointed" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_failed_widget_update_keeps_old_name(self, mock_cls, tmp_path):
        client = _mock_blueos_client()
        client.get_bag.return_value = self._device_bag()
        client.set_bag.side_effect = lambda key, value: key != self.PROFILES_KEY
        mock_cls.return_value = client

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(self._write_cfg(tmp_path)), "-y"])
        assert result.exit_code == 0, result.output
        keys = [c.args[0] for c in client.set_bag.call_args_list]
        assert self.KEY not in keys
        assert "keeping its stream names" in " ".join(result.output.split())

    @patch("skynet.blueos_api.BlueOSClient")
    def test_unreadable_bag_skips_rename(self, mock_cls, tmp_path):
        client = _mock_blueos_client()
        client.get_bag.return_value = None
        mock_cls.return_value = client

        result = runner.invoke(app, ["config", "upload", "192.168.2.2", str(self._write_cfg(tmp_path)), "-y"])
        assert result.exit_code == 0, result.output
        client.set_bag.assert_not_called()
        assert "Cannot read Cockpit settings" in result.output

    @patch("skynet.blueos_api.BlueOSClient")
    def test_dry_run_mentions_rename_without_contacting_device(self, mock_cls, tmp_path):
        client = _mock_blueos_client()
        mock_cls.return_value = client

        result = runner.invoke(
            app, ["config", "upload", "192.168.2.2", str(self._write_cfg(tmp_path)), "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert "Cockpit stream names: sky1" in result.output
        client.get_bag.assert_not_called()
        client.set_bag.assert_not_called()
