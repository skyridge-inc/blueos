## Context

The target vehicle is an ArduRover skid-steer mower on a Pixhawk Cube
Orange+, paired with an ArduSimple simpleRTK3B (Unicore UM982) dual-antenna
GPS that normally provides both position and true heading. The rover runs
under a BlueOS companion computer that exposes a MAVLink proxy at
`tcp:<host>:5760` — the same endpoint `skynet misc connect` and
`skynet nav upload` already talk to.

`templates/mower_base.param` confirms the frame:

- `FRAME_CLASS = 2` (Rover)
- `SERVO1_FUNCTION = 73` (ThrottleLeft)
- `SERVO3_FUNCTION = 74` (ThrottleRight)
- `CRUISE_SPEED = 2` m/s, `SPEED_MAX = 3` m/s, `WP_SPEED = 2` m/s

This is pure differential thrust — no steering servo. That narrows the sim's
vehicle model to one case and lets us refuse anything else at startup
rather than branching into a kinematic model we haven't tested.

Mission download is greenfield in this repo. `src/skynet/mission_upload.py`
implements the upload state machine, but the inverse path
(`MISSION_REQUEST_LIST` → `MISSION_COUNT` → `MISSION_REQUEST_INT` →
`MISSION_ITEM_INT` → `MISSION_ACK`) does not exist and must be added as
its own small capability.

`GPS_INPUT`, `SERVO_OUTPUT_RAW`, `HEARTBEAT`-based arm detection,
`MISSION_ITEM_REACHED`, and `REQUEST_DATA_STREAM` / `MESSAGE_INTERVAL` are
all new to skynet. All the MAVLink message plumbing for this capability is
first-time code.

## Goals / Non-Goals

**Goals**
- Closed-loop kinematic simulation against a real Pixhawk Cube Orange+,
  over the BlueOS MAVLink proxy or USB serial, using the same
  `mavlink_connection()` context manager as every other skynet command.
- Download the mission currently on the autopilot, spawn the sim at the
  first real waypoint (seq 1, after home), drive ArduRover through AUTO
  mode on simulated sensor data.
- Crash-safe param management: save originals to a sidecar file *before*
  mutation, restore on any clean exit, refuse to start if a sidecar is
  left behind from a prior crashed run.
- Stop cleanly on DISARM or when the last mission waypoint is reached.

