## 1. Exceptions

- [x] 1.1 Add `MissionDownloadError`, `GpsSimError`, and
      `FrameMismatchError` to `src/skynet/exceptions.py`, all inheriting
      from `MowerProvisionerError`.

## 2. Mission download

- [x] 2.1 Create `src/skynet/mission_download.py` with
      `download_mission(conn, *, timeout=5.0) -> list[tuple[float, float]]`.
- [x] 2.2 Implement the state machine: `MISSION_REQUEST_LIST` →
      `MISSION_COUNT` → per-seq `MISSION_REQUEST_INT` + `MISSION_ITEM_INT`
      → final `MISSION_ACK(MAV_MISSION_ACCEPTED, MISSION)`. Retry once on
      per-item timeout or seq-mismatch, then `MissionDownloadError`.
- [x] 2.3 Return `[home, wp1, ..., wpN]` with index 0 = home to match the
      `read_waypoints(include_home=True)` convention. Reject count 0 or 1.
- [x] 2.4 `tests/test_mission_download.py` — happy path, empty/only-home
      rejection, per-item retry succeeds, second timeout fails, bad ack
      raises, round-trip against `upload_mission`.

## 3. Kinematic model (pure, no MAVLink)

- [x] 3.1 Create `src/skynet/gps_sim.py` with a `SkidSteerModel`
      dataclass holding `(lat, lon, heading_deg)` and a `step(dt,
      left_norm, right_norm)` method returning updated `(lat, lon,
      heading_deg, vn, ve)`.
- [x] 3.2 Integrate via `to_xy` / `to_latlon` from
      `skynet.mission_planning` so the sim frame matches the planner
      frame. Store the start lat/lon as the origin.
- [x] 3.3 Add a `ServoNormalizer` utility that maps raw PWM to
      `[-1.0, +1.0]` using `SERVOn_MIN/TRIM/MAX` with saturation at the
      rails. Fall back to `1000/1500/2000` defaults when params are
      missing, with a one-time warning.
- [x] 3.4 `tests/test_gps_sim.py::TestSkidSteerModel` — zero throttle is
      stationary, symmetric forward goes north when heading=0, full
      differential pivots in place (position unchanged, heading changes),
      integrator matches a 10-step hand-computed trajectory within 1 cm.
- [x] 3.5 `tests/test_gps_sim.py::TestServoNormalizer` — trim center,
      rail saturation above `MAX` and below `MIN`, missing-param
      fallback.

## 4. Param save/restore with crash-safe sidecar

- [x] 4.1 In `gps_sim.py`, add a `SimParamContext` context manager that
      takes the connection, a dict of required sim values, and a sidecar
      path. `__enter__` refuses on leftover sidecar, fetches the current
      values of the required params, writes the sidecar, then pushes the
      sim values via `write_params`. `__exit__` restores the originals
      and deletes the sidecar.
- [x] 4.2 Sidecar path derivation: `~/.config/skynet/sim_restore_<slug>.param`
      where `<slug>` is `--device` with non-alnum chars → `_`.
- [x] 4.3 `tests/test_gps_sim.py::TestSimParamContext` — happy path (enter
      writes sidecar, exit restores + deletes), leftover-sidecar aborts
      `__enter__` with instructions, partial-write followed by exception
      still runs restore, sidecar contents are a valid `.param` file
      re-readable by `load_param_file`.

## 5. SERVO_OUTPUT_RAW subscription

- [x] 5.1 Request `SERVO_OUTPUT_RAW` at 10 Hz via `MESSAGE_INTERVAL`
      (`command_long_send(MAV_CMD_SET_MESSAGE_INTERVAL, ...)`), with a
      fallback to `REQUEST_DATA_STREAM` if the autopilot NACKs the
      interval command.
- [x] 5.2 Background reader thread (or cooperative loop) that caches the
      most recent `servo1_raw` and `servo3_raw` as the zero-order-hold
      input for the kinematic integrator.
- [x] 5.3 Startup check: raise `GpsSimError` if no `SERVO_OUTPUT_RAW`
      arrives within 2 s of the request.
