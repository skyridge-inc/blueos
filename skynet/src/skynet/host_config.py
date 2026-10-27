"""Host-level BlueOS configuration that has no dedicated REST endpoint.

BlueOS cable-guy runs dnsmasq inside the blueos-core container without
any static-lease support, and blueos-core is recreated on every boot.
DHCP reservations therefore live in a host file that bootstrap
bind-mounts over the container's /etc/dnsmasq.conf (which dnsmasq reads
by default). These helpers render/parse that file and build the shell
commands run on the host via the commander API.
"""

from __future__ import annotations

import base64
import shlex
from typing import Any

DNSMASQ_HOST_PATH = "/etc/blueos/dnsmasq.conf"
DNSMASQ_CONTAINER_PATH = "/etc/dnsmasq.conf"
STARTUP_JSON_PATH = "/root/.config/blueos/bootstrap/startup.json"

_HEADER = (
    "# Managed by skynet — static DHCP reservations for BlueOS dnsmasq servers.\n"
    f"# Bind-mounted over {DNSMASQ_CONTAINER_PATH} in blueos-core via bootstrap startup.json.\n"
)


def render_dnsmasq_conf(reservations: list[dict[str, Any]]) -> str:
    """Render reservations as dnsmasq ``dhcp-host=`` lines."""
    lines = [_HEADER]
    for r in reservations:
        fields = [str(r["mac"]).lower(), str(r["ip"])]
        if r.get("hostname"):
            fields.append(str(r["hostname"]))
        lines.append(f"dhcp-host={','.join(fields)}\n")
    return "".join(lines)


def parse_dnsmasq_conf(text: str) -> list[dict[str, Any]]:
    """Extract ``dhcp-host=<mac>,<ip>[,<hostname>]`` reservations."""
    reservations: list[dict[str, Any]] = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line.startswith("dhcp-host="):
            continue
        fields = [f.strip() for f in line[len("dhcp-host="):].split(",")]
        if len(fields) < 2:
            continue
        entry: dict[str, Any] = {"mac": fields[0].lower(), "ip": fields[1]}
        if len(fields) >= 3 and fields[2]:
            entry["hostname"] = fields[2]
        reservations.append(entry)
    return reservations


def write_file_command(path: str, content: str) -> str:
    """Shell command that writes content to a root-owned host file.

    Content is base64-encoded so it survives shell quoting intact.
    """
    encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
    return f"echo {encoded} | base64 -d | sudo tee {shlex.quote(path)} >/dev/null"


_ENSURE_BIND_SCRIPT = f"""
import json, shutil, time
p = {STARTUP_JSON_PATH!r}
d = json.load(open(p))
binds = d["core"].setdefault("binds", {{}})
want = {{"bind": {DNSMASQ_CONTAINER_PATH!r}, "mode": "ro"}}
if binds.get({DNSMASQ_HOST_PATH!r}) == want:
    print("unchanged")
else:
    shutil.copy2(p, p + ".bak-" + time.strftime("%Y%m%d%H%M%S"))
    binds[{DNSMASQ_HOST_PATH!r}] = want
    s = json.dumps(d, indent=4)
    json.loads(s)
    open(p, "w").write(s + "\\n")
    print("changed")
"""


def ensure_bind_command() -> str:
    """Shell command that idempotently adds the dnsmasq.conf bind to blueos-core.

    Backs up startup.json before modifying it. Prints ``changed`` or
    ``unchanged`` on stdout.
    """
    return f"sudo python3 -c {shlex.quote(_ENSURE_BIND_SCRIPT)}"