**Non-Goals**
- Ackermann-frame rovers (we refuse anything that isn't skid-steer).
- Sensor noise, jitter, multipath, ionospheric or tropospheric effects.
- 3D altitude motion. The rover is ground-bound; altitude stays at 0 MSL
  and the EKF gets baro for vertical.
- RTK float/fix state transitions — we report a clean 3D fix always.
- Fence, rally, geofence, or survey-grid simulation.
- Auto-arming the autopilot. The operator arms in AUTO via Mission Planner
  or QGC once the sim reports healthy lock.
- Field use. This is a dev-loop accelerator, not a flight-sim replacement.

## Decisions

### Decision 1: `GPS_INPUT` over `HIL_GPS`

`GPS_INPUT` (MAVLink id 232) is the canonical external-GPS-injection path
in ArduPilot and is gated on `GPS_TYPE = 14` (MAV). That path keeps the
real IMU loop running — critical, because we want the Pixhawk's attitude
estimate, rate loops, and motor outputs to be real.

`HIL_GPS` (id 113) requires full HIL mode, which disables the real IMU
path. Using it would turn the Pixhawk into a dumb relay instead of a real
hardware-in-the-loop test, defeating the entire point.

**Emission rate**: 5 Hz by default, configurable via `--rate HZ`, clamped
to `[1, 20]`. ArduPilot's EKF3 expects GPS updates around 5–10 Hz; below 1
Hz the EKF innovation gate trips, above 20 Hz we starve the MAVLink link on
the proxy.

**Message fields**:
- `fix_type = 3` (3D fix)
- `satellites_visible = 14`
- `hdop = 0.8`, `vdop = 1.0`
- `horizontal_accuracy = 0.1 m`, `vertical_accuracy = 0.3 m`
- `speed_accuracy = 0.1 m/s`
- `vn, ve` from the kinematic model velocity vector, `vd = 0`
- `yaw` in centidegrees (int16 scaled 0..36000). **Must be nonzero** —
  ArduPilot treats 0 as "no yaw"; use `1` centideg as the floor for true
  north to force the EKF to consume the yaw channel.
- `lat, lon` as int32 scaled `round(deg * 1e7)`, matching the same
  convention used in the mission-upload code path.
- `time_usec` monotonic from `time.monotonic_ns() // 1000` at the start of
  the run (reusing wall-clock here would require NTP alignment on BlueOS).
- `ignore_flags = 0` (we provide everything).

### Decision 2: Kinematic model — skid-steer differential drive

State: `(lat, lon, heading_deg, v_mps, omega_radps)`.

**Input**: `SERVO_OUTPUT_RAW` — pull `servo1_raw` (left throttle PWM) and
`servo3_raw` (right throttle PWM). Convert each to a normalized
`[-1.0, +1.0]` scalar using the autopilot's own `SERVO1_MIN/TRIM/MAX` and
`SERVO3_MIN/TRIM/MAX` params read at startup. Below trim → negative,
above trim → positive, saturated at the rails. If any `SERVOn_*` param
is missing, fall back to the ArduPilot defaults `1000 / 1500 / 2000` and
emit a warning.

**Integrator** (each tick, `dt = 1 / rate_hz`):
```
left_norm   = normalize(servo1_raw, SERVO1_MIN, SERVO1_TRIM, SERVO1_MAX)
right_norm  = normalize(servo3_raw, SERVO3_MIN, SERVO3_TRIM, SERVO3_MAX)
v_mps       = max_speed_mps * (left_norm + right_norm) / 2
omega_radps = max_speed_mps * (right_norm - left_norm) / track_width_m
heading_deg += degrees(omega_radps * dt)
vn          = v_mps * cos(radians(heading_deg))   # north
ve          = v_mps * sin(radians(heading_deg))   # east (ENU)
x_m        += vn * dt
y_m        += ve * dt
(lat, lon)  = to_latlon((x_m, y_m), origin=start_latlon)
```

Reuses `skynet.mission_planning.to_xy` / `to_latlon` — the same
equirectangular projection the planner already uses. One projection
definition for both planning and simulating means the sim and plan live
in the same local frame and any off-by-one in the projection hits both
sides equally.

`max_speed_mps` defaults to `2 mph ≈ 0.8941 m/s` per the user's answer
and is overridable via `--ground-speed MPH`. `track_width_m` is a CLI
knob defaulting to `0.5 m`.

**Frame refusal**: at startup, fetch `FRAME_CLASS`, `SERVO1_FUNCTION`, and
`SERVO3_FUNCTION`. If `FRAME_CLASS != 2` or either function is not 73/74,
raise `FrameMismatchError`. Branching into untested kinematic models on a
live autopilot is worse than refusing.

### Decision 3: Param save/restore with crash-safe sidecar

Required autopilot params for the sim to work:

| Param            | Value | Why                                        |
|------------------|-------|--------------------------------------------|
| `GPS_TYPE`       | 14    | Accept `GPS_INPUT` as primary GPS          |
| `GPS_TYPE2`      | 0     | Disable secondary to avoid blend conflicts |
| `AHRS_EKF_TYPE`  | 3     | EKF3                                        |
| `EK3_SRC1_POSXY` | 3     | GPS horizontal position                    |
| `EK3_SRC1_VELXY` | 3     | GPS horizontal velocity                    |
| `EK3_SRC1_POSZ`  | 1     | Baro for vertical (no altitude sim)        |
| `EK3_SRC1_YAW`   | 2     | GPS yaw (required to consume `GPS_INPUT.yaw`) |

**Startup flow**:

1. Check for a pre-existing sidecar at
   `~/.config/skynet/sim_restore_<host_slug>.param`. If present, refuse
   to start with an error that prints the exact `skynet misc write`
   command needed to recover and instructs the operator to delete the
   sidecar before retrying. This is the crash-recovery gate.
2. `fetch_all_params` the relevant param subset using the existing
   `params.fetch_all_params` helper and filter in-memory.
3. Write the original values to the sidecar file *before* any write.
4. Write the sim-required values via `params.write_params`
   (`include_calibration=True` since these are not calibration params and
   some — e.g. `GPS_TYPE` — would otherwise be filtered out depending on
   future changes to `CALIBRATION_PARAMS`).
5. Run the sim loop.
6. On any exit path (clean return, exception, SIGINT, SIGTERM), restore
   originals from the in-memory copy *and* delete the sidecar.

**Crash-survivability contract**: at any instant between step 3 and a
successful restore, the sidecar file on disk contains exactly the values
that need to be rewritten to bring the autopilot back to its pre-sim
state. Killing the sim with `kill -9` leaves the operator with one
command: `skynet misc write <sidecar> --yes --include-calibration`.

`<host_slug>` is derived from the `--device` argument: for
`tcp:192.168.2.2:5760` → `tcp_192_168_2_2_5760`; for `/dev/ttyACM0` →
`usb_ttyACM0`. This keeps sidecars from different autopilots distinct.

### Decision 4: Mission download state machine

New module `mission_download.py`, mirroring the style of
`mission_upload.py`:

1. Send `MISSION_REQUEST_LIST(target_system, target_component,
   mission_type=MISSION)`.
2. Wait up to `timeout` seconds for `MISSION_COUNT`. Retry the list
   request once on timeout, then `MissionDownloadError`.
3. For `seq` in `0..count-1`: send `MISSION_REQUEST_INT(seq)`, wait for
   `MISSION_ITEM_INT` with matching seq, extract
   `(x / 1e7, y / 1e7)` → `(lat, lon)`. Retry once per item on timeout
   or seq-mismatch, then `MissionDownloadError`.
4. Send `MISSION_ACK(MAV_MISSION_ACCEPTED, MISSION)` to close out the
   session.
5. Return `list[(lat, lon)]` with index 0 = home (mirrors
   `read_waypoints(include_home=True)`).

Refuse if `count == 0` or `count == 1` — the sim needs at least one real
waypoint after home or there is nothing to fly.

### Decision 5: Arm handoff — operator-in-the-loop

The sim does **not** auto-arm the autopilot. Once a few `GPS_INPUT`
messages have been delivered and `SYS_STATUS.onboard_control_sensors_health
& MAV_SYS_STATUS_SENSOR_GPS` reports healthy (or we see a valid
`GLOBAL_POSITION_INT` from the autopilot confirming EKF origin is set), the
sim prints a clear banner:

```
GPS lock established (lat=..., lon=..., hdg=...°)
Arm in AUTO mode via GCS (Mission Planner, QGC, or mavproxy) to begin.
```

Rationale: auto-arming a sim against real hardware is a loaded footgun.
Forcing the operator to arm from a GCS keeps them in the loop and keeps
the sim's responsibility to sensors only — which is the correct separation.

### Decision 6: Stop conditions

Exit cleanly on any of:
- `HEARTBEAT.base_mode & MAV_MODE_FLAG_SAFETY_ARMED == 0` *after* we
  observed the vehicle armed at least once. (Without the "observed armed"
  latch, we'd trip immediately on the very first pre-arm heartbeat.)
- `MISSION_ITEM_REACHED.seq == last_mission_seq` (the final mission
  item, not the home row).
- `--duration N` wall-clock deadline (optional; off by default).
- SIGINT / SIGTERM.

Every exit path — including uncaught exceptions — routes through the
param restore + sidecar delete sequence. Implement via a
`try/finally` around the sim loop inside a `contextlib.ExitStack`
registered with the save/restore context manager.

### Decision 7: Rate & timing

- Request `SERVO_OUTPUT_RAW` at 10 Hz via `MESSAGE_INTERVAL` (preferred,
  per-message) with a fallback to `REQUEST_DATA_STREAM(RC_CHANNELS, 10)`
  for older firmware. This is the autopilot's output stream, not the
  RC input, so `SERVO_OUTPUT_RAW` is the right message.
- Request `HEARTBEAT` and `MISSION_ITEM_REACHED` at 1 Hz each (default is
  already fine — no explicit request needed).
- `GPS_INPUT` emitted at 5 Hz by default (`--rate HZ`, clamp 1–20).
- Kinematic integrator ticks at the GPS emit rate; servo readings are
  last-known-value (zero-order hold) between ticks.
- Startup check: if no `SERVO_OUTPUT_RAW` arrives within 2 s of
  requesting the stream, raise `GpsSimError` with a clear message — a
  silent empty stream would look like a stuck rover.

### Decision 8: Device-string reuse

The command takes `--device` / `-d` and `--baud` / `-b` with the exact
same defaults and semantics as `misc connect` and `nav upload`: default
`/dev/ttyACM0`, env `MOWER_DEVICE`. Pointing at the BlueOS proxy is just
`-d tcp:<host>:5760`. No second way to spell "where is the autopilot."

## Risks / Trade-offs

- **Dual-antenna yaw fidelity**: the real UM982 reports yaw with a quality
  metric we don't simulate. ArduPilot's EKF3 GPS yaw fusion only checks
  that yaw is nonzero and that `EK3_SRC1_YAW = 2`. Acceptable for a dev
  loop; not acceptable for field ops (and field ops is out of scope).
- **Real GPS co-existence**: if the physical RTK GPS is plugged into
  `SERIAL3` while the sim runs, setting `GPS_TYPE = 14` disables its
  driver, so there is no conflict. On exit we restore `GPS_TYPE` and
  normal operation resumes. Documented clearly in the CLI help.
- **No altitude sim**: the rover is ground-bound; we lock `alt = 0 (MSL)`
  and rely on baro (`EK3_SRC1_POSZ = 1`) for vertical. A mission with
  altitude commands will produce ArduPilot warnings but still execute
  in 2D.
- **Partial param writes mid-startup**: fully handled by the sidecar
  recovery file — any partial write is restorable via
  `skynet misc write`.
- **Missed `SERVO_OUTPUT_RAW` stream**: startup check aborts loudly
  within 2 s, so the operator sees the failure instead of a stuck rover.
- **Sidecar staleness after a clean run that the OS killed between
  restore-write and sidecar-delete**: the operator's next run will refuse
  to start and print the recovery command. Worst case is one manual
  recovery step.
- **Not suitable for actual field use**. Repeated because it matters.

## Migration Plan

Purely additive. No existing command, spec, file format, or param file
changes. `read_waypoints`, `upload_mission`, nav planning, and BlueOS
config flows are untouched.
