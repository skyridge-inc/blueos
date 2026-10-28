"""USB-attached GNSS RTK/heading receiver discovery and configuration.

Supports Septentrio receivers (e.g. the mosaic-H on an ArduSimple
simpleRTK3B Heading). Their USB port is a CDC-ACM serial device that
accepts ASCII commands at any time; each reply starts with ``$R:``
(success), ``$R;`` (multi-block listing) or ``$R?`` (error) and ends
with a prompt naming the port, e.g. ``USB1>``.

A receiver's persistent configuration is its "Boot" config file. The
receiver lists it as the commands that differ from factory defaults
(``lstConfigFile, Boot``), and those commands can be replayed verbatim
to reproduce the configuration on another receiver.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from .exceptions import GnssReceiverError

SEPTENTRIO_VID = 0x152A

# Prompt that terminates every reply, e.g. "USB1>" or "COM2>".
_PROMPT_RE = re.compile(r"(?m)^[A-Z]+\d+>\s*$")
_CONFIG_HEADER = "# Different from RxDefault:"


@dataclass(frozen=True)
class UsbReceiver:
    """A GNSS receiver found on a USB serial port."""

    port: str
    vendor: str
    description: str
    serial_number: str | None


def find_receivers(comports: Callable[[], list[Any]] | None = None) -> list[UsbReceiver]:
    """Scan USB serial ports for supported GNSS receivers.

    A Septentrio receiver exposes two CDC-ACM ports (USB1/USB2) on some
    hosts; both accept commands, so only the first per serial number is
    returned.
    """
    if comports is None:
        from serial.tools.list_ports import comports

    found: dict[str, UsbReceiver] = {}
    for p in sorted(comports(), key=lambda p: p.device):
        if p.vid != SEPTENTRIO_VID:
            continue
        key = p.serial_number or p.device
        found.setdefault(key, UsbReceiver(
            port=p.device,
            vendor="Septentrio",
            description=p.product or p.description or "",
            serial_number=p.serial_number,
        ))
    return list(found.values())


def _printable(text: str) -> str:
    """Drop lines containing binary noise (e.g. stray SBF blocks)."""
    lines = text.replace("\r", "").split("\n")
    return "\n".join(l for l in lines if all(31 < ord(c) < 127 or c == "\t" for c in l))


def parse_identification(text: str) -> dict[str, str | None]:
    """Extract product, serial and firmware from ``lif, Identification``."""

    def find(pattern: str) -> str | None:
        m = re.search(pattern, text)
        return m.group(1) if m else None

    return {
        "vendor": "Septentrio",
        "product": find(r'<hwplatform[^>]*\bproduct="([^"]+)"'),
        "serial": find(r'\bserialnr="([^"]+)"'),
        "firmware": find(r'<firmware[^>]*\bversion="([^"]+)"'),
    }


def parse_config_listing(text: str) -> list[str]:
    """Extract the replayable commands from an ``lstConfigFile`` listing."""
    commands: list[str] = []
    in_body = False
    for line in text.split("\n"):
        if line.strip() == _CONFIG_HEADER:
            in_body = True
            continue
        if not in_body:
            continue
        if _PROMPT_RE.match(line) or not line.startswith("  "):
            break
        commands.append(line.strip())
    return commands


class SeptentrioReceiver:
    """Command session on a Septentrio receiver's USB serial port."""

    def __init__(self, port: str, serial_factory: Callable[..., Any] | None = None) -> None:
        if serial_factory is None:
            import serial

            serial_factory = serial.Serial
        try:
            # CDC-ACM ignores the baud rate; any value works.
            self._ser = serial_factory(port, 115200, timeout=0.2)
        except Exception as e:  # serial.SerialException, OSError
            raise GnssReceiverError(f"Cannot open {port}: {e}") from e
        self.port = port

    def close(self) -> None:
        self._ser.close()

    def __enter__(self) -> SeptentrioReceiver:
        # Forces command mode if the port was left in a data-only mode.
        self._ser.write(b"SSSSSSSSSS\r\n")
        self._read_until_prompt(timeout=2.0, required=False)
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _read_until_prompt(self, timeout: float, required: bool = True) -> str:
        buf = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                chunk = self._ser.read(4096)
            except OSError as e:  # serial.SerialException subclasses OSError
                raise GnssReceiverError(f"Lost connection to receiver on {self.port}: {e}") from e
            if chunk:
                buf += chunk.decode("ascii", errors="replace")
                if _PROMPT_RE.search(buf.replace("\r", "")):
                    return _printable(buf)
        if required:
            raise GnssReceiverError(f"No reply from receiver on {self.port} within {timeout:.0f}s")
        return _printable(buf)

    def command(self, cmd: str, timeout: float = 5.0) -> str:
        """Send a command and return the reply text (minus the prompt).

        Raises GnssReceiverError if the receiver rejects the command.
        """
        try:
            self._ser.reset_input_buffer()
            self._ser.write((cmd + "\r\n").encode("ascii"))
        except OSError as e:
            raise GnssReceiverError(f"Lost connection to receiver on {self.port}: {e}") from e
        reply = self._read_until_prompt(timeout)
        for line in reply.split("\n"):
            if line.startswith("$R?"):
                raise GnssReceiverError(f"Receiver rejected '{cmd}': {line[3:].strip()}")
        return _PROMPT_RE.sub("", reply).strip()

    def identify(self) -> dict[str, str | None]:
        return parse_identification(self.command("lstInternalFile, Identification", timeout=8.0))

    def get_config(self, which: str = "Boot") -> list[str]:
        return parse_config_listing(self.command(f"lstConfigFile, {which}", timeout=8.0))

    def apply_config(self, commands: list[str], on_command: Callable[[str], None] | None = None) -> None:
        """Make ``commands`` the receiver's entire Boot configuration.

        Resets the running config to factory defaults first so settings
        absent from ``commands`` don't linger, then replays them and
        saves the result to Boot.
        """
        self.command("exeCopyConfigFile, RxDefault, Current")
        for cmd in commands:
            if on_command:
                on_command(cmd)
            self.command(cmd)
        self.command("exeCopyConfigFile, Current, Boot")
