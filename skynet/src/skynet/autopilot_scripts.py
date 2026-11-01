"""ArduPilot Lua scripts listed in a rover YAML, copied to the Cube's SD card.

``autopilot_scripts`` lists script files relative to the rover YAML, e.g.
``scripts/cube_temp_f.lua``. Upload enables scripting (SCR_ENABLE=1), copies
each script to APM/scripts/ over MAVFTP when its content differs, and the
autopilot is rebooted so it loads them.
"""

from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from .exceptions import AutopilotFileError, ParamFileError

SCRIPTS_KEY = "autopilot_scripts"
REMOTE_DIR = "/APM/scripts"
# Scripting only starts at boot, so enabling it needs a reboot.
SCRIPTING_PARAMS: dict[str, float] = {"SCR_ENABLE": 1.0}


def load_scripts(entries: Any, yaml_path: Path) -> dict[str, bytes]:
    """Read the listed scripts: {file name on the Cube: content}.

    Raises:
        ParamFileError: If the list is malformed or a file can't be read.
    """
    if entries is None:
        return {}
    if not isinstance(entries, list):
        raise ParamFileError(f"{SCRIPTS_KEY} must be a list of .lua paths")
    scripts: dict[str, bytes] = {}
    for entry in entries:
        path = yaml_path.parent / str(entry)
        if path.suffix != ".lua":
            raise ParamFileError(f"{SCRIPTS_KEY}: {entry} is not a .lua file")
        if path.name in scripts:
            raise ParamFileError(f"{SCRIPTS_KEY}: two scripts named {path.name}")
        try:
            scripts[path.name] = path.read_bytes()
        except OSError as e:
            raise ParamFileError(f"{SCRIPTS_KEY}: cannot read {path}: {e}") from e
    return scripts


def _ftp(conn: Any) -> Any:
    from pymavlink.mavftp import MAVFTP

    return MAVFTP(conn, conn.target_system, conn.target_component)


def _read_remote(ftp: Any, remote: str) -> bytes | None:
    """The file's content on the autopilot, or None if it doesn't exist."""
    from pymavlink.mavftp import FtpError

    result: dict[str, bytes] = {}
    ftp.cmd_get([remote], callback=lambda fh: result.__setitem__("data", fh.read()))
    ret = ftp.process_ftp_reply("OpenFileRO", timeout=10)
    if ret.error_code != FtpError.Success:
        return None
    return result.get("data")


def sync_scripts(conn: Any, scripts: dict[str, bytes]) -> list[str]:
    """Copy scripts whose content differs to APM/scripts/. Returns names copied.

    Raises:
        AutopilotFileError: If a copy fails.
    """
    from pymavlink.mavftp import FtpError

    ftp = _ftp(conn)
    copied: list[str] = []
    for name, content in sorted(scripts.items()):
        remote = f"{REMOTE_DIR}/{name}"
        if _read_remote(ftp, remote) == content:
            continue
        for directory in ("/APM", REMOTE_DIR):
            ftp.cmd_mkdir([directory])   # fails harmlessly when it already exists
        ftp.cmd_put([name, remote], fh=io.BytesIO(content), callback=lambda _size: None)
        ret = ftp.process_ftp_reply("CreateFile", timeout=30)
        if ret.error_code != FtpError.Success:
            raise AutopilotFileError(f"copying {name} to {remote} failed ({ret.error_code!r})")
        if _read_remote(ftp, remote) != content:
            raise AutopilotFileError(f"{remote} does not match {name} after copying")
        copied.append(name)
    return copied
