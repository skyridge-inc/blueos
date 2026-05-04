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
    # EKF sources — GPS for position/velocity, baro for altitude,
    # and GSF (Gaussian Sum Filter) for yaw.
    #
    # Yaw chain for a bench-sim on this hardware:
    # - GPS yaw (EK3_SRC1_YAW=2) does NOT work — AP_GPS_MAV does not
    #   send the "GPS config data" capability, EKF waits forever.
    # - Compass yaw (EK3_SRC1_YAW=1) does NOT work — the operator's
    #   rover has all three compasses disabled (relies on UM982 CAN
    #   yaw normally), and forcing COMPASS_USE=1 on an uncalibrated
    #   internal compass gets rejected by the EKF health check
    #   (compass_var stays at 0 = never fused).
    # - GSF (EK3_SRC1_YAW=8) IS the canonical no-compass yaw source in
    #   ArduPilot. It runs 5 parallel EKFs with different initial yaws
    #   and picks the one that best explains IMU + GPS velocity data.
    #
    # EK3_SRC_OPTIONS bit 1 (value 2) enables FuseGSFYaw so the main
    # EKF uses the GSF estimate.
    "AHRS_EKF_TYPE": 3,
    "EK3_SRC1_POSXY": 3,  # GPS horizontal position
    "EK3_SRC1_VELXY": 3,  # GPS horizontal velocity
    "EK3_SRC1_POSZ": 1,   # baro for vertical
    "EK3_SRC1_YAW": 6,    # ExternalNav (yaw via VISION_POSITION_ESTIMATE)
    # GSF (EK3_SRC1_YAW=8) was tried but deadlocks: GSF needs motion to
    # converge on yaw, motion needs nav controller, nav controller needs
    # yaw-aligned EKF. With no compass and no GPS-yaw fusion path, the
    # only escape is to inject yaw via a dedicated channel. The
    # AP_VisualOdom_MAV backend (VISO_TYPE=1) consumes
    # VISION_POSITION_ESTIMATE messages and feeds them straight to the
    # EKF as ExternalNav.
    "VISO_TYPE": 1,
    # VISO_TYPE=1 alone is necessary but not sufficient. Without
    # explicit delay/noise params, the EKF's "is this vision data
    # trustworthy?" pre-check fails silently and yaw alignment never
    # completes (no "EKF3 IMU yaw aligned" message in the autopilot
    # log). These three values tell the EKF the vision source has
    # 50 ms of pipeline delay, ~10 cm position noise, and ~3° yaw
    # noise — all reasonable defaults for a simulated source.
    "VISO_DELAY_MS": 50,
    "VISO_POS_M_NSE": 0.1,
    "VISO_YAW_M_NSE": 0.05,
    # Disable all GPS alignment pre-checks. The EKF default requires the
    # GPS driver to populate sat count, HDop, position error, speed
    # error, and yaw error fields — but the AP_GPS_MAV driver doesn't
    # fully populate all of these, so "EKF3 waiting for GPS config
    # data" is logged forever and the EKF never aligns, leaving flags
    # stuck at 167 (CONST_POS_MODE). We know our sim GPS is good, so
    # we skip the pre-checks entirely.
    "EK3_GPS_CHECK": 0,
    # Explicit GPS measurement delay. Default is 0 meaning "auto", but
    # AP_GPS_MAV's auto-detect can fail over a laggy tunnel; 50 ms is
    # a safe pessimistic value for a NetBird-proxied link.
    "GPS_DELAY_MS": 50,
    # COMPASS_USE/USE2/USE3 intentionally not overridden. The operator's
    # rover has compasses disabled; we don't fight that configuration
    # because GSF gives us yaw without needing any compass.
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
    # LOG_FILE_DSRMROT=1 makes the autopilot rotate (seal + start fresh) the
    # dataflash log on disarm. Default is 0 — disarm leaves the log open,
    # which means LOG_REQUEST_LIST returns only previously-sealed logs and
    # the active session's data is invisible. The auto-download path on
    # AUTO-fail relies on the disarm sealing the freeze log so we can pull
    # it. Without this, we'd download a stale pre-sim log.
    "LOG_FILE_DSRMROT": 1,
    # LOG_DISARMED=1 keeps the log writer running between boot and first
    # arm. Captures the EKF warmup and AUTO-engage handshake, both of which
    # are forensically interesting on a freeze.
    "LOG_DISARMED": 1,
}

