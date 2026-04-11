"""Skid-steer GPS/heading simulator for hardware-in-the-loop ArduRover."""

from __future__ import annotations

import logging
import math
import signal
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from pymavlink import mavutil

from .config import load_param_file, save_param_file
from .exceptions import GpsSimError
from .mission_planning import to_latlon, to_xy
from .params import fetch_all_params, write_params

logger = logging.getLogger(__name__)

# Required params and their sim values.
SIM_PARAMS: dict[str, float] = {
    "GPS_TYPE": 14,
    "GPS_TYPE2": 0,
    "AHRS_EKF_TYPE": 3,
    "EK3_SRC1_POSXY": 3,
    "EK3_SRC1_VELXY": 3,
    "EK3_SRC1_POSZ": 1,
    "EK3_SRC1_YAW": 2,
}

# Default sidecar directory.
SIDECAR_DIR = Path.home() / ".config" / "skynet"

# Conversion constants.
MPH_TO_MPS = 0.44704


# -------------------- SkidSteerModel --------------------


@dataclass
class SkidSteerModel:
    """Pure kinematic differential-drive model.

    State is (lat, lon, heading_deg). The local frame origin is captured
    at construction so every step integrates in the same equirectangular
    tangent plane as `mission_planning.to_xy`.
    """

    start_lat: float
    start_lon: float
    start_heading_deg: float = 0.0
    max_speed_mps: float = 2.0 * MPH_TO_MPS
    track_width_m: float = 0.5

    lat: float = field(init=False)
    lon: float = field(init=False)
    heading_deg: float = field(init=False)
    _x_m: float = field(init=False, default=0.0)
    _y_m: float = field(init=False, default=0.0)
    _origin: tuple[float, float] = field(init=False)

    def __post_init__(self) -> None:
        self.lat = self.start_lat
        self.lon = self.start_lon
        self.heading_deg = self.start_heading_deg % 360.0
        self._origin = (self.start_lat, self.start_lon)

    def step(
        self, dt: float, left_norm: float, right_norm: float
    ) -> tuple[float, float, float, float, float]:
        """Advance the model by dt seconds.

        Returns (lat, lon, heading_deg, vn, ve).
        """
        left = max(-1.0, min(1.0, left_norm))
        right = max(-1.0, min(1.0, right_norm))

        v = self.max_speed_mps * (left + right) / 2.0
        omega = (
            self.max_speed_mps * (right - left) / self.track_width_m
        )  # rad/s

        self.heading_deg = (self.heading_deg + math.degrees(omega * dt)) % 360.0
        hdg_rad = math.radians(self.heading_deg)
        vn = v * math.cos(hdg_rad)  # north
        ve = v * math.sin(hdg_rad)  # east

        # to_xy uses x=east, y=north — match that convention.
        self._x_m += ve * dt
        self._y_m += vn * dt

        (self.lat, self.lon) = to_latlon(
            [(self._x_m, self._y_m)], self._origin
        )[0]
        return (self.lat, self.lon, self.heading_deg, vn, ve)


# -------------------- ServoNormalizer --------------------


class ServoNormalizer:
    """Map raw PWM microseconds to [-1, +1] using SERVOn_MIN/TRIM/MAX."""

    _warned: set[int] = set()

    def __init__(
        self,
        channel: int,
        params: dict[str, float],
    ) -> None:
        self.channel = channel
        min_key = f"SERVO{channel}_MIN"
        trim_key = f"SERVO{channel}_TRIM"
        max_key = f"SERVO{channel}_MAX"

        missing = [k for k in (min_key, trim_key, max_key) if k not in params]
        if missing:
            if channel not in ServoNormalizer._warned:
                logger.warning(
                    "SERVO%d params missing (%s); using defaults 1000/1500/2000",
                    channel,
                    ",".join(missing),
                )
                ServoNormalizer._warned.add(channel)
            self.min_pwm = 1000.0
            self.trim_pwm = 1500.0
            self.max_pwm = 2000.0
        else:
            self.min_pwm = float(params[min_key])
            self.trim_pwm = float(params[trim_key])
            self.max_pwm = float(params[max_key])

    def normalize(self, raw_pwm: float) -> float:
        if raw_pwm >= self.max_pwm:
            return 1.0
        if raw_pwm <= self.min_pwm:
            return -1.0
        if raw_pwm >= self.trim_pwm:
            return (raw_pwm - self.trim_pwm) / (self.max_pwm - self.trim_pwm)
        return (raw_pwm - self.trim_pwm) / (self.trim_pwm - self.min_pwm)


