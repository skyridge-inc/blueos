## ADDED Requirements

### Requirement: SkidSteerModel
The system SHALL provide a pure-Python `SkidSteerModel` class in
`skynet.gps_sim` representing a differential-drive rover state
`(lat, lon, heading_deg)` plus the integrator that updates it given a
time step and two normalized throttle inputs.

The model SHALL be initialized with a starting `(lat, lon)`, a starting
heading in degrees (default `0.0`), a `max_speed_mps`, and a
`track_width_m`. It SHALL expose a method
`step(dt, left_norm, right_norm) -> (lat, lon, heading_deg, vn, ve)`
where `left_norm` and `right_norm` are clamped to `[-1.0, +1.0]` and the
integrator evolves state according to:

```
v_mps       = max_speed_mps * (left_norm + right_norm) / 2
omega_radps = max_speed_mps * (right_norm - left_norm) / track_width_m
heading    += degrees(omega_radps * dt)     # wrapped to [0, 360)
vn          = v_mps * cos(radians(heading))
ve          = v_mps * sin(radians(heading))
```

Position integration SHALL reuse `skynet.mission_planning.to_xy` and
`to_latlon` — the same equirectangular projection the planner uses — so
the sim frame matches the planner frame exactly. The origin of the
local frame SHALL be the initial `(lat, lon)`.

The model SHALL NOT read from or write to any MAVLink connection. It is
a pure compute unit.

#### Scenario: Zero throttle is stationary
- **WHEN** `step(dt=0.2, left_norm=0.0, right_norm=0.0)` is called on a
  model constructed at `(40.0, -80.0)` with heading 0
- **THEN** the returned lat/lon equal the starting lat/lon within 1e-9
- **AND** `vn == 0.0` and `ve == 0.0`

#### Scenario: Symmetric forward
- **WHEN** `step(dt=1.0, left_norm=1.0, right_norm=1.0)` is called on a
  model with `max_speed_mps=1.0` starting at `(40.0, -80.0)` heading 0
- **THEN** the returned position is approximately 1 m north of the
  starting point
- **AND** `vn ≈ 1.0` and `ve ≈ 0.0`
- **AND** `heading_deg` is unchanged

#### Scenario: In-place pivot
- **WHEN** `step(dt=0.1, left_norm=-1.0, right_norm=+1.0)` is called
  repeatedly
- **THEN** `(lat, lon)` do not change beyond floating-point noise
- **AND** `heading_deg` increases monotonically

#### Scenario: Frame parity with planner
- **WHEN** a model integrates a trajectory and the same trajectory is
  computed by calling `to_xy` / `to_latlon` directly with the same
  origin
- **THEN** the two sequences agree within 1e-6 degrees at every step

### Requirement: ServoNormalizer
The system SHALL provide a `ServoNormalizer` that maps a raw PWM
microsecond value to a normalized `[-1.0, +1.0]` throttle scalar using
the autopilot's `SERVOn_MIN`, `SERVOn_TRIM`, and `SERVOn_MAX` parameters.

Above `trim`, output SHALL scale linearly from 0 at `trim` to `+1` at
`max`. Below `trim`, output SHALL scale linearly from 0 at `trim` to
`-1` at `min`. Values outside `[min, max]` SHALL saturate at the rails.

When any of `SERVOn_MIN`, `SERVOn_TRIM`, or `SERVOn_MAX` is missing from
the fetched parameter set, the normalizer SHALL fall back to the
ArduPilot defaults `1000 / 1500 / 2000` and emit a single warning at
construction time (not per-call).

#### Scenario: Trim maps to zero
- **WHEN** a normalizer with `min=1000, trim=1500, max=2000` is called
  with `raw=1500`
- **THEN** the result is `0.0`

#### Scenario: Full forward
- **WHEN** the same normalizer is called with `raw=2000`
- **THEN** the result is `+1.0`

#### Scenario: Full reverse
- **WHEN** the same normalizer is called with `raw=1000`
- **THEN** the result is `-1.0`

#### Scenario: Above max saturates
- **WHEN** the same normalizer is called with `raw=2500`
- **THEN** the result is `+1.0`

#### Scenario: Below min saturates
- **WHEN** the same normalizer is called with `raw=500`
- **THEN** the result is `-1.0`

#### Scenario: Missing params fall back to defaults with warning
- **WHEN** the normalizer is constructed without `SERVO1_TRIM` in the
  param dict
- **THEN** it uses `1500` as trim
- **AND** a warning is emitted exactly once at construction time

### Requirement: SimParamContext — Crash-Safe Sidecar
The system SHALL provide a `SimParamContext` context manager that saves
the autopilot's current values for a set of required params to a
sidecar file *before* any mutation, writes the sim-required values,
and on exit restores the originals and deletes the sidecar.

The sidecar path SHALL be
`~/.config/skynet/sim_restore_<slug>.param` where `<slug>` is derived
from the connection's `--device` argument by replacing every non-alnum
character with `_` (e.g. `tcp:192.168.2.2:5760` →
`tcp_192_168_2_2_5760`; `/dev/ttyACM0` → `_dev_ttyACM0`). Different
autopilots SHALL have distinct sidecar filenames.