# Param renames between firmware versions: (old_name, new_name).
_PARAM_ALIASES: list[tuple[str, str]] = [
    ("GPS_TYPE", "GPS1_TYPE"),
    ("GPS_TYPE2", "GPS2_TYPE"),
    # ArduPilot 4.4+ also renamed the per-GPS delay params.
    ("GPS_DELAY_MS", "GPS1_DELAY_MS"),
    ("GPS_DELAY_MS2", "GPS2_DELAY_MS"),
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

    def record_late_originals(self, originals: dict[str, float]) -> None:
        """Merge originals discovered after a post-reboot re-fetch into
        the sidecar and the in-memory restore set.

        Needed because some params (notably `VISO_*` and occasionally
        `DISARM_DELAY`) only materialise once `VISO_TYPE=1` has been
        persisted across a reboot — they can't be captured in the
        first `__enter__` pass. Without this, a second-pass write of
        those params would leak past sim context exit.
        """
        if self._originals is None:
            self._originals = {}
        for name, value in originals.items():
            # Don't overwrite — the earliest observed value is the real
            # pre-sim state.
            self._originals.setdefault(name, value)
        save_param_file(
            self.sidecar, self._originals, include_calibration=True
        )

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
    """Emits GPS_INPUT messages at a configured rate from a SkidSteerModel.

    Tracks `emit_count` so the main loop can report the *actual* achieved
    send rate — which can diverge from the configured rate when the
    TCP tunnel back-pressures or the sim's tick loop falls behind.
    """

    def __init__(
        self,
        conn: Any,
        model: SkidSteerModel,
        rate_hz: float = 15.0,
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
        self.emit_count = 0

    def set_velocity(self, vn: float, ve: float) -> None:
        self._last_vn = vn
        self._last_ve = ve

    def emit(self) -> None:
        time_usec = (time.monotonic_ns() - self._start_ns) // 1000
        lat = int(round(self.model.lat * 1e7))
        lon = int(round(self.model.lon * 1e7))
        # Send the sim's kinematic heading as GPS yaw. MAVLink spec:
        # yaw=0 means "no yaw available", so when heading is exactly 0°
        # we floor to 1 centidegree (0.01°) — this signals "valid yaw"
        # while being indistinguishable from true north to the EKF.
        # If the firmware's AP_GPS_MAV driver fuses this, the sim's
        # heading drives the vehicle. Otherwise the EKF falls back to
        # the internal compass, and navigation still works.
        yaw_cdeg = int(round(self.model.heading_deg * 100)) % 36000
        if yaw_cdeg == 0:
            yaw_cdeg = 1

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
        self.emit_count += 1


# -------------------- VisionPositionEmitter --------------------


class VisionPositionEmitter:
    """Emits VISION_POSITION_ESTIMATE messages so EKF gets external yaw.

    With EK3_SRC1_YAW=6 (ExternalNav) and VISO_TYPE=1 (MAV vision
    backend), ArduPilot consumes VISION_POSITION_ESTIMATE.yaw as the
    EKF's yaw reference. This breaks the GSF chicken-and-egg: GSF needs
    motion to converge, motion needs nav controller, nav controller
    needs yaw — but vision yaw is just *given* to the EKF directly, no
    motion required.

    The position fields (x, y, z) are filled with the sim's NED offset
    from its origin to keep them self-consistent with GPS_INPUT, but
    the EKF uses GPS for position fusion (EK3_SRC1_POSXY=3) so the
    vision position values are only used as a sanity reference.
    """

    def __init__(self, conn: Any, model: SkidSteerModel) -> None:
        self.conn = conn
        self.model = model
        self._origin_lat = model.start_lat
        self._origin_lon = model.start_lon
        self._start_ns = time.monotonic_ns()

    def emit(self) -> None:
        # time_usec=0 tells AP_VisualOdom_MAV to stamp the message
        # with the autopilot's local clock instead of trying to
        # interpret our timestamp. This avoids time-of-arrival sanity
        # check failures that prevent yaw alignment.
        time_usec = 0

        # Compute NED offset from origin in meters.
        cos_lat = math.cos(math.radians(self._origin_lat))
        m_per_deg_lat = 111_320.0
        m_per_deg_lon = 111_320.0 * cos_lat
        north_m = (self.model.lat - self._origin_lat) * m_per_deg_lat
        east_m = (self.model.lon - self._origin_lon) * m_per_deg_lon

        # MAVLink VISION_POSITION_ESTIMATE uses a local NED frame:
        # x = north, y = east, z = down (negative for above origin).
        x = float(north_m)
        y = float(east_m)
        z = 0.0

        # Roll, pitch, yaw in radians.
        roll = 0.0
        pitch = 0.0
        yaw = math.radians(self.model.heading_deg)

        self.conn.mav.vision_position_estimate_send(
            time_usec,
            x,
            y,
            z,
            roll,
            pitch,
            yaw,
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
    - GPS_RAW_INT: AP_GPS_MAV driver's reported fix_type. When
      AR_AttitudeControl::get_forward_speed falls back from
      ahrs.get_velocity_NED(), it checks `AP::gps().status() >= FIX_3D`.
      This message reveals whether the driver considers itself to have a
      3D fix despite us injecting RTK_FIXED in GPS_INPUT.
    - LOCAL_POSITION_NED: EKF velocity (vx, vy) and position (x, y).
      If vx/vy are published, ahrs.get_velocity_NED() is returning true.
      If the message never arrives or is stale, the EKF is not
      publishing velocity and AR_WPNav's early-return guard #4 fires.
    - SYS_STATUS: onboard_control_sensors_health bits. GPS sensor-health
      bit shows whether the autopilot considers GPS healthy from its
      own perspective (distinct from the fix_type).
    - POSITION_TARGET_GLOBAL_INT: what the autopilot's nav controller
      is *aiming* at. Missing = AR_WPNav early-returned before even
      publishing a target; present = AR_WPNav is live and we can
      compare target vs current position to understand throttle=0
      behaviour. Added for V6 Issue 4 diagnostics.
    """
    for msg_id in (
        mavutil.mavlink.MAVLINK_MSG_ID_MISSION_CURRENT,
        mavutil.mavlink.MAVLINK_MSG_ID_NAV_CONTROLLER_OUTPUT,
        mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD,
        mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_EKF_STATUS_REPORT,
        mavutil.mavlink.MAVLINK_MSG_ID_GPS_RAW_INT,
        mavutil.mavlink.MAVLINK_MSG_ID_LOCAL_POSITION_NED,
        mavutil.mavlink.MAVLINK_MSG_ID_SYS_STATUS,
        mavutil.mavlink.MAVLINK_MSG_ID_POSITION_TARGET_GLOBAL_INT,
        # ATTITUDE drives the pre-arm orientation check: if the autopilot
        # reports |roll| or |pitch| beyond ~15° the rover is on its side
        # and AR_PosControl will silently produce 0 desired_speed (V13
        # freeze). Streaming at 2 Hz is plenty for a one-shot check.
        mavutil.mavlink.MAVLINK_MSG_ID_ATTITUDE,
    ):
        _set_message_interval(conn, msg_id, 1.0)


# MAV_GPS_FIX_TYPE values (MAVLink GPS_FIX_TYPE enum).
GPS_FIX_LABELS: dict[int, str] = {
    0: "NO_GPS",
    1: "NO_FIX",
    2: "2D",
    3: "3D",
    4: "DGPS",
    5: "RTK_FLOAT",
    6: "RTK_FIXED",
    7: "STATIC",
    8: "PPP",
}


def gps_fix_label(fix_type: int) -> str:
    return GPS_FIX_LABELS.get(int(fix_type), f"fix{fix_type}")


# Bit masks for SYS_STATUS.onboard_control_sensors_health. Values from
# MAV_SYS_STATUS_SENSOR enum. These are the subset relevant to the
# AR_WPNav guards — GPS for the fix-fallback path in get_forward_speed,
# AHRS for get_velocity_NED / get_location.
SYS_STATUS_SENSOR_GPS = 1 << 5        # 0x20 — MAV_SYS_STATUS_SENSOR_GPS
SYS_STATUS_SENSOR_AHRS = 1 << 12      # 0x1000 — MAV_SYS_STATUS_SENSOR_AHRS


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

    For ArduRover, pass custom_mode = 10 for AUTO, 4 for HOLD,
    15 for GUIDED, etc.
    """
    base_mode = mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED
    conn.mav.set_mode_send(conn.target_system, base_mode, custom_mode)


def set_position_target_global(conn: Any, lat: float, lon: float) -> None:
    """Command the rover to navigate to (lat, lon) in GUIDED mode.

    Uses MAVLink SET_POSITION_TARGET_GLOBAL_INT with a type_mask that
    leaves only the position fields active. The autopilot's GUIDED mode
    handles speed/heading control to reach the commanded point.

    Bypasses the mission state machine and the L1 nav controller's
    initialization sequence — useful when AUTO mode refuses to engage.
    """
    # type_mask bits set = IGNORE that field.
    # Bits 0, 1, 2 = lat, lon, alt (we want these — leave UNSET).
    # Bits 3-5 = vx, vy, vz (ignore).
    # Bits 6-8 = afx, afy, afz (ignore).
    # Bit 9 = force (ignore).
    # Bit 10 = yaw (ignore — autopilot picks).
    # Bit 11 = yaw_rate (ignore).
    type_mask = 0b0000_1111_1111_1000

    conn.mav.set_position_target_global_int_send(
        0,  # time_boot_ms (0 = autopilot uses current)
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        type_mask,
        int(round(lat * 1e7)),
        int(round(lon * 1e7)),
        0.0,    # alt
        0.0, 0.0, 0.0,  # vx, vy, vz (ignored)
        0.0, 0.0, 0.0,  # afx, afy, afz (ignored)
        0.0,    # yaw (ignored)
        0.0,    # yaw_rate (ignored)
    )


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


# Navigation-tuning params that directly shape AR_WPNav / AR_PivotTurn
# behaviour. WP_PIVOT_ANGLE defaults to 0 (pivot disabled); the non-
# pivot branch in AR_WPNav::update_steering_and_speed never writes
# _desired_heading_cd, which is why NAV_CONTROLLER_OUTPUT.nav_bearing
# stays at 0° even when the autopilot *is* producing steering/throttle.
# We log these at sim start so the operator can tell at a glance whether
# pivot is going to fire for their geometry. See
# docs/SIM_AUTOPILOT_ISSUE_V3.md for the full reasoning.
NAV_TUNING_PARAMS_TO_LOG = (
    "WP_PIVOT_ANGLE",
    "WP_PIVOT_RATE",
    "WP_RADIUS",
    "WP_OVERSHOOT",
    "WPNAV_SPEED",
    "WPNAV_ACCEL",
    "WPNAV_JERK",
    "TURN_MAX_G",
    "ATC_STR_ACC_MAX",
)


def log_nav_tuning_params(
    params: dict[str, float],
    printer: Callable[[str], None],
) -> None:
    """Print nav-tuning param values (or 'missing') for at-a-glance diagnostics.

    The three anomalies most worth flagging here:
    - `WP_PIVOT_ANGLE <= 5`  → AR_PivotTurn never activates; non-pivot
      branch used for all turns.
    - `WPNAV_SPEED == 0`     → scurve speed limit zero → target velocity
      collapses to zero → throttle stays at stop-controller output.
    - `WP_RADIUS == 0`       → waypoint reached-test becomes ambiguous
      (radius is used by AR_WPNav to detect "near WP"); paired with a
      degenerate track this can cause reached_destination to latch
      prematurely.
    """
    for name in NAV_TUNING_PARAMS_TO_LOG:
        if name in params:
            val = params[name]
            note = ""
            if name == "WP_PIVOT_ANGLE" and val <= 5:
                note = "  [PIVOT DISABLED — only scurve steering]"
            elif name == "WPNAV_SPEED" and val == 0:
                note = "  [ZERO — scurve will not command motion]"
            elif name == "WP_RADIUS" and val == 0:
                note = "  [ZERO — reached-waypoint logic degenerate]"
            printer(f"  {name} = {val}{note}")
        else:
            printer(f"  {name} = <not on autopilot>")


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


def offset_spawn_perpendicular(
    wp_lat: float,
    wp_lon: float,
    distance_m: float = 3.0,
) -> tuple[tuple[float, float], float]:
    """Place the rover `distance_m` from `wp` facing 90° CW from the bearing to wp.

    Returns ((lat, lon), heading_deg).

    The rover is offset due south of the waypoint (arbitrary direction
    since we only have one point), and the heading is set to 90° CW
    from the bearing toward the waypoint. With the rover south of the
    WP, the bearing to the WP is ~0° (north), so the heading is ~90°
    (east). This gives the L1 navigation controller a non-degenerate
    line segment (rover is not on the track and must steer) and a
    non-zero cross-track error that forces an immediate steering +
    throttle response.

    The "behind the waypoint" approach used previously (V4–V9) placed
    the rover ON the track with heading aligned to it. ArduRover's
    AR_WPNav non-pivot branch produced nav_bearing=0° and throttle=0%
    in that geometry. A perpendicular offset forces the nav controller
    to compute a real cross-track correction which exercises a
    different (working) code path.
    """
    cos_lat = math.cos(math.radians(wp_lat))
    m_per_deg_lat = 111_320.0
    m_per_deg_lon = 111_320.0 * cos_lat if cos_lat != 0 else 111_320.0

    # Place rover due south of the waypoint.
    spawn_lat = wp_lat - distance_m / m_per_deg_lat
    spawn_lon = wp_lon

    # Bearing from spawn to WP is ~0° (north).
    # 90° CW from that → heading = 90° (east).
    dy_m = (wp_lat - spawn_lat) * m_per_deg_lat
    dx_m = (wp_lon - spawn_lon) * m_per_deg_lon
    bearing_to_wp = math.degrees(math.atan2(dx_m, dy_m)) % 360.0
    heading_deg = (bearing_to_wp + 90.0) % 360.0

    return (spawn_lat, spawn_lon), heading_deg


def send_rc_override(
    conn: Any,
    channels: dict[int, int],
) -> None:
    """Send RC_CHANNELS_OVERRIDE with specific channel PWM values.

    `channels` maps 1-based channel number to PWM (1000–2000).
    Channels not in the dict are sent as 0 (no override).
    """
    ch = [0] * 18
    for num, pwm in channels.items():
        if 1 <= num <= 18:
            ch[num - 1] = pwm
    conn.mav.rc_channels_override_send(
        conn.target_system,
        conn.target_component,
        *ch[:8],   # channels 1–8
        *ch[8:],   # channels 9–18 (MAVLink v2)
    )


def arm_autopilot(conn: Any) -> None:
    """Disengage safety, then send MAV_CMD_COMPONENT_ARM_DISARM to arm the vehicle.

    On the bench, BRD_SAFETY_DEFLT defaults the safety switch to engaged on
    every boot. ArduPilot will accept ARM_DISARM (because BRD_SAFETYOPTION
    decouples is_armed from safety state) but hal.util->get_soft_armed()
    stays false — every navigation update early-returns with zero outputs
    and the rover sits at PWM 1500. This was the V13 "freeze" for ~13 sim
    runs. force_safety_off via DO_SET_SAFETY_SWITCH_STATE keeps the same
    code path as a physical safety-button press.
    """
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_DO_SET_SAFETY_SWITCH_STATE,
        0,
        float(mavutil.mavlink.SAFETY_SWITCH_STATE_DANGEROUS),  # param1 = 1 → motors enabled
        0.0, 0.0, 0.0, 0.0, 0.0, 0.0,
    )
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
        0,
        1.0,  # param1 = 1 → arm
        0.0,  # param2 = 0 → normal arm (21196 = force)
        0.0,
        0.0,
        0.0,
        0.0,
        0.0,
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

    Samples several ATTITUDE messages and waits for the yaw to settle
    before returning. Before the EKF finishes tilt/yaw alignment, the
    autopilot falls back to DCM and reports `yaw=0` — using that raw
    value as the sim's seed heading caused the V5 mismatch where the
    EKF's post-alignment yaw disagreed with the sim's kinematic
    heading. See docs/SIM_AUTOPILOT_ISSUE_V5.md §Issue 3.
    """
    deadline = time.monotonic() + max(timeout, 0.5)
    yaws: list[float] = []
    last_any: float | None = None
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        msg = conn.recv_match(
            type="ATTITUDE",
            blocking=True,
            timeout=min(0.5, max(0.05, remaining)),
        )
        if msg is None:
            continue
        yaw_deg = math.degrees(msg.yaw) % 360.0
        last_any = yaw_deg
        yaws.append(yaw_deg)
        # Need ≥3 consecutive samples with range <1° to call it settled.
        if len(yaws) >= 3:
            recent = yaws[-3:]
            spread = max(recent) - min(recent)
            if spread < 1.0:
                return sum(recent) / 3.0

    if last_any is None:
        logger.warning(
            "No ATTITUDE received within %ss — starting sim at heading 0°",
            timeout,
        )
        return 0.0
    logger.warning(
        "ATTITUDE yaw had not settled after %ss (last=%.1f°, samples=%d); "
        "using last sample as seed heading",
        timeout, last_any, len(yaws),
    )
    return last_any


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