# -------------------- SimParamContext --------------------


def device_slug(device: str) -> str:
    """Slugify a device string for use in a sidecar filename."""
    return "".join(c if c.isalnum() else "_" for c in device)


def sidecar_path(device: str, sidecar_dir: Path | None = None) -> Path:
    base = sidecar_dir or SIDECAR_DIR
    return base / f"sim_restore_{device_slug(device)}.param"


class SimParamContext:
    """Save required autopilot params to a sidecar, write sim values, restore on exit."""

    def __init__(
        self,
        conn: Any,
        device: str,
        *,
        sim_params: dict[str, float] | None = None,
        sidecar_dir: Path | None = None,
    ) -> None:
        self.conn = conn
        self.device = device
        self.sim_params = dict(sim_params or SIM_PARAMS)
        self.sidecar = sidecar_path(device, sidecar_dir)
        self._originals: dict[str, float] | None = None
        self._prev_sigint: Any = None
        self._prev_sigterm: Any = None

    def __enter__(self) -> "SimParamContext":
        if self.sidecar.exists():
            raise GpsSimError(
                f"Leftover sidecar file detected: {self.sidecar}\n"
                f"A previous `skynet nav sim` run likely crashed. Restore "
                f"the autopilot with:\n"
                f"  skynet misc write {self.sidecar} --yes --include-calibration\n"
                f"Then delete the sidecar and retry."
            )

        all_params = fetch_all_params(self.conn)
        self._originals = {}
        for name in self.sim_params:
            if name in all_params:
                self._originals[name] = all_params[name]
            else:
                logger.warning(
                    "Required param %s not found on autopilot; skipping",
                    name,
                )

        # Write sidecar BEFORE any mutation.
        save_param_file(
            self.sidecar, self._originals, include_calibration=True
        )

        # Install signal handlers so Ctrl+C still runs restore.
        self._prev_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        try:
            self._prev_sigterm = signal.signal(
                signal.SIGTERM, self._signal_handler
            )
        except ValueError:
            # Not in main thread — skip SIGTERM.
            self._prev_sigterm = None

        # Apply sim values.
        write_params(
            self.conn,
            {k: v for k, v in self.sim_params.items() if k in self._originals},
            include_calibration=True,
        )

        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        # Always restore handlers first.
        if self._prev_sigint is not None:
            signal.signal(signal.SIGINT, self._prev_sigint)
        if self._prev_sigterm is not None:
            signal.signal(signal.SIGTERM, self._prev_sigterm)

        if self._originals is None:
            return

        # Restore originals.
        write_params(self.conn, self._originals, include_calibration=True)

        # Only delete sidecar after successful restore.
        try:
            self.sidecar.unlink()
        except FileNotFoundError:
            pass

    def _signal_handler(self, signum: int, frame: Any) -> None:
        raise KeyboardInterrupt(f"Signal {signum} received")


# -------------------- GpsInputEmitter --------------------


class GpsInputEmitter:
    """Emits GPS_INPUT messages at a configured rate from a SkidSteerModel."""

    def __init__(
        self,
        conn: Any,
        model: SkidSteerModel,
        rate_hz: float = 5.0,
    ) -> None:
        self.conn = conn
        self.model = model
        if rate_hz < 1:
            logger.warning("rate_hz=%s clamped to 1", rate_hz)
            rate_hz = 1
        elif rate_hz > 20:
            logger.warning("rate_hz=%s clamped to 20", rate_hz)
            rate_hz = 20
        self.rate_hz = rate_hz
        self._start_ns = time.monotonic_ns()
        self._last_vn = 0.0
        self._last_ve = 0.0

    def set_velocity(self, vn: float, ve: float) -> None:
        self._last_vn = vn
        self._last_ve = ve

    def emit(self) -> None:
        time_usec = (time.monotonic_ns() - self._start_ns) // 1000
        lat = int(round(self.model.lat * 1e7))
        lon = int(round(self.model.lon * 1e7))
        yaw_cdeg = int(round(self.model.heading_deg * 100)) % 36000
        if yaw_cdeg == 0:
            yaw_cdeg = 1  # ArduPilot treats 0 as "no yaw"
        self.conn.mav.gps_input_send(
            time_usec,
            0,  # gps_id
            0,  # ignore_flags
            0,  # time_week_ms
            0,  # time_week
            3,  # fix_type = 3D
            lat,
            lon,
            0.0,  # alt
            0.8,  # hdop
            1.0,  # vdop
            self._last_vn,
            self._last_ve,
            0.0,  # vd
            0.1,  # speed_accuracy
            0.1,  # horiz_accuracy
            0.3,  # vert_accuracy
            14,  # satellites_visible
            yaw_cdeg,
        )


