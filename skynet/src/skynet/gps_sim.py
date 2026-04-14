"""GPS/heading simulator for hardware-in-the-loop ArduRover."""

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

# Required sim values keyed by the param names actually on the autopilot.
# ArduPilot 4.4+ renamed GPS_TYPE → GPS1_TYPE and GPS_TYPE2 → GPS2_TYPE.
# resolve_sim_params() picks the right names at runtime.
_SIM_VALUES_CANONICAL: dict[str, float] = {
    # GPS source — MAVLink-injected, no secondary.
    "GPS_TYPE": 14,
    "GPS_TYPE2": 0,
    # EKF sources — GPS for position/velocity/yaw, baro for altitude.
    "AHRS_EKF_TYPE": 3,
    "EK3_SRC1_POSXY": 3,
    "EK3_SRC1_VELXY": 3,
    "EK3_SRC1_POSZ": 1,
    "EK3_SRC1_YAW": 2,
    # Disable all compasses so the EKF uses ONLY our GPS_INPUT yaw.
    # Without this, the internal compass votes and disagrees with the
    # static-heading sim, tripping EKF failsafe on a ~1s cycle.
    "COMPASS_USE": 0,
    "COMPASS_USE2": 0,
    "COMPASS_USE3": 0,
    # Bench-safe failsafe relaxations — we have no RC, no GCS heartbeat
    # guarantee, and the sim may legitimately show zero motion while
    # under throttle (before the autopilot acts on servo commands).
    "ARMING_CHECK": 0,        # Skip pre-arm checks entirely.
    "FS_EKF_ACTION": 0,       # 0=disabled in Rover; 1 would switch to Hold.
    "FS_CRASH_CHECK": 0,      # Don't auto-disarm for "no motion under throttle".
    "FS_THR_ENABLE": 0,       # Don't trip on missing RC receiver.
    "FS_GCS_ENABLE": 0,       # Don't trip on GCS heartbeat gaps.
    # Rover auto-disarms after DISARM_DELAY seconds of near-zero throttle.
    # With the sim idle waiting for mission start, this trips every cycle.
    "DISARM_DELAY": 0,        # 0 disables the idle auto-disarm entirely.
    # MIS_RESTART=0 lets us place the mission pointer manually without
    # the autopilot resetting it on every arm. A fresh upload in phase 2
    # already resets the mission state, so restart-on-arm isn't needed.
    "MIS_RESTART": 0,
    # AUTO_KICKSTART: if > 0, ArduRover requires a physical push (acceleration
    # spike) before it begins driving in AUTO mode. On a stationary bench sim
    # this push never happens and the rover sits forever. Force 0 to disable.
    "AUTO_KICKSTART": 0,
}

# Param renames between firmware versions: (old_name, new_name).
_PARAM_ALIASES: list[tuple[str, str]] = [
    ("GPS_TYPE", "GPS1_TYPE"),
    ("GPS_TYPE2", "GPS2_TYPE"),
]


def resolve_sim_params(autopilot_params: dict[str, float]) -> dict[str, float]:
    """Return sim-required param dict with names matched to this autopilot.

    For each param in _SIM_VALUES_CANONICAL, check whether the canonical
    name or its alias exists on the autopilot and use whichever is found.
    """
    alias_map: dict[str, str] = {}
    for old, new in _PARAM_ALIASES:
        alias_map[old] = new
        alias_map[new] = old

    resolved: dict[str, float] = {}
    for name, value in _SIM_VALUES_CANONICAL.items():
        if name in autopilot_params:
            resolved[name] = value
        elif name in alias_map and alias_map[name] in autopilot_params:
            resolved[alias_map[name]] = value
        else:
            logger.warning(
                "Sim param %s (and alias %s) not found on autopilot",
                name,
                alias_map.get(name, "none"),
            )
    return resolved


# Legacy constant — tests and dry-run display reference this.
SIM_PARAMS = _SIM_VALUES_CANONICAL

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


# -------------------- AckermannModel --------------------


