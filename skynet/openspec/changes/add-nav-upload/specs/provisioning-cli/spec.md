## ADDED Requirements

### Requirement: nav upload Command
The `nav upload` command SHALL upload a QGC WPL 110 `.waypoints` file to the
autopilot over MAVLink using the shared `mavlink_connection()` context
manager — the same transport layer used by `misc connect`. It SHALL accept
a positional `waypoint_file` argument and the shared `--device` / `-d`
(default `/dev/ttyACM0`, overridable via `MOWER_DEVICE`), `--baud` / `-b`
(default 115200), `--dry-run`, and `--yes` / `-y` options. The same device
string syntax used by `misc connect` SHALL be accepted unchanged, so
pointing at the BlueOS MAVLink proxy is spelled `-d tcp:<host>:5760`.

The command SHALL parse the waypoint file with
`read_waypoints(..., include_home=True)` so that index 0 of the uploaded
mission is the home row from the file. On `--dry-run` the command SHALL
print the sequence/latitude/longitude of each waypoint and return without
opening any MAVLink connection. Without `--yes` it SHALL prompt for
confirmation before uploading. During upload it SHALL display a Rich
progress bar driven by the mission-upload progress callback. On success it
SHALL print a green message reporting the device and waypoint count. On
any `MissionUploadError` or other `MowerProvisionerError` it SHALL print a
red error to stderr and exit with a non-zero status.

The command MUST NOT introduce a second MAVLink transport path; it MUST
reuse `skynet.connection.mavlink_connection` verbatim.

#### Scenario: USB serial upload
- **WHEN** the user runs `mower-provision nav upload
  ./output/700_long_mower1.waypoints -d /dev/ttyACM0 --yes`
- **THEN** the CLI opens a serial MAVLink connection via
  `mavlink_connection("/dev/ttyACM0", baud=115200)`
- **AND** uploads every waypoint (including home at index 0) via the
  mission-upload state machine
- **AND** prints a green success message with the device and waypoint count

#### Scenario: BlueOS TCP proxy upload
- **WHEN** the user runs `mower-provision nav upload
  ./output/700_long_mower1.waypoints -d tcp:192.168.2.2:5760 --yes`
- **THEN** the CLI opens a TCP MAVLink connection to the BlueOS proxy via
  the same `mavlink_connection()` call used by `misc connect`
- **AND** the upload completes against the Pixhawk Cube Orange+ behind the
  proxy

#### Scenario: Dry run
- **WHEN** the user runs `mower-provision nav upload mission.waypoints
  --dry-run`
- **THEN** the CLI prints every seq/lat/lon that would be uploaded
- **AND** opens no MAVLink connection

#### Scenario: Confirmation prompt
- **WHEN** the user runs `mower-provision nav upload mission.waypoints`
  without `--yes`
- **THEN** the user is prompted to confirm before the upload begins
- **AND** declining aborts the command with no writes

#### Scenario: Missing or empty waypoint file
- **WHEN** the waypoint file does not exist or contains no mission rows
- **THEN** the CLI prints a red error to stderr and exits non-zero

#### Scenario: Autopilot rejects mission
- **WHEN** the autopilot replies with a `MISSION_ACK` whose result is not
  `MAV_MISSION_ACCEPTED`
- **THEN** the CLI prints the `MissionUploadError` message (including the
  failing seq and result code) to stderr and exits non-zero
