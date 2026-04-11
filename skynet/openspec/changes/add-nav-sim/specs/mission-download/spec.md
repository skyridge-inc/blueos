## ADDED Requirements

### Requirement: download_mission Function
The system SHALL provide
`download_mission(conn, *, timeout=5.0, progress_callback=None)` in
`skynet.mission_download`. `conn` is an open
`pymavlink.mavutil.mavlink_connection` with `target_system` and
`target_component` set by the heartbeat (as produced by
`skynet.connection.mavlink_connection()`).

The function SHALL perform the MAVLink mission-download protocol with
`mission_type = MAV_MISSION_TYPE_MISSION`:

1. Send `MISSION_REQUEST_LIST(target_system, target_component,
   mission_type)`.
2. Wait up to `timeout` seconds for `MISSION_COUNT`. On timeout, resend
   the request once; on a second timeout, raise `MissionDownloadError`.
3. For `seq` in `0..count-1`:
   a. Send `MISSION_REQUEST_INT(target_system, target_component, seq,
      mission_type)`.
   b. Wait up to `timeout` seconds for a matching `MISSION_ITEM_INT`.
      Accept any ordering but require each seq exactly once. Retry the
      request once on timeout or seq mismatch; fail with
      `MissionDownloadError` on a second timeout.
   c. Extract `(x / 1e7, y / 1e7)` → `(lat, lon)`.
4. Send `MISSION_ACK(mission_type, MAV_MISSION_ACCEPTED)` to close the
   session.

The function SHALL return `list[tuple[float, float]]` with index 0 =
home and indices `1..count-1` = mission waypoints — mirroring the
convention used by
`skynet.mission_planning.read_waypoints(include_home=True)` and by
`skynet.mission_upload.upload_mission(items)`. A successful round-trip
`upload_mission(download_mission(conn))` SHALL leave the autopilot with
the same mission it started with, to the precision allowed by the int32
lat/lon scaling.

The function SHALL raise `MissionDownloadError` (a subclass of
`MowerProvisionerError`) when any of the following occur:

- `count == 0` or `count == 1`. The caller must have at least one real
  waypoint after home; an only-home mission is rejected at the download
  layer so callers don't have to.
- Any per-item request fails twice.
- `MISSION_COUNT` does not arrive within two timeout windows.
- The autopilot sends a `MISSION_ITEM_INT` with a seq outside
  `0..count-1`.

When `progress_callback` is provided, it SHALL be called as
`progress_callback(received, total)` after each item with
`total = count`.

#### Scenario: Successful download
- **WHEN** `download_mission(conn)` is called against a mock connection
  that replies with `MISSION_COUNT(count=3)` and `MISSION_ITEM_INT` for
  seqs 0, 1, 2
- **THEN** the function returns a list of 3 `(lat, lon)` tuples
- **AND** each lat/lon matches the `x/1e7` and `y/1e7` from the
  corresponding `MISSION_ITEM_INT`
- **AND** a `MISSION_ACK(ACCEPTED)` was sent at the end

#### Scenario: Empty mission rejected
- **WHEN** the mock autopilot replies with `MISSION_COUNT(count=0)`
- **THEN** `MissionDownloadError` is raised with a message about the
  empty mission
- **AND** no `MISSION_REQUEST_INT` is sent

#### Scenario: Only-home mission rejected
- **WHEN** the mock autopilot replies with `MISSION_COUNT(count=1)`
- **THEN** `MissionDownloadError` is raised with a message instructing
  the operator to upload a mission first

#### Scenario: Retry on single per-item timeout
- **WHEN** the mock autopilot fails to send `MISSION_ITEM_INT(seq=1)`
  within the first `timeout` window and sends it on the second try
- **THEN** `download_mission` resends `MISSION_REQUEST_INT(seq=1)` and
  the download completes normally

#### Scenario: Second timeout fails
- **WHEN** the mock autopilot fails to send `MISSION_ITEM_INT(seq=1)`
  across two consecutive `timeout` windows
- **THEN** `download_mission` raises `MissionDownloadError` identifying
  seq 1

#### Scenario: Out-of-range seq rejected
- **WHEN** the mock autopilot sends `MISSION_ITEM_INT(seq=99)` while
  `count=3`
- **THEN** `download_mission` raises `MissionDownloadError`

#### Scenario: Round-trip with upload_mission
- **WHEN** a mission of 4 items is uploaded via
  `upload_mission(conn, items)` and then downloaded via
  `download_mission(conn)` through the same mock autopilot
- **THEN** the returned list has length 4
- **AND** each item matches the original within 1e-7 degrees

#### Scenario: Progress callback invoked
- **WHEN** `download_mission` is called with a `progress_callback`
- **THEN** the callback is invoked `count` times with monotonically
  increasing `received` values ending at `count`

### Requirement: MissionDownloadError Exception
The system SHALL define `MissionDownloadError` in `skynet.exceptions` as
a subclass of `MowerProvisionerError`. All mission-download failures
SHALL be surfaced via this type so the CLI can map them uniformly to a
red stderr message and a non-zero exit status.

#### Scenario: Exception hierarchy
- **WHEN** `MissionDownloadError("x")` is raised
- **THEN** it is an instance of `MowerProvisionerError`
