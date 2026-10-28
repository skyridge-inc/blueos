"""Tests for gnss_receiver — USB scan, reply parsing, config apply — and the config_gps CLI."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
import yaml
from typer.testing import CliRunner

from skynet.cli import app
from skynet.exceptions import GnssReceiverError
from skynet.gnss_receiver import (
    SEPTENTRIO_VID,
    SeptentrioReceiver,
    UsbReceiver,
    find_receivers,
    parse_config_listing,
    parse_identification,
)

runner = CliRunner()

BOOT_COMMANDS = [
    "setDataInOut, COM1, , none",
    "setSBFOutput, Stream3, COM3",
    "setCOMSettings, COM3, baud230400",
]

IDENT_REPLY = (
    "$R; lstInternalFile, Identification\n---->\n$-- BLOCK 1 / 2\n"
    '<hwplatform product="mosaic-H"\n name="GRB0051" serialnr="3806485"\n rxfullid="SN1">\n'
    "---->\n$-- BLOCK 2 / 2\n"
    '<firmware version="4.14.4" date="231130" rev="ge16550">\n'
    '<bootloader version="0.0.0" date="700101"/>\n'
    "USB1>"
)


def _listing(commands: list[str], which: str = "Boot") -> str:
    body = "".join(f"  {c}\n" for c in commands)
    return (
        f"$R; lstConfigFile, {which}\n---->\n$-- BLOCK 1 / 0\n"
        f'# Configuration File "{which}"\n# Different from RxDefault:\n{body}USB1>'
    )


class FakeSerial:
    """Scripted Septentrio USB port: replies keyed by command text."""

    def __init__(self, replies: dict[str, str] | None = None) -> None:
        self.replies = replies or {}
        self.sent: list[str] = []
        self._out = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        cmd = data.decode().strip()
        self.sent.append(cmd)
        if cmd.startswith("SSSS"):
            reply = "USB1>"
        else:
            reply = self.replies.get(cmd, f"$R: {cmd}\nUSB1>")
        self._out += (reply.replace("\n", "\r\n") + "\r\n").encode()

    def read(self, n: int) -> bytes:
        out, self._out = self._out[:n], self._out[n:]
        return out

    def reset_input_buffer(self) -> None:
        self._out = b""

    def close(self) -> None:
        self.closed = True


def _receiver(fake: FakeSerial) -> SeptentrioReceiver:
    return SeptentrioReceiver("/dev/fake", serial_factory=lambda *a, **k: fake)


class TestFindReceivers:
    def _port(self, device, vid, serial="3806485"):
        return SimpleNamespace(
            device=device, vid=vid, serial_number=serial,
            product="Septentrio USB Device", description="desc",
        )

    def test_filters_by_vendor_and_dedupes_by_serial(self):
        ports = [
            self._port("/dev/ttyACM2", SEPTENTRIO_VID),
            self._port("/dev/ttyACM0", SEPTENTRIO_VID),
            self._port("/dev/ttyUSB0", 0x0403, serial="FTDI1"),
        ]
        found = find_receivers(lambda: ports)
        assert found == [UsbReceiver(
            port="/dev/ttyACM0", vendor="Septentrio",
            description="Septentrio USB Device", serial_number="3806485",
        )]

    def test_two_receivers(self):
        ports = [
            self._port("/dev/ttyACM0", SEPTENTRIO_VID, serial="A"),
            self._port("/dev/ttyACM1", SEPTENTRIO_VID, serial="B"),
        ]
        assert [r.serial_number for r in find_receivers(lambda: ports)] == ["A", "B"]

    def test_none(self):
        assert find_receivers(lambda: []) == []


class TestParsing:
    def test_identification(self):
        assert parse_identification(IDENT_REPLY) == {
            "vendor": "Septentrio", "product": "mosaic-H",
            "serial": "3806485", "firmware": "4.14.4",
        }

    def test_config_listing(self):
        assert parse_config_listing(_listing(BOOT_COMMANDS)) == BOOT_COMMANDS

    def test_config_listing_empty(self):
        assert parse_config_listing(_listing([])) == []


class TestSeptentrioReceiver:
    def test_identify_and_get_config(self):
        fake = FakeSerial({
            "lstInternalFile, Identification": IDENT_REPLY,
            "lstConfigFile, Boot": _listing(BOOT_COMMANDS),
        })
        with _receiver(fake) as rx:
            assert rx.identify()["product"] == "mosaic-H"
            assert rx.get_config("Boot") == BOOT_COMMANDS
        assert fake.sent[0].startswith("SSSS")
        assert fake.closed

    def test_rejected_command_raises(self):
        fake = FakeSerial({"bogus": "$R? bogus: Invalid command!\nUSB1>"})
        with _receiver(fake) as rx:
            with pytest.raises(GnssReceiverError, match="Invalid command"):
                rx.command("bogus")

    def test_apply_config_resets_replays_and_saves(self):
        fake = FakeSerial()
        with _receiver(fake) as rx:
            rx.apply_config(BOOT_COMMANDS)
        assert fake.sent[1:] == [
            "exeCopyConfigFile, RxDefault, Current",
            *BOOT_COMMANDS,
            "exeCopyConfigFile, Current, Boot",
        ]

    def test_apply_config_stops_on_error(self):
        fake = FakeSerial({BOOT_COMMANDS[1]: f"$R? {BOOT_COMMANDS[1]}: bad\nUSB1>"})
        with _receiver(fake) as rx:
            with pytest.raises(GnssReceiverError):
                rx.apply_config(BOOT_COMMANDS)
        assert "exeCopyConfigFile, Current, Boot" not in fake.sent

    def test_no_reply_times_out(self):
        class Silent(FakeSerial):
            def write(self, data):
                self.sent.append(data.decode().strip())

        rx = _receiver(Silent())
        with pytest.raises(GnssReceiverError, match="No reply"):
            rx.command("getCOMSettings, all", timeout=0.05)

    def test_disconnect_raises_receiver_error(self):
        class Unplugged(FakeSerial):
            def read(self, n):
                raise OSError("Device not configured")

        rx = _receiver(Unplugged())
        with pytest.raises(GnssReceiverError, match="Lost connection"):
            rx.command("exeResetReceiver, Hard, none")

    def test_open_failure(self):
        def boom(*a, **k):
            raise OSError("busy")

        with pytest.raises(GnssReceiverError, match="Cannot open"):
            SeptentrioReceiver("/dev/x", serial_factory=boom)


FOUND = [UsbReceiver("/dev/fake", "Septentrio", "Septentrio USB Device", "3806485")]


def _patched_receiver(fake: FakeSerial):
    return patch(
        "skynet.gnss_receiver.SeptentrioReceiver",
        side_effect=lambda port: _receiver(fake),
    )


class TestConfigGpsCli:
    def test_download(self, tmp_path):
        fake = FakeSerial({
            "lstInternalFile, Identification": IDENT_REPLY,
            "lstConfigFile, Boot": _listing(BOOT_COMMANDS),
        })
        out = tmp_path / "gps.yaml"
        with patch("skynet.gnss_receiver.find_receivers", return_value=FOUND), _patched_receiver(fake):
            result = runner.invoke(app, ["config_gps", "download", "-o", str(out)])
        assert result.exit_code == 0, result.output
        data = yaml.safe_load(out.read_text())
        assert data["receiver"]["product"] == "mosaic-H"
        assert data["config"] == BOOT_COMMANDS

    def test_download_no_receiver(self):
        with patch("skynet.gnss_receiver.find_receivers", return_value=[]):
            result = runner.invoke(app, ["config_gps", "download"])
        assert result.exit_code == 1

    def test_download_multiple_receivers_needs_port(self):
        two = FOUND + [UsbReceiver("/dev/fake2", "Septentrio", "x", "999")]
        with patch("skynet.gnss_receiver.find_receivers", return_value=two):
            result = runner.invoke(app, ["config_gps", "download"])
        assert result.exit_code == 1

    def _write_cfg(self, tmp_path, product="mosaic-H"):
        cfg = tmp_path / "gps.yaml"
        cfg.write_text(yaml.safe_dump({"receiver": {"product": product}, "config": BOOT_COMMANDS}))
        return cfg

    def test_upload_applies_and_verifies(self, tmp_path):
        fake = FakeSerial({
            "lstInternalFile, Identification": IDENT_REPLY,
            "lstConfigFile, Boot": _listing(BOOT_COMMANDS),
        })
        with patch("skynet.gnss_receiver.find_receivers", return_value=FOUND), _patched_receiver(fake):
            result = runner.invoke(app, ["config_gps", "upload", str(self._write_cfg(tmp_path)), "-y"])
        assert result.exit_code == 0, result.output
        assert "verified" in result.output
        assert "exeCopyConfigFile, Current, Boot" in fake.sent
        assert all(c in fake.sent for c in BOOT_COMMANDS)

    def test_upload_dry_run_does_not_scan(self, tmp_path):
        with patch("skynet.gnss_receiver.find_receivers") as scan:
            result = runner.invoke(app, ["config_gps", "upload", str(self._write_cfg(tmp_path)), "--dry-run"])
        assert result.exit_code == 0
        scan.assert_not_called()

    def test_upload_declined(self, tmp_path):
        fake = FakeSerial({"lstInternalFile, Identification": IDENT_REPLY})
        with patch("skynet.gnss_receiver.find_receivers", return_value=FOUND), _patched_receiver(fake):
            result = runner.invoke(app, ["config_gps", "upload", str(self._write_cfg(tmp_path))], input="n\n")
        assert result.exit_code == 1
        assert not any(c.startswith("exeCopyConfigFile") for c in fake.sent)

    def test_upload_product_mismatch_warns(self, tmp_path):
        fake = FakeSerial({
            "lstInternalFile, Identification": IDENT_REPLY,
            "lstConfigFile, Boot": _listing(BOOT_COMMANDS),
        })
        cfg = self._write_cfg(tmp_path, product="mosaic-X5")
        with patch("skynet.gnss_receiver.find_receivers", return_value=FOUND), _patched_receiver(fake):
            result = runner.invoke(app, ["config_gps", "upload", str(cfg), "-y"])
        assert result.exit_code == 0
        assert "mosaic-X5" in result.output

    def test_upload_bad_file(self, tmp_path):
        cfg = tmp_path / "gps.yaml"
        cfg.write_text("config: not-a-list\n")
        result = runner.invoke(app, ["config_gps", "upload", str(cfg), "-y"])
        assert result.exit_code == 1