# -------------------- StopWatcher --------------------


class StopWatcher:
    """Combines DISARM, mission-reached, duration, and signal triggers."""

    def __init__(
        self,
        last_mission_seq: int,
        *,
        duration_seconds: float | None = None,
    ) -> None:
        self.last_mission_seq = last_mission_seq
        self.duration_seconds = duration_seconds
        self.armed_latch = False
        self.should_stop = False
        self.stop_reason: str | None = None
        self._start_monotonic: float = 0.0
        self._prev_sigint: Any = None
        self._prev_sigterm: Any = None

    def __enter__(self) -> "StopWatcher":
        self._start_monotonic = time.monotonic()
        self._prev_sigint = signal.signal(signal.SIGINT, self._sig)
        try:
            self._prev_sigterm = signal.signal(signal.SIGTERM, self._sig)
        except ValueError:
            self._prev_sigterm = None
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._prev_sigint is not None:
            signal.signal(signal.SIGINT, self._prev_sigint)
        if self._prev_sigterm is not None:
            signal.signal(signal.SIGTERM, self._prev_sigterm)

    def _sig(self, signum: int, frame: Any) -> None:
        self.trip(f"signal {signum}")

    def trip(self, reason: str) -> None:
        if not self.should_stop:
            self.should_stop = True
            self.stop_reason = reason

    def observe_heartbeat(self, base_mode: int) -> None:
        armed = bool(
            base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        )
        if armed:
            self.armed_latch = True
        elif self.armed_latch:
            self.trip("DISARM")

    def observe_mission_reached(self, seq: int) -> None:
        if seq == self.last_mission_seq:
            self.trip(f"mission reached seq {seq}")

    def check_duration(self) -> None:
        if self.duration_seconds is None:
            return
        if time.monotonic() - self._start_monotonic > self.duration_seconds:
            self.trip(f"duration {self.duration_seconds}s expired")


# -------------------- Frame validation --------------------


def validate_skid_steer(params: dict[str, float]) -> None:
    """Raise FrameMismatchError if params do not describe a skid-steer rover."""
    from .exceptions import FrameMismatchError

    frame_class = int(params.get("FRAME_CLASS", -1))
    s1 = int(params.get("SERVO1_FUNCTION", -1))
    s3 = int(params.get("SERVO3_FUNCTION", -1))
    if frame_class != 2 or s1 != 73 or s3 != 74:
        raise FrameMismatchError(
            f"Expected skid-steer rover (FRAME_CLASS=2, SERVO1_FUNCTION=73, "
            f"SERVO3_FUNCTION=74), got FRAME_CLASS={frame_class}, "
            f"SERVO1_FUNCTION={s1}, SERVO3_FUNCTION={s3}. Refusing to run."
        )


# -------------------- Stream subscription --------------------


def request_servo_output_stream(conn: Any, rate_hz: float = 10.0) -> None:
    """Request SERVO_OUTPUT_RAW at the given rate via MESSAGE_INTERVAL."""
    interval_us = int(1_000_000 / rate_hz)
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        float(mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW),
        float(interval_us),
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def wait_for_servo_output(conn: Any, timeout: float = 2.0) -> Any:
    """Wait up to `timeout` for a SERVO_OUTPUT_RAW; raise GpsSimError on failure."""
    msg = conn.recv_match(
        type="SERVO_OUTPUT_RAW", blocking=True, timeout=timeout
    )
    if msg is None:
        raise GpsSimError(
            f"No SERVO_OUTPUT_RAW received within {timeout}s. Check that "
            f"MESSAGE_INTERVAL requests are accepted by the autopilot."
        )
    return msg
