## Context

Skynet already has a fully working `misc connect` command that opens a
MAVLink link through `mavlink_connection(device, baud)` and waits for a
heartbeat. It transparently supports both USB serial (`/dev/ttyACM0`) and
the BlueOS MAVLink proxy (`tcp:<host>:5760`) — the same code path with just
a different device string. The mission-upload command must reuse that
context manager exactly to avoid a second, divergent connection layer.

On the mission side, `nav plan` writes QGC WPL 110 files via
`write_waypoints(path, waypoints, home)`. Row 0 is the home position
(command 16, MAV_CMD_NAV_WAYPOINT, altitude 0) and rows 1..N are the mission
items (also command 16). The existing `read_waypoints()` helper deliberately
skips row 0, which is fine for visualization but loses home when uploading
to the autopilot — the mission protocol requires the full list including
home at index 0.

## Goals / Non-Goals

**Goals**
- One-shot upload of a `.waypoints` file to a Pixhawk Cube Orange+ over
  either USB serial or the BlueOS TCP MAVLink proxy.
- Use the exact same connection plumbing as `misc connect`
  (`mavlink_connection()` context manager).
- Fail loudly with a typed exception and non-zero exit on any MAVLink
  mission-protocol error; never leave a partial mission on the autopilot
  silently.
- Dry-run and confirmation prompts consistent with `write` / `sync` /
  `config upload`.

**Non-Goals**
- Downloading or diffing missions from the autopilot (separate future work).
- Editing the mission in-flight, rallying points, geofences, or survey grids.
- Any integration with Mission Planner / QGC file pickers.
- Hardware-in-the-loop tests — consistent with existing
  no-real-hardware-in-tests policy.

## Decisions

### Decision 1: Use MISSION_ITEM_INT (not MISSION_ITEM)

ArduPilot deprecated the float32 lat/lon form years ago and the int32-scaled
form (`MISSION_ITEM_INT`) is the only one that preserves 8-decimal waypoint
precision — which is exactly what `write_waypoints` emits
(`f"{lat:.8f}"`). We upload as `MISSION_ITEM_INT` with
`lat_int = round(lat * 1e7)` and `lon_int = round(lon * 1e7)`, matching the
QGC WPL 110 convention.

**Alternatives considered**: `MISSION_ITEM` (float). Rejected — loses
precision at lawn scale and is deprecated upstream.

### Decision 2: Single mission type — MAV_MISSION_TYPE_MISSION

QGC WPL 110 files only represent the main mission; they do not carry
geofence, rally, or fence data. We hard-code
`mission_type = MAV_MISSION_TYPE_MISSION` on every message and do not
accept a `--type` flag. If we later need to upload fences or rally points,
that is a separate capability and a separate command.

### Decision 3: Full mission-protocol state machine, not bulk write

The MAVLink mission protocol is pull-based: the client sends `MISSION_COUNT`,
then the autopilot sends a sequence of `MISSION_REQUEST_INT` messages (one
per seq), to which the client replies with `MISSION_ITEM_INT`. The upload
ends with a `MISSION_ACK` carrying a `MAV_MISSION_RESULT`. We implement that
exact state machine rather than blasting all items up-front, because
ArduPilot will reject out-of-order or unsolicited items. We accept both
`MISSION_REQUEST_INT` and legacy `MISSION_REQUEST` from the autopilot — some
firmware revisions still use the float form on the request side even when
the items are ints.

**Retry policy**: on request timeout (5s), resend the current item once,
then fail with `MissionUploadError`. On a `MAV_MISSION_RESULT != ACCEPTED`
ack, fail immediately — retrying a rejected mission is counter-productive.

### Decision 4: Home row at index 0 is always sent

`read_waypoints()` will grow an optional `include_home: bool = False`
parameter (default preserves existing behavior for visualization callers).
The upload code path passes `include_home=True`, so index 0 of the uploaded
mission is the home row verbatim from the file. Clearing the mission first
with `MISSION_CLEAR_ALL` is **not** done — `MISSION_COUNT=N` already
implicitly replaces the existing mission on ArduPilot, and sending
`CLEAR_ALL` adds a redundant round-trip that can race with the new upload.

### Decision 5: Reuse `mavlink_connection()` exactly — no new transport

The command body is a straight analogue of `misc connect`:

```python
with mavlink_connection(device, baud=baud) as conn:
    upload_mission(conn, items)
```

Device string defaults to `/dev/ttyACM0` and is overridable via `--device`
or `MOWER_DEVICE`. Pointing at a BlueOS proxy is just
`-d tcp:192.168.2.2:5760` — no new flag, no `--host` shortcut, no URL
parsing. This keeps the command surface identical to `misc connect` and
avoids a second way to express "where is the autopilot."

## Risks / Trade-offs

- **Partial uploads on transport drop**: if the TCP proxy disconnects
  mid-sequence, the autopilot is left with whatever it has accepted so far
  (possibly zero, possibly partial). We surface this as
  `MissionUploadError` with the sequence number that failed so the operator
  can re-run; we do not attempt to roll back. This matches how `write`
  behaves on param failures.
- **Firmware variation on REQUEST vs REQUEST_INT**: handled by accepting
  either. No runtime flag.
- **No mission verification after upload**: we trust
  `MAV_MISSION_ACCEPTED`. A future `nav diff` command could re-download and
  compare; out of scope here.

## Migration Plan

None — this is purely additive. No existing command, spec, or file format
changes. `read_waypoints()` grows an optional keyword argument with a
default that preserves existing behavior.
