## 1. CLI flag

- [x] 1.1 Add `--verbose` / `-v` boolean option to `nav_sim` in `cli.py`.

## 2. Per-tick verbose output

- [x] 2.1 After each `emitter.emit()`, if `verbose` is True, print a
      compact status line with sim time, lat, lon, heading, speed,
      left/right normalized throttle, and raw servo PWM.

## 3. State-transition notices

- [x] 3.1 Print `Reached waypoint N` on every `MISSION_ITEM_REACHED`
      regardless of verbose (not just the final one that trips the
      stop watcher).
- [x] 3.2 Print a disarm notice when the stop watcher trips on DISARM.

## 4. Tests

- [x] 4.1 Existing `--dry-run` CLI test still passes (verbose doesn't
      affect dry run).
- [x] 4.2 Full suite green.