@dataclass
class AckermannModel:
    """Bicycle-model kinematics for Ackermann (steering + throttle) rovers.

    SERVO1_FUNCTION=26 (GroundSteering) controls steering angle.
    SERVO3_FUNCTION=70 (Throttle) controls forward speed.
    """

    start_lat: float
    start_lon: float
    start_heading_deg: float = 0.0
    max_speed_mps: float = 2.0 * MPH_TO_MPS
    wheelbase_m: float = 0.5
    max_steer_angle_deg: float = 30.0

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
        self, dt: float, steer_norm: float, throttle_norm: float
    ) -> tuple[float, float, float, float, float]:
        """Advance the model by dt seconds.

        Args:
            steer_norm: Normalized steering input [-1, +1].
                        Positive = turn right.
            throttle_norm: Normalized throttle input [-1, +1].
                           Positive = forward.

        Returns (lat, lon, heading_deg, vn, ve).
        """
        steer = max(-1.0, min(1.0, steer_norm))
        throttle = max(-1.0, min(1.0, throttle_norm))

        v = self.max_speed_mps * throttle
        steer_angle_rad = math.radians(self.max_steer_angle_deg * steer)

        if abs(steer_angle_rad) > 1e-6:
            omega = v * math.tan(steer_angle_rad) / self.wheelbase_m
        else:
            omega = 0.0

        self.heading_deg = (self.heading_deg + math.degrees(omega * dt)) % 360.0
        hdg_rad = math.radians(self.heading_deg)
        vn = v * math.cos(hdg_rad)
        ve = v * math.sin(hdg_rad)

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
        # If a leftover sidecar exists, prefer its contents as the
        # authoritative originals. A previous crashed run may have left
        # the autopilot in sim mode, in which case the current values on
        # the autopilot ARE the sim values, not the real pre-sim state.
        prior_originals: dict[str, float] = {}
        if self.sidecar.exists():
            logger.warning(
                "Leftover sidecar found at %s — loading its originals and "
                "deleting it before fresh run",
                self.sidecar,
            )
            try:
                prior_originals = load_param_file(
                    self.sidecar, include_calibration=True
                )
            except Exception as e:
                logger.warning("Could not read leftover sidecar: %s", e)
                prior_originals = {}
            self.sidecar.unlink()

        all_params = fetch_all_params(self.conn)

        # Resolve canonical names to whatever this firmware actually uses.
        self.sim_params = resolve_sim_params(all_params)

        self._originals = {}
        for name in self.sim_params:
            # Prefer the sidecar's value (real pre-sim state) over the
            # current autopilot value (may already be a sim override).
            if name in prior_originals:
                self._originals[name] = prior_originals[name]
            elif name in all_params:
                self._originals[name] = all_params[name]

        # Write fresh sidecar BEFORE any mutation.
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

        # Provide a plausible GPS time. ArduPilot's GPS health check
        # rejects fixes with time_week == 0. Use real wall-clock time
        # converted to GPS epoch (1980-01-06 UTC) minus leap seconds.
        now = time.time()
        gps_epoch = 315964800.0  # 1980-01-06 00:00:00 UTC
        leap_seconds = 18         # GPS vs UTC offset as of 2017+
        gps_time = now - gps_epoch + leap_seconds
        time_week = int(gps_time // (7 * 86400))
        time_week_ms = int((gps_time % (7 * 86400)) * 1000)

        self.conn.mav.gps_input_send(
            time_usec,
            0,  # gps_id
            0,  # ignore_flags
            time_week_ms,
            time_week,
            # MAV_GPS_FIX_TYPE_RTK_FIXED (6). ArduPilot's EKF3 requires
            # an RTK-quality fix to trust GPS yaw — with a plain 3D fix
            # (3) the nav controller refuses to engage even though
            # position is accepted. The sim's GPS is a perfect source,
            # so reporting RTK_FIXED is accurate.
            6,
            lat,
            lon,
            0.0,  # alt
            0.5,  # hdop — tighter for RTK
            0.8,  # vdop
            self._last_vn,
            self._last_ve,
            0.0,  # vd
            0.05,  # speed_accuracy — tighter for RTK
            0.02,  # horiz_accuracy — 2cm like real RTK
            0.05,  # vert_accuracy
            20,   # satellites_visible
            yaw_cdeg,
        )


# -------------------- StopWatcher --------------------


class StopWatcher:
    """Combines DISARM, mission-reached, duration, and signal triggers."""

    # Ignore disarm events within this many seconds of the first arm.
    # Gives the EKF time to converge on the sim's GPS data before treating
    # a transient arm/disarm cycle as a real mission-end disarm.
    MIN_ARMED_SECONDS = 5.0

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
        self._armed_at: float | None = None
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
            if not self.armed_latch:
                self.armed_latch = True
                self._armed_at = time.monotonic()
        elif self.armed_latch:
            elapsed = time.monotonic() - (self._armed_at or 0.0)
            if elapsed >= self.MIN_ARMED_SECONDS:
                self.trip("DISARM")
            else:
                # Transient arm/disarm — reset the latch and keep running.
                self.armed_latch = False
                self._armed_at = None

    def observe_mission_reached(self, seq: int) -> None:
        if seq == self.last_mission_seq:
            self.trip(f"mission reached seq {seq}")

    def check_duration(self) -> None:
        if self.duration_seconds is None:
            return
        if time.monotonic() - self._start_monotonic > self.duration_seconds:
            self.trip(f"duration {self.duration_seconds}s expired")


# -------------------- Drive type detection --------------------

DRIVE_SKID_STEER = "skid_steer"
DRIVE_ACKERMANN = "ackermann"


def detect_drive_type(params: dict[str, float]) -> str:
    """Detect the rover's drive type from servo function params.

    Returns DRIVE_SKID_STEER or DRIVE_ACKERMANN.
    Raises FrameMismatchError if the configuration is unrecognized.
    """
    from .exceptions import FrameMismatchError

    frame_class = int(params.get("FRAME_CLASS", -1))
    s1 = int(params.get("SERVO1_FUNCTION", -1))
    s3 = int(params.get("SERVO3_FUNCTION", -1))

    if frame_class == 2 and s1 == 73 and s3 == 74:
        return DRIVE_SKID_STEER

    if frame_class in (1, 2) and s1 == 26 and s3 == 70:
        return DRIVE_ACKERMANN

    raise FrameMismatchError(
        f"Unrecognized rover configuration: FRAME_CLASS={frame_class}, "
        f"SERVO1_FUNCTION={s1}, SERVO3_FUNCTION={s3}. Expected skid-steer "
        f"(73/74) or Ackermann steering+throttle (26/70). Refusing to run."
    )


def validate_skid_steer(params: dict[str, float]) -> None:
    """Legacy wrapper — prefer detect_drive_type."""
    detect_drive_type(params)


# -------------------- Stream subscription --------------------


def _set_message_interval(conn: Any, msg_id: int, rate_hz: float) -> None:
    interval_us = int(1_000_000 / rate_hz)
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL,
        0,
        float(msg_id),
        float(interval_us),
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def request_servo_output_stream(conn: Any, rate_hz: float = 10.0) -> None:
    """Request SERVO_OUTPUT_RAW at the given rate via MESSAGE_INTERVAL."""
    _set_message_interval(
        conn, mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW, rate_hz
    )


def request_diagnostic_streams(conn: Any) -> None:
    """Request diagnostic messages at 1 Hz each.

    Subscribes to:
    - MISSION_CURRENT: which waypoint is the active target
    - NAV_CONTROLLER_OUTPUT: target/nav bearing, wp_dist, xtrack_error
    - VFR_HUD: commanded throttle %, groundspeed — reveals whether the
      autopilot is actually trying to drive
    - GLOBAL_POSITION_INT: autopilot's view of its own position (for
      checking EKF trust of our GPS_INPUT)
    - EKF_STATUS_REPORT: innovations and flags — reveals silent EKF
      rejection of GPS yaw or other data
    """
    for msg_id in (
        mavutil.mavlink.MAVLINK_MSG_ID_MISSION_CURRENT,
        mavutil.mavlink.MAVLINK_MSG_ID_NAV_CONTROLLER_OUTPUT,
        mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD,
        mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_EKF_STATUS_REPORT,
    ):
        _set_message_interval(conn, msg_id, 1.0)


# MAV_SEVERITY levels. STATUSTEXT with severity <= WARNING (4) is
# surfaced to the user by default.
STATUSTEXT_SEVERITY_EMERGENCY = 0
STATUSTEXT_SEVERITY_ALERT = 1
STATUSTEXT_SEVERITY_CRITICAL = 2
STATUSTEXT_SEVERITY_ERROR = 3
STATUSTEXT_SEVERITY_WARNING = 4
STATUSTEXT_SEVERITY_NOTICE = 5
STATUSTEXT_SEVERITY_INFO = 6
STATUSTEXT_SEVERITY_DEBUG = 7


def severity_label(severity: int) -> str:
    return {
        0: "EMERGENCY", 1: "ALERT", 2: "CRITICAL", 3: "ERROR",
        4: "WARNING", 5: "NOTICE", 6: "INFO", 7: "DEBUG",
    }.get(severity, f"SEV{severity}")


# ArduRover custom_mode values (flight mode)
ROVER_MODE_NAMES: dict[int, str] = {
    0: "MANUAL",
    1: "ACRO",
    3: "STEERING",
    4: "HOLD",
    5: "LOITER",
    6: "FOLLOW",
    7: "SIMPLE",
    10: "AUTO",
    11: "RTL",
    12: "SMART_RTL",
    15: "GUIDED",
    16: "INITIALISING",
}


def rover_mode_name(custom_mode: int) -> str:
    return ROVER_MODE_NAMES.get(int(custom_mode), f"mode {custom_mode}")


def start_mission(conn: Any) -> None:
    """Send MAV_CMD_MISSION_START to tell the autopilot to run the mission."""
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_MISSION_START,
        0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def set_rover_mode(conn: Any, custom_mode: int) -> None:
    """Set the autopilot's flight mode via MAV_CMD_DO_SET_MODE.

    For ArduRover, pass custom_mode = 10 for AUTO, 4 for HOLD, etc.
    """
    base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
    conn.mav.set_mode_send(conn.target_system, base_mode, custom_mode)


def set_target_groundspeed(conn: Any, speed_mps: float) -> None:
    """Send MAV_CMD_DO_CHANGE_SPEED to force a target ground speed.

    Overrides WP_SPEED / CRUISE_SPEED for the current mission. Useful as
    a belt-and-suspenders fix when the vehicle's own speed params might
    be zero or misconfigured.
    """
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED,
        0,
        1.0,          # param1: 1 = groundspeed
        float(speed_mps),  # param2: target speed m/s
        -1.0,         # param3: throttle % (-1 = no change)
        0.0,
        0.0,
        0.0,
        0.0,
    )


