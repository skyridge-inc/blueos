"""Tests for copying rover Lua scripts to the autopilot."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pymavlink.mavftp import FtpError

from skynet.autopilot_scripts import load_scripts, sync_scripts
from skynet.exceptions import AutopilotFileError, ParamFileError


def test_load_scripts_relative_to_yaml(tmp_path):
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "a.lua").write_bytes(b"x")
    assert load_scripts(["scripts/a.lua"], tmp_path / "sky1.yaml") == {"a.lua": b"x"}
    assert load_scripts(None, tmp_path / "sky1.yaml") == {}


@pytest.mark.parametrize("entries, message", [
    ("scripts/a.lua", "must be a list"),
    (["scripts/a.txt"], "not a .lua"),
    (["scripts/missing.lua"], "cannot read"),
])
def test_load_scripts_errors(tmp_path, entries, message):
    with pytest.raises(ParamFileError, match=message):
        load_scripts(entries, tmp_path / "sky1.yaml")


class FakeFtp:
    """Stands in for pymavlink's MAVFTP with an in-memory SD card."""

    def __init__(self, files=None, put_error=FtpError.Success):
        self.files = dict(files or {})
        self.put_error = put_error
        self.puts = []
        self._pending = None

    def cmd_get(self, args, callback=None):
        self._pending = ("get", args[0], callback)

    def cmd_put(self, args, fh=None, callback=None):
        self._pending = ("put", args[1], fh.read())

    def cmd_mkdir(self, args):
        return MagicMock(error_code=FtpError.Success)

    def process_ftp_reply(self, name, timeout=5):
        kind, path, extra = self._pending
        if kind == "get":
            if path not in self.files:
                return MagicMock(error_code=FtpError.FileNotFound)
            fh = MagicMock()
            fh.read.return_value = self.files[path]
            extra(fh)
            return MagicMock(error_code=FtpError.Success)
        if self.put_error == FtpError.Success:
            self.files[path] = extra
            self.puts.append(path)
        return MagicMock(error_code=self.put_error)


def test_sync_copies_new_and_changed_only():
    ftp = FakeFtp({"/APM/scripts/same.lua": b"same", "/APM/scripts/old.lua": b"v1"})
    with patch("skynet.autopilot_scripts._ftp", return_value=ftp):
        copied = sync_scripts(MagicMock(), {"same.lua": b"same", "old.lua": b"v2", "new.lua": b"n"})
    assert copied == ["new.lua", "old.lua"]
    assert ftp.files["/APM/scripts/old.lua"] == b"v2"
    assert "/APM/scripts/same.lua" not in ftp.puts


def test_sync_raises_on_copy_failure():
    ftp = FakeFtp(put_error=FtpError.Fail)
    with patch("skynet.autopilot_scripts._ftp", return_value=ftp):
        with pytest.raises(AutopilotFileError, match="new.lua"):
            sync_scripts(MagicMock(), {"new.lua": b"n"})