- [x] 5.4 Test: mocked connection that emits a scripted sequence of
      `SERVO_OUTPUT_RAW` messages; assert the cache updates and the
      startup-check timeout raises the right error.

## 6. GPS_INPUT emission loop

- [x] 6.1 Driver loop: tick at `rate` Hz, read cached servo values, step
      the `SkidSteerModel`, build a `GPS_INPUT` message, send via
      `conn.mav.gps_input_send(...)`.
- [x] 6.2 Populate all fields per design.md Decision 1. `yaw` in
      centidegrees, floored at `1` when true heading is 0. `time_usec`
      from `time.monotonic_ns() // 1000`. `ignore_flags = 0`.
- [x] 6.3 Clamp `rate` to `[1, 20]` Hz with a warning outside that range.
- [x] 6.4 Test: mocked conn, run loop for N ticks, assert
      `gps_input_send` called N times with monotonically advancing
      `time_usec` and int32-scaled lat/lon matching the model state.

## 7. Stop-condition watchers

- [x] 7.1 `StopWatcher` tracks: `armed_latch` (True once we've seen
      ARMED once), `last_mission_seq` (from the downloaded mission),
      wall-clock start, and a SIGINT/SIGTERM flag set by a signal
      handler registered only for the sim's lifetime.
- [x] 7.2 Subscribe to `HEARTBEAT` and `MISSION_ITEM_REACHED`. On each
      message, update state and set `should_stop` when any condition
      trips.
- [x] 7.3 `--duration` optional wall-clock limit (seconds).
- [x] 7.4 Test: each of the four triggers fires exactly once in
      isolation; uncaught exception in the sim loop still runs the
      restore (via `finally`).

## 8. CLI `nav sim` command

- [x] 8.1 Add `@nav_app.command("sim")` in `src/skynet/cli.py`.
      Signature: `device: DeviceOption`, `baud: BaudOption`,
      `ground_speed: float = 2.0`, `rate: int = 5`,
      `track_width: float = 0.5`, `duration: Optional[float] = None`,
      `start_seq: int = 1`, `dry_run: bool`, `yes: bool`.
- [x] 8.2 Body: open `mavlink_connection(device, baud=baud)`,
      `download_mission(conn)`, validate skid-steer frame via param
      read, compute start lat/lon from `mission[start_seq]`.
- [x] 8.3 `--dry-run`: print the downloaded mission, the kinematic
      config, and the param diff that *would* be applied; open no
      `SimParamContext`, send no `GPS_INPUT`, exit 0.
- [x] 8.4 Without `--yes`: confirm before entering `SimParamContext`.
- [x] 8.5 Run loop: `with SimParamContext(...): run_sim_loop(conn,
      model, ...)`. Map `MissionDownloadError`, `FrameMismatchError`,
      `GpsSimError`, and other `MowerProvisionerError`s to red stderr
      and `typer.Exit(1)`.
- [x] 8.6 On clean exit, print a green summary line with the total
      duration and the final mission seq reached.

## 9. Integration tests

- [x] 9.1 `tests/test_gps_sim.py::TestNavSimCli::test_dry_run` — CLI
      runner, mocked `mavlink_connection` and `download_mission`,
      assert no param writes and no `gps_input_send` calls.
- [x] 9.2 `tests/test_gps_sim.py::TestNavSimCli::test_frame_mismatch`
      — monkeypatched param fetch returns `FRAME_CLASS=0`, assert the
      CLI exits non-zero with `FrameMismatchError`.
- [x] 9.3 `tests/test_gps_sim.py::TestNavSimCli::test_leftover_sidecar`
      — pre-create a sidecar, assert refusal with the recovery
      instructions in the error message.

## 10. Docs

- [x] 10.1 Add a `nav sim` example to `README.md` under the nav section,
      alongside `nav plan` and `nav upload`.
- [x] 10.2 Add a short docs paragraph noting the `GPS_TYPE` side-effect
      and the crash-recovery sidecar path.

## 11. Green test suite

- [x] 11.1 `unset VIRTUAL_ENV && uv run python -m pytest` passes.
- [x] 11.2 `openspec validate add-nav-sim --strict` still passes after
      implementation (any spec drift must update the spec, not the
      code).
