"""Tests for host_config — dnsmasq reservation rendering and host commands."""

from __future__ import annotations

import base64
import json
import shlex

from skynet.host_config import (
    DNSMASQ_CONTAINER_PATH,
    DNSMASQ_HOST_PATH,
    ensure_bind_command,
    parse_dnsmasq_conf,
    render_dnsmasq_conf,
    write_file_command,
)

CAMERA = {"mac": "64:35:1c:00:f0:79", "ip": "192.168.10.2", "hostname": "routecam"}


class TestRenderParse:
    def test_round_trip(self):
        reservations = [CAMERA, {"mac": "aa:bb:cc:dd:ee:ff", "ip": "192.168.10.3"}]
        assert parse_dnsmasq_conf(render_dnsmasq_conf(reservations)) == reservations

    def test_render_line_format(self):
        text = render_dnsmasq_conf([CAMERA])
        assert "dhcp-host=64:35:1c:00:f0:79,192.168.10.2,routecam\n" in text
        assert text.startswith("#")

    def test_render_lowercases_mac(self):
        text = render_dnsmasq_conf([{"mac": "64:35:1C:00:F0:79", "ip": "192.168.10.2"}])
        assert "dhcp-host=64:35:1c:00:f0:79,192.168.10.2\n" in text

    def test_render_empty(self):
        assert parse_dnsmasq_conf(render_dnsmasq_conf([])) == []

    def test_parse_ignores_comments_and_other_options(self):
        text = (
            "# comment\n"
            "\n"
            "#dhcp-host=11:11:11:11:11:11,10.0.0.1\n"
            "log-dhcp\n"
            "dhcp-host=64:35:1C:00:F0:79,192.168.10.2,routecam  # front cam\n"
            "dhcp-host=bad\n"
        )
        assert parse_dnsmasq_conf(text) == [CAMERA]


class TestCommands:
    def test_write_file_command_round_trips_content(self):
        content = "line with 'quotes' and \"double\" $VARS\n"
        cmd = write_file_command(DNSMASQ_HOST_PATH, content)
        encoded = shlex.split(cmd)[1]
        assert base64.b64decode(encoded).decode() == content
        assert cmd.endswith(f"sudo tee {DNSMASQ_HOST_PATH} >/dev/null")

    def _run_bind_script(self, startup: dict, tmp_path, monkeypatch) -> tuple[str, dict]:
        """Execute the ensure-bind script against a temp startup.json."""
        path = tmp_path / "startup.json"
        path.write_text(json.dumps(startup))
        script = shlex.split(ensure_bind_command())[-1]
        script = script.replace("/root/.config/blueos/bootstrap/startup.json", str(path))
        out: list[str] = []
        monkeypatch.setattr("builtins.print", lambda *a: out.append(" ".join(map(str, a))))
        exec(script, {})
        return out[-1], json.loads(path.read_text())

    def test_ensure_bind_adds_and_backs_up(self, tmp_path, monkeypatch):
        startup = {"core": {"binds": {"/dev/": {"bind": "/dev/", "mode": "rw"}}}}
        status, data = self._run_bind_script(startup, tmp_path, monkeypatch)
        assert status == "changed"
        assert data["core"]["binds"][DNSMASQ_HOST_PATH] == {
            "bind": DNSMASQ_CONTAINER_PATH, "mode": "ro",
        }
        assert data["core"]["binds"]["/dev/"] == {"bind": "/dev/", "mode": "rw"}
        assert list(tmp_path.glob("startup.json.bak-*"))

    def test_ensure_bind_idempotent(self, tmp_path, monkeypatch):
        startup = {"core": {"binds": {
            DNSMASQ_HOST_PATH: {"bind": DNSMASQ_CONTAINER_PATH, "mode": "ro"},
        }}}
        status, _ = self._run_bind_script(startup, tmp_path, monkeypatch)
        assert status == "unchanged"
        assert not list(tmp_path.glob("startup.json.bak-*"))

    def test_ensure_bind_command_uses_sudo(self):
        assert ensure_bind_command().startswith("sudo python3 -c ")
