"""Rover battery monitoring: the YAML ``batteries`` section -> ArduPilot BATT* params.

Each entry describes what is wired to one Cube power port, e.g.::

    batteries:
    - port: power1               # Cube POWER1 -> BATT_*, POWER2 -> BATT2_*
      sensor: holybro_pm02_v3    # analog voltage/current module
      chemistry: lifepo4         # per-battery alarm voltages
      batteries_in_series: 2     # 12 V batteries feeding the sensed bus
      low_action: hold
      critical_action: hold

Cockpit's battery indicator shows battery 1 (POWER1) from SYS_STATUS, so
nothing on the Cockpit side needs configuring; ArduPilot's "Battery 1 is
low" message reaches Cockpit's alerter.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import ParamFileError

BATTERIES_KEY = "batteries"


@dataclass(frozen=True)
class SensorPreset:
    monitor: int            # BATT_MONITOR
    volt_mult: float        # BATT_VOLT_MULT (nominal; calibrate per unit with a multimeter)
    amp_per_volt: float     # BATT_AMP_PERVLT


SENSORS: dict[str, SensorPreset] = {
    # Holybro spec sheet: voltage divider 18.182, 36.364 A/V. Analog, 2-12S.
    "holybro_pm02_v3": SensorPreset(monitor=4, volt_mult=18.182, amp_per_volt=36.364),
}

# Low / critical alarm voltage per 12 V battery.
CHEMISTRIES: dict[str, tuple[float, float]] = {
    "lifepo4": (12.8, 12.0),      # 12.8 V nominal LiFePO4 (4S)
    "lead_acid": (11.8, 11.5),    # flooded / AGM / gel
}

# ArduRover BATT_FS_LOW_ACT / BATT_FS_CRT_ACT values.
ACTIONS: dict[str, int] = {
    "none": 0,
    "rtl": 1,
    "hold": 2,
    "smartrtl": 3,
    "smartrtl_or_hold": 4,
}

# Cube Orange / Orange+ analog power ports: (voltage pin, current pin).
PORTS: dict[str, tuple[str, int, int]] = {
    "power1": ("BATT", 14, 15),
    "power2": ("BATT2", 13, 4),
}

# Only exist on the autopilot once that port's BATT*_MONITOR is enabled and
# the autopilot has rebooted.
PORT_DEPENDENT_SUFFIXES = ("_VOLT_PIN", "_CURR_PIN", "_VOLT_MULT", "_AMP_PERVLT")


def _choice(
    entry: dict[str, Any], key: str, options: dict[str, Any], where: str, default: str = "",
) -> str:
    value = str(entry.get(key, default)).lower()
    if value not in options:
        raise ParamFileError(f"{where}: {key} must be one of {', '.join(options)} (got {entry.get(key)!r})")
    return value


def battery_params(batteries: Any) -> dict[str, float]:
    """ArduPilot params for the YAML ``batteries`` list.

    Raises:
        ParamFileError: If an entry is malformed.
    """
    if batteries is None:
        return {}
    if not isinstance(batteries, list):
        raise ParamFileError(f"{BATTERIES_KEY} must be a list")

    params: dict[str, float] = {}
    seen: set[str] = set()
    for i, entry in enumerate(batteries):
        where = f"{BATTERIES_KEY}[{i}]"
        if not isinstance(entry, dict):
            raise ParamFileError(f"{where} must be a mapping")
        port = _choice(entry, "port", PORTS, where)
        if port in seen:
            raise ParamFileError(f"{where}: port {port} listed twice")
        seen.add(port)
        prefix, volt_pin, curr_pin = PORTS[port]
        sensor = SENSORS[_choice(entry, "sensor", SENSORS, where)]
        low, critical = CHEMISTRIES[_choice(entry, "chemistry", CHEMISTRIES, where)]
        series = entry.get("batteries_in_series", 1)
        if not isinstance(series, int) or isinstance(series, bool) or series < 1:
            raise ParamFileError(f"{where}: batteries_in_series must be a positive integer")
        capacity = entry.get("capacity_mah", 0)
        if not isinstance(capacity, (int, float)) or isinstance(capacity, bool) or capacity < 0:
            raise ParamFileError(f"{where}: capacity_mah must be a number >= 0")

        params.update({
            f"{prefix}_MONITOR": float(sensor.monitor),
            f"{prefix}_VOLT_PIN": float(volt_pin),
            f"{prefix}_CURR_PIN": float(curr_pin),
            f"{prefix}_VOLT_MULT": float(entry.get("volt_mult", sensor.volt_mult)),
            f"{prefix}_AMP_PERVLT": float(entry.get("amp_per_volt", sensor.amp_per_volt)),
            f"{prefix}_LOW_VOLT": round(low * series, 3),
            f"{prefix}_CRT_VOLT": round(critical * series, 3),
            f"{prefix}_FS_LOW_ACT": float(ACTIONS[_choice(entry, "low_action", ACTIONS, where, "none")]),
            f"{prefix}_FS_CRT_ACT": float(
                ACTIONS[_choice(entry, "critical_action", ACTIONS, where, "none")]
            ),
            # 0 = no remaining-% estimate; set it only when the sensor sees the whole pack's draw.
            f"{prefix}_CAPACITY": float(capacity),
        })
    return dict(sorted(params.items()))


def is_port_dependent(name: str) -> bool:
    """True for params that appear only after a BATT*_MONITOR change and reboot."""
    return any(name.startswith(prefix) and name.endswith(PORT_DEPENDENT_SUFFIXES)
               for prefix, _, _ in PORTS.values())


def sync_scaling_from_device(batteries: Any, device_params: dict[str, float]) -> int:
    """Copy the device's calibrated VOLT_MULT / AMP_PERVLT into the YAML entries.

    A per-unit calibration done on the autopilot then survives the next upload.
    Returns how many values changed.
    """
    if not isinstance(batteries, list):
        return 0
    changed = 0
    for entry in batteries:
        if not isinstance(entry, dict) or str(entry.get("port", "")).lower() not in PORTS:
            continue
        prefix = PORTS[str(entry["port"]).lower()][0]
        sensor = SENSORS.get(str(entry.get("sensor", "")).lower())
        for key, suffix, default in (
            ("volt_mult", "_VOLT_MULT", sensor.volt_mult if sensor else None),
            ("amp_per_volt", "_AMP_PERVLT", sensor.amp_per_volt if sensor else None),
        ):
            device = device_params.get(prefix + suffix)
            if device is None:
                continue
            current = entry.get(key, default)
            if current is None or abs(float(current) - device) > 1e-3:
                entry[key] = round(device, 4)
                changed += 1
    return changed