The required param set SHALL include at minimum `GPS_TYPE`,
`GPS_TYPE2`, `AHRS_EKF_TYPE`, `EK3_SRC1_POSXY`, `EK3_SRC1_VELXY`,
`EK3_SRC1_POSZ`, and `EK3_SRC1_YAW`. The sim-required values SHALL be
`14, 0, 3, 3, 3, 1, 2` respectively.

`__enter__` SHALL:

1. Refuse if the sidecar file already exists, raising `GpsSimError`
   with an error message that includes the exact
   `skynet misc write <sidecar> --yes --include-calibration` command
   the operator needs to recover.
2. Fetch current values for the required params from the autopilot.
3. Write those originals to the sidecar file as a valid skynet `.param`
   file that `skynet.config.load_param_file` can read back.
4. Write the sim-required values to the autopilot via
   `skynet.params.write_params`.

`__exit__` SHALL (whether exiting normally or via exception):

1. Write the saved originals back to the autopilot.
2. Delete the sidecar file only after the restore completes successfully.
3. If the restore itself fails, leave the sidecar file in place and
   re-raise so the operator knows manual recovery is needed.

The context manager SHALL register a signal handler for SIGINT and
SIGTERM within its lifetime that triggers the same `__exit__` path so a
`Ctrl+C` during the sim loop still runs the restore.

#### Scenario: Happy-path restore
- **WHEN** `SimParamContext` is entered and then exited without
  exception
- **THEN** the sidecar file was written during entry
- **AND** on exit the autopilot values are back to the originals
- **AND** the sidecar file is deleted

#### Scenario: Leftover sidecar aborts entry
- **WHEN** the sidecar file already exists at context entry
- **THEN** `__enter__` raises `GpsSimError`
- **AND** the error message contains the exact recovery command
- **AND** no param writes occur

#### Scenario: Exception inside the block still restores
- **WHEN** an exception is raised inside the `with` block after entry
  succeeded
- **THEN** `__exit__` still restores the originals and deletes the
  sidecar before the exception propagates

#### Scenario: SIGINT during the block runs restore
- **WHEN** SIGINT is delivered inside the `with` block
- **THEN** the context manager routes the signal through its normal
  exit path and the originals are restored

#### Scenario: Sidecar survives crash
- **WHEN** the process is killed with SIGKILL between `__enter__` and
  a successful restore
- **THEN** the sidecar file on disk contains exactly the original
  values needed to restore the autopilot
- **AND** the file is a valid `.param` file loadable by
  `load_param_file`

### Requirement: GpsInputEmitter
The system SHALL provide a `GpsInputEmitter` that, given an open MAVLink
connection and a `SkidSteerModel`, sends `GPS_INPUT` messages at a
configured rate populated from the model's state.

Each emitted message SHALL set:

- `time_usec` = monotonic microseconds since process start (from
  `time.monotonic_ns() // 1000`)
- `gps_id = 0`
- `ignore_flags = 0`
- `time_week_ms = 0`, `time_week = 0`
- `fix_type = 3` (3D fix)
- `lat = round(lat_deg * 1e7)` (int32)
- `lon = round(lon_deg * 1e7)` (int32)
- `alt = 0.0`
- `hdop = 0.8`, `vdop = 1.0`
- `vn, ve` from the model, `vd = 0.0`
- `speed_accuracy = 0.1`
- `horiz_accuracy = 0.1`, `vert_accuracy = 0.3`
- `satellites_visible = 14`
- `yaw` in centidegrees as `max(1, int(round(heading_deg * 100)) %
  36000)`. The nonzero floor is required because ArduPilot treats yaw 0
  as "no yaw" and refuses to consume it.

The emitter SHALL clamp its construction `rate` argument to `[1, 20]`
Hz and warn on clamping. `GPS_INPUT` is a broadcast MAVLink message
(no target addressing in the message itself), so the emitter SHALL send
via `conn.mav.gps_input_send(...)` and rely on the open connection's
link to route it to the autopilot.

#### Scenario: Emission loop
- **WHEN** the emitter runs for 10 ticks at 5 Hz against a mock
  connection
- **THEN** `gps_input_send` is called exactly 10 times
- **AND** successive `time_usec` values strictly increase
- **AND** each `lat`, `lon` matches `int(round(model.lat * 1e7))` at
  send time

#### Scenario: Yaw floor
- **WHEN** the model heading is exactly 0.0°
- **THEN** the emitted `yaw` field is `1` centideg, not `0`

#### Scenario: Rate clamp
- **WHEN** the emitter is constructed with `rate=50`
- **THEN** the effective rate is 20 Hz and a warning is logged

#### Scenario: Sent via conn.mav.gps_input_send
- **WHEN** the emitter ticks once
- **THEN** exactly one call to `conn.mav.gps_input_send` is made
- **AND** the call carries the model's current lat/lon/heading and the
  GPS_INPUT field values specified above

