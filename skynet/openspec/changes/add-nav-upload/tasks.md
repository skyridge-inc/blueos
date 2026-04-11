## 1. Exceptions and waypoint reader

- [x] 1.1 Add `MissionUploadError(MowerProvisionerError)` to
      `src/skynet/exceptions.py`.
- [x] 1.2 Extend `src/skynet/mission_planning/waypoints.py::read_waypoints`
      with an `include_home: bool = False` parameter. When `True`, return
      the home row as the first element and preserve the full per-row tuple
      (lat, lon) exactly as parsed. Existing callers keep the old behavior.
- [x] 1.3 Add tests for `read_waypoints(include_home=True)` — round-trips a
      file written by `write_waypoints` and asserts home is at index 0.

## 2. Mission upload state machine

- [x] 2.1 Create `src/skynet/mission_upload.py` with `upload_mission(conn,
      items, progress_callback=None, timeout=5.0)`. `items` is a list of
      `(lat, lon)` with index 0 = home.
- [x] 2.2 Implement the MAVLink protocol: send `MISSION_COUNT` with
      `mission_type = MAV_MISSION_TYPE_MISSION`, then loop receiving
      `MISSION_REQUEST_INT` or `MISSION_REQUEST` and replying with
      `MISSION_ITEM_INT` (command 16, frame
      `MAV_FRAME_GLOBAL_RELATIVE_ALT`, `lat_int = round(lat * 1e7)`,
      `lon_int = round(lon * 1e7)`, `current=1` for seq 0 else 0,
      `autocontinue=1`).
- [x] 2.3 Wait for final `MISSION_ACK`; raise `MissionUploadError` if the
      result is not `MAV_MISSION_ACCEPTED`, including the numeric result
      and the seq at which it was reported.
- [x] 2.4 On per-item timeout, retry once from the current seq; on a second
      timeout, raise `MissionUploadError`.
- [x] 2.5 Fire `progress_callback(sent, total)` after each accepted item so
      the CLI can drive a Rich progress bar.

## 3. CLI command

- [x] 3.1 Add `nav_upload` in `src/skynet/cli.py` registered as
      `@nav_app.command("upload")`. Signature:
      `waypoint_file: Path (positional), device: DeviceOption, baud:
      BaudOption, dry_run, yes`.
- [x] 3.2 Body: load items with
      `read_waypoints(str(waypoint_file), include_home=True)`; on empty or
      missing home, print red error and `raise typer.Exit(1)`.
- [x] 3.3 Print a summary line (`"Loaded N waypoints (+ home) from
      <path>"`). On `--dry-run`, list seq/lat/lon and return before
      touching MAVLink.
- [x] 3.4 Without `--yes`, call `typer.confirm(f"Upload {len(items)-1}
      waypoints to {device}?", abort=True)`.
- [x] 3.5 Open `mavlink_connection(device, baud=baud)` (same as
      `misc connect`), drive `upload_mission` under a Rich `Progress`, and
      print a green success message with the device and waypoint count.
- [x] 3.6 Map `MissionUploadError` (and any `MowerProvisionerError`) to a
      red stderr message and `typer.Exit(1)`.

## 4. Tests

- [x] 4.1 `tests/test_mission_upload.py` — mock a MAVLink connection that
      emits `MISSION_REQUEST_INT` for each seq and a final
      `MAV_MISSION_ACCEPTED` ack; assert the right number of
      `MISSION_ITEM_INT` messages were sent in order with the correct
      lat/lon scaling.
- [x] 4.2 Negative test: mock autopilot responds with `MISSION_ACK` =
      `MAV_MISSION_ERROR`; assert `MissionUploadError` is raised and carries
      the failing seq.
- [x] 4.3 Negative test: timeout on one request, retry once succeeds; a
      second timeout raises `MissionUploadError`.
- [x] 4.4 Legacy request test: mock autopilot emits float
      `MISSION_REQUEST` instead of `MISSION_REQUEST_INT` — upload still
      completes.
- [x] 4.5 CLI smoke test (typer `CliRunner`) for `--dry-run` path — asserts
      no connection is opened and the summary is printed.

## 5. Docs and wiring

- [x] 5.1 Update `openspec/specs/provisioning-cli/spec.md` by adding the
      `nav upload` requirement (done via `openspec archive` after
      implementation).
- [x] 5.2 Add a short usage example to `README.md` under the nav section:
      `skynet nav upload ./output/700_long_mower1.waypoints -d
      tcp:192.168.2.2:5760 --yes`.
- [x] 5.3 `uv run pytest` passes.