# Vehicle params we want to read and warn about at sim start.
SPEED_PARAMS_TO_CHECK = (
    "CRUISE_SPEED",
    "CRUISE_THROTTLE",
    "WP_SPEED",
)


def warn_on_zero_speed_params(
    params: dict[str, float],
    printer: Callable[[str], None],
) -> list[str]:
    """Check CRUISE_SPEED / CRUISE_THROTTLE / WP_SPEED for zero values.

    Returns the list of param names that are zero. Calls `printer` with a
    warning line for each. The caller can use the returned list to decide
    whether to force a target speed via DO_CHANGE_SPEED.
    """
    zeros = [
        name for name in SPEED_PARAMS_TO_CHECK
        if name in params and float(params[name]) == 0.0
    ]
    for name in zeros:
        printer(
            f"{name}=0 on autopilot — speed controller will not command "
            f"throttle. Will force target speed via DO_CHANGE_SPEED."
        )
    return zeros


def set_current_mission_seq(conn: Any, seq: int) -> None:
    """Set the current active mission item via MISSION_SET_CURRENT."""
    conn.mav.mission_set_current_send(
        conn.target_system,
        conn.target_component,
        seq,
    )


def deduplicate_mission(
    mission: list[tuple[float, float]],
    tolerance_m: float = 0.5,
) -> list[tuple[float, float]]:
    """Collapse consecutive duplicate waypoints into a single entry.

    ArduRover's L1 navigation controller follows the line segment from
    the previous waypoint to the current one. If two consecutive
    waypoints are at the same lat/lon (e.g. home == WP1, which is the
    default from `nav_plan`), the segment has zero length, the nav
    controller cannot compute a bearing, and the rover refuses to drive.

    Returns a new list where any entry within `tolerance_m` of its
    immediate predecessor is dropped.
    """
    if len(mission) < 2:
        return list(mission)

    m_per_deg_lat = 111_320.0
    out: list[tuple[float, float]] = [mission[0]]
    for lat, lon in mission[1:]:
        prev_lat, prev_lon = out[-1]
        cos_lat = math.cos(math.radians(prev_lat))
        m_per_deg_lon = 111_320.0 * cos_lat
        dy = (lat - prev_lat) * m_per_deg_lat
        dx = (lon - prev_lon) * m_per_deg_lon
        if math.hypot(dx, dy) < tolerance_m:
            continue  # duplicate — skip
        out.append((lat, lon))
    return out