### Requirement: StopWatcher
The system SHALL provide a `StopWatcher` that combines four stop
triggers, each of which independently causes the sim loop to exit
cleanly: DISARM, mission complete, duration expiry, and signal.

DISARM trigger: watch `HEARTBEAT.base_mode`. Maintain an
`armed_latch` that turns True the first time
`base_mode & MAV_MODE_FLAG_SAFETY_ARMED != 0`. After the latch is set,
the next heartbeat with that bit clear SHALL set `should_stop`. Without
the latch, an initial pre-arm heartbeat would trip immediately.

Mission-complete trigger: watch `MISSION_ITEM_REACHED`. When
`msg.seq == last_mission_seq` (the final mission item from the
downloaded mission, NOT the home row), set `should_stop`.

Duration trigger: if constructed with `duration_seconds`, set
`should_stop` when `monotonic() - start_monotonic > duration_seconds`.

Signal trigger: install SIGINT and SIGTERM handlers on `__enter__` that
set `should_stop`. Restore the previous handlers on `__exit__` so the
watcher is safe to nest inside other signal-using code.

Every stop path SHALL still route through the `SimParamContext` restore
because the stop signal only flips `should_stop` — the actual teardown
happens in the `finally` block of the sim loop.

#### Scenario: DISARM after arm
- **WHEN** the watcher observes a heartbeat with ARMED set, then a
  heartbeat with ARMED clear
- **THEN** `should_stop` becomes True after the second heartbeat

#### Scenario: DISARM before arm is ignored
- **WHEN** the watcher observes only pre-arm heartbeats
- **THEN** `should_stop` remains False

#### Scenario: Mission reached
- **WHEN** `last_mission_seq = 5` and the watcher observes
  `MISSION_ITEM_REACHED(seq=5)`
- **THEN** `should_stop` becomes True
- **AND** earlier `MISSION_ITEM_REACHED(seq=4)` does not set it

#### Scenario: Duration expiry
- **WHEN** the watcher is constructed with `duration_seconds=1.0` and
  1.1 seconds of monotonic time pass
- **THEN** `should_stop` is True

#### Scenario: SIGINT triggers stop
- **WHEN** SIGINT is delivered while the watcher is active
- **THEN** `should_stop` becomes True

### Requirement: Verification Harness Expectations
The implementation SHALL ship with the following verification coverage.
The spec names these explicitly so a reviewer can audit the scope of
tests at PR time; the spec does not prescribe test code.

1. **Pure unit tests** for `SkidSteerModel` and `ServoNormalizer` with
   no MAVLink dependency — stationary zero throttle, symmetric forward,
   in-place pivot, integrator round-trip through `to_xy`/`to_latlon`,
   PWM rail saturation, missing-param fallback.
2. **Mocked-MAVLink tests** for `download_mission` (happy path, empty
   rejection, retry, second-timeout failure, out-of-range seq,
   round-trip against `upload_mission`), `SimParamContext` (happy
   restore, leftover-sidecar rejection, exception-still-restores, SIGINT
   routing, SIGKILL leaves a valid recovery sidecar), `GpsInputEmitter`
   (N-tick loop, yaw floor, rate clamp, routing), and `StopWatcher`
   (each of the four triggers in isolation).
3. **CLI tests** via `typer.testing.CliRunner` for the `nav sim`
   command: `--dry-run` opens no connection and writes no params,
   frame mismatch aborts with `FrameMismatchError`, leftover sidecar
   aborts with the recovery message.
4. **SITL bench verification** (documented manual step, not an
   automated test): run ArduRover SITL + `skynet nav sim` against its
   mavproxy with a 4-point 20 m square mission, arm AUTO, and verify
   the SITL-reported `GLOBAL_POSITION_INT` tracks the sim model's
   internal state within 2 m after 10 s.
5. **Real-hardware bench verification** (documented manual step):
   Pixhawk Cube Orange+ on a bench with the physical RTK GPS
   disconnected, `skynet nav sim` running via the BlueOS proxy, a
   4-point 20 m square mission uploaded, arm in AUTO from Mission
   Planner, and verify that Mission Planner's position indicator walks
   the square, that the `.bin` log shows `GPS.Lat/Lng` tracking
   `POS.Lat/Lng` within 0.5 m and `AHRS.Yaw` matching the sim within
   2°, that `MSG` messages contain mission-complete text, and that
   after disarm the sidecar recovery file is gone and the original
   params are restored.
6. **Crash-recovery drill** (documented manual step): start the sim,
   `kill -9` it mid-run, confirm the sidecar file remains on disk with
   the original param values, confirm that
   `skynet misc write <sidecar> --yes --include-calibration` restores
   the autopilot, and confirm that the next `nav sim` run refuses to
   start until the sidecar is removed.

#### Scenario: All six verification approaches enumerated
- **WHEN** a reviewer audits the implementation PR
- **THEN** every item in this requirement has either a shipped test
  file or a documented manual verification procedure in the PR
  description or `docs/`
