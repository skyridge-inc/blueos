## ADDED Requirements

### Requirement: QGC WPL 110 Waypoint Input
The system SHALL provide a `read_waypoints(path, include_home=False)`
function that parses a QGC WPL 110 `.waypoints` file and returns its
waypoints as a list of `(lat, lon)` tuples. The file header SHALL be
validated as the literal string `QGC WPL 110`; any other header SHALL
raise a `ValueError`. Rows are tab-separated; rows with fewer than 12
fields SHALL be skipped. Blank lines SHALL be skipped.

When `include_home=False` (the default), the row at index 0 (the home
row) SHALL be skipped so the returned list contains only mission
waypoints — this preserves the prior behavior used by visualization
callers.

When `include_home=True`, the row at index 0 SHALL be included as the
first element of the returned list, so index 0 of the result is the home
position and indices 1..N are mission waypoints. This form is used by the
mission-upload path, where the autopilot requires the full sequence
starting at seq 0 = home.

#### Scenario: Default skips home
- **WHEN** `read_waypoints("mission.waypoints")` is called on a file with
  one home row and three mission rows
- **THEN** the result is a list of 3 `(lat, lon)` tuples — the mission
  rows only

#### Scenario: include_home=True returns home at index 0
- **WHEN** `read_waypoints("mission.waypoints", include_home=True)` is
  called on the same file
- **THEN** the result is a list of 4 `(lat, lon)` tuples
- **AND** index 0 of the result equals the home row's lat/lon

#### Scenario: Round-trip with write_waypoints
- **WHEN** a list of waypoints is written via `write_waypoints(path,
  waypoints, home=h)` and then read back with
  `read_waypoints(path, include_home=True)`
- **THEN** the first element of the result equals `h`
- **AND** the remaining elements equal the original `waypoints` list
  within 1e-8 degrees

#### Scenario: Bad header rejected
- **WHEN** the first line of the file is not `QGC WPL 110`
- **THEN** a `ValueError` is raised