def offset_spawn_behind_waypoint(
    here_lat: float,
    here_lon: float,
    next_lat: float,
    next_lon: float,
    distance_m: float = 5.0,
) -> tuple[float, float]:
    """Return a lat/lon offset `distance_m` behind `here` relative to `next`.

    Used so the simulated rover spawns some meters before the first target
    waypoint, giving the autopilot's waypoint-reached logic a non-zero
    distance to close. Without this the mission state machine gets stuck
    at wp_dist=0 (no hysteresis transition) and the rover never moves.

    If `here` and `next` are essentially identical, falls back to offsetting
    due south so the caller still gets a distinct spawn lat/lon.
    """
    cos_lat = math.cos(math.radians(here_lat))
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * cos_lat if cos_lat != 0 else 111_320.0

    dy_m = (next_lat - here_lat) * m_per_deg_lat  # north
    dx_m = (next_lon - here_lon) * m_per_deg_lon  # east
    dist_m = math.hypot(dx_m, dy_m)

    if dist_m < 0.1:
        # Degenerate next == here; default to offsetting south.
        return (here_lat - distance_m / m_per_deg_lat, here_lon)

    # Unit vector from here toward next.
    ux = dx_m / dist_m
    uy = dy_m / dist_m

    # Place spawn BEHIND here (opposite the toward-next direction).
    offset_x_m = -ux * distance_m
    offset_y_m = -uy * distance_m

    return (
        here_lat + offset_y_m / m_per_deg_lat,
        here_lon + offset_x_m / m_per_deg_lon,
    )


def reboot_autopilot(conn: Any) -> None:
    """Send MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN to reboot the autopilot."""
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_PREFLIGHT_REBOOT_SHUTDOWN,
        0,
        1.0,  # param1 = 1 → autopilot reboot
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
    )


def read_autopilot_yaw(conn: Any, timeout: float = 3.0) -> float:
    """Read the autopilot's current EKF yaw (degrees) from the ATTITUDE msg.

    Returns 0.0 if no ATTITUDE is received within `timeout`. The caller
    should log a warning in that case.
    """
    msg = conn.recv_match(type="ATTITUDE", blocking=True, timeout=timeout)
    if msg is None:
        logger.warning(
            "No ATTITUDE received within %ss — starting sim at heading 0°",
            timeout,
        )
        return 0.0
    # msg.yaw is radians, convention -pi..pi with 0 = north, positive = east (CW)
    yaw_deg = math.degrees(msg.yaw) % 360.0
    return yaw_deg


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
