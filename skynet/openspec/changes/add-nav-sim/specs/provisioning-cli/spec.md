## ADDED Requirements

### Requirement: nav sim Command
The `nav sim` command SHALL run a software-in-the-loop GPS/heading
simulator against a real autopilot over MAVLink using the shared
`skynet.connection.mavlink_connection()` context manager — the same
transport used by `misc connect` and `nav upload`. It SHALL download the
current mission from the autopilot via the `mission-download` capability,
spawn the simulated rover at the mission item indexed by `--start-seq`
(default `1`, the first real waypoint after home), and drive a closed
loop in which `SERVO_OUTPUT_RAW` commands are converted through a
skid-steer kinematic model into `GPS_INPUT` messages fed back to the
autopilot.

The command SHALL accept the shared `--device` / `-d` (default
`/dev/ttyACM0`, overridable via `MOWER_DEVICE`) and `--baud` / `-b`
(default 115200) options. Pointing at the BlueOS MAVLink proxy SHALL be
spelled `-d tcp:<host>:5760`, identically to `misc connect`. The command
SHALL also accept:

- `--ground-speed MPH` (default `2.0`) — max forward speed at full
  throttle PWM. Velocity scales linearly from `0` at zero throttle to
  `ground_speed` at full-scale servo output.
- `--rate HZ` (default `5`, clamped to `[1, 20]`) — `GPS_INPUT` emission
  rate and kinematic integrator tick rate.
- `--track-width METERS` (default `0.5`) — skid-steer wheelbase used to
  convert differential throttle into yaw rate.
- `--duration SECONDS` (optional) — wall-clock safety timeout.
- `--start-seq N` (default `1`) — mission seq to spawn at.
- `--dry-run` — prints the downloaded mission, the kinematic config, and
  the param diff that would be applied, then exits without mutating
  autopilot state or sending any `GPS_INPUT`.
- `--yes` / `-y` — skips the confirmation prompt before entering the
  param save/restore context.

Before running the sim loop, the command SHALL:

1. Refuse on any non-skid-steer frame by reading `FRAME_CLASS`,
   `SERVO1_FUNCTION`, and `SERVO3_FUNCTION`, raising `FrameMismatchError`
   on mismatch (`FRAME_CLASS != 2` or `SERVO1_FUNCTION != 73` or
   `SERVO3_FUNCTION != 74`).
2. Refuse at startup if a leftover sim-restore sidecar file exists for
   this device, with an error message containing the exact
   `skynet misc write` recovery command.
3. Reject missions with `count == 0` or `count == 1` — there is no real
   waypoint to spawn at.

During the run, the command SHALL print a green "GPS lock established"
banner once a healthy EKF state is observed, and SHALL NOT auto-arm the
autopilot — operator arms in AUTO via their GCS.

The command SHALL exit cleanly on any of: autopilot DISARM (after having
been observed armed at least once), `MISSION_ITEM_REACHED` for the final
mission seq, `--duration` expiry, or SIGINT/SIGTERM. Every exit path
SHALL run the param restore and delete the sidecar. Any raised
`MissionDownloadError`, `FrameMismatchError`, `GpsSimError`, or other
`MowerProvisionerError` SHALL be printed in red to stderr and exit
non-zero.

The command MUST NOT introduce a second MAVLink transport path; it MUST
reuse `skynet.connection.mavlink_connection` verbatim.

#### Scenario: USB serial default
- **WHEN** the operator runs `skynet nav sim --yes` on a host with the
  Pixhawk on `/dev/ttyACM0`
- **THEN** the CLI opens a serial MAVLink connection via
  `mavlink_connection("/dev/ttyACM0", baud=115200)`
- **AND** downloads the current mission from the autopilot
- **AND** enters the sim param context, starts the GPS_INPUT loop, and
  prints the "GPS lock established" banner

#### Scenario: BlueOS TCP proxy
- **WHEN** the operator runs
  `skynet nav sim -d tcp:192.168.2.2:5760 --yes`
- **THEN** the CLI opens a TCP MAVLink connection to the BlueOS proxy
  using the same `mavlink_connection()` call
- **AND** the sim runs against the Pixhawk behind the proxy

#### Scenario: Dry run
- **WHEN** the operator runs `skynet nav sim --dry-run`
- **THEN** the CLI downloads the mission and prints it
- **AND** prints the kinematic config (ground speed, rate, track width)
- **AND** prints the param diff that *would* be applied to put the
  autopilot into external-GPS mode
- **AND** opens no `SimParamContext` and sends no `GPS_INPUT` messages
- **AND** exits zero

#### Scenario: Confirmation prompt
- **WHEN** the operator runs `skynet nav sim` without `--yes`
- **THEN** the user is prompted to confirm before any autopilot params
  are mutated
- **AND** declining aborts the command with no param writes

#### Scenario: Non-skid-steer frame is refused
- **WHEN** the autopilot reports `FRAME_CLASS = 1` (not a rover) or
  `SERVO1_FUNCTION != 73` or `SERVO3_FUNCTION != 74`
- **THEN** the CLI raises `FrameMismatchError`, prints a red error
  explaining the required frame, and exits non-zero *before* any
  `GPS_INPUT` is sent

#### Scenario: Empty or only-home mission
- **WHEN** the autopilot has no mission loaded (`count == 0`) or only a
  home row (`count == 1`)
- **THEN** the CLI prints a red error telling the operator to run
  `skynet nav upload` first and exits non-zero

#### Scenario: Leftover sidecar from a prior crashed run
- **WHEN** a `sim_restore_<slug>.param` file already exists under
  `~/.config/skynet/` for this device
- **THEN** the CLI refuses to start
- **AND** the error message contains the exact
  `skynet misc write <sidecar-path> --yes --include-calibration`
  command the operator needs to recover

#### Scenario: Start at first real waypoint
- **WHEN** the mission has home + 5 waypoints and `--start-seq` is not
  provided
- **THEN** the simulated rover spawns at mission seq 1 (the first real
  waypoint), not seq 0 (home)

#### Scenario: DISARM stops the sim cleanly
- **WHEN** the sim is running and the operator has armed and then
  disarms the autopilot from the GCS
- **THEN** the sim exits its loop
- **AND** restores the original autopilot params
- **AND** deletes the sidecar file

#### Scenario: Mission complete stops the sim cleanly
- **WHEN** the sim is running and the autopilot emits
  `MISSION_ITEM_REACHED(seq=last_seq)`
- **THEN** the sim exits its loop
- **AND** restores the original autopilot params
- **AND** deletes the sidecar file
- **AND** prints a green summary with the final seq

#### Scenario: SERVO_OUTPUT_RAW stream never starts
- **WHEN** the autopilot fails to send `SERVO_OUTPUT_RAW` within 2 s of
  the stream request at startup
- **THEN** the CLI raises `GpsSimError` with a clear message
- **AND** the param restore runs before exit
