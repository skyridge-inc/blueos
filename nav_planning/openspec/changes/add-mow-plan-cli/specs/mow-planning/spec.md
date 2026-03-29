## ADDED Requirements

### Requirement: Polygon File Parsing
The system SHALL parse ArduPilot .poly files containing one space-separated `lat lon` pair per line. Lines starting with `#` SHALL be treated as comments. Blank lines SHALL be skipped. The polygon MUST have at least 3 vertices.

#### Scenario: Valid polygon file
- **WHEN** a .poly file with 4 lat/lon pairs is provided
- **THEN** the system returns a list of 4 (lat, lon) coordinate tuples

#### Scenario: File with comments and blank lines
- **WHEN** a .poly file contains `#` comment lines and blank lines mixed with coordinates
- **THEN** the system ignores comments and blanks, returning only coordinate tuples

#### Scenario: Insufficient vertices
- **WHEN** a .poly file contains fewer than 3 coordinate pairs
- **THEN** the system raises an error indicating a valid polygon requires at least 3 vertices

### Requirement: Coordinate Projection
The system SHALL project WGS84 lat/lon coordinates to local XY meters using equirectangular projection, and reverse-project XY meters back to lat/lon. The projection origin SHALL be the centroid of the input polygon.

#### Scenario: Projection round-trip
- **WHEN** a set of lat/lon coordinates is projected to XY and then back to lat/lon
- **THEN** the resulting coordinates match the originals within 0.001 meter accuracy at lawn scale (< 1km)

### Requirement: Auto-Heading Detection
The system SHALL automatically detect the optimal mowing heading by finding the longest edge of the input polygon and using its angle. The heading SHALL be expressed in degrees (0=north, 90=east, clockwise).

#### Scenario: Rectangular polygon
- **WHEN** a rectangular polygon with its longest side running east-west is provided with no explicit heading
- **THEN** the auto-detected heading is approximately 90 degrees (east-west strips)

#### Scenario: Explicit heading override
- **WHEN** the user provides an explicit --heading value
- **THEN** the auto-detection is skipped and the provided heading is used

### Requirement: Boustrophedon Path Generation
The system SHALL generate a boustrophedon (back-and-forth parallel strips) coverage path within the polygon boundary. Strips SHALL be spaced at `width * (1 - overlap / 100)` meters apart. The path SHALL alternate direction on each strip (left-to-right, then right-to-left).

#### Scenario: Simple rectangle with no overlap
- **WHEN** a 10m x 5m rectangle is provided with strip width 1.0m and 0% overlap
- **THEN** the system generates 5 parallel strips covering the entire rectangle

#### Scenario: Overlap reduces spacing
- **WHEN** strip width is 1.0m and overlap is 10%
- **THEN** strips are spaced 0.9m apart

#### Scenario: Concave polygon
- **WHEN** a concave (L-shaped) polygon is provided
- **THEN** sweep lines that cross the concavity produce multiple clipped segments, all included in the path

### Requirement: Waypoint File Output
The system SHALL write waypoint files in QGC WPL 110 format compatible with Mission Planner and QGroundControl. The first waypoint (index 0) SHALL be a home position using the first polygon vertex. Subsequent waypoints SHALL use MAV_CMD_NAV_WAYPOINT (command 16) with MAV_FRAME_GLOBAL_RELATIVE_ALT (frame 3) and altitude 0.

#### Scenario: Valid QGC WPL 110 output
- **WHEN** a mowing path is generated
- **THEN** the output file starts with `QGC WPL 110` header and contains tab-separated waypoint lines with fields: index, current_wp, frame, command, p1, p2, p3, p4, lat, lon, alt, autocontinue

#### Scenario: Loadable in Mission Planner
- **WHEN** the output .waypoints file is loaded in Mission Planner
- **THEN** it displays the correct number of waypoints at the correct GPS positions

### Requirement: CLI Interface
The system SHALL provide a `nav-plan mow` CLI command accepting a polygon file path and optional parameters for strip width, overlap percentage, heading angle, and output file path.

#### Scenario: Minimal invocation
- **WHEN** the user runs `nav-plan mow field.poly --width 0.53`
- **THEN** the system generates a .waypoints file with auto-detected heading and 0% overlap

#### Scenario: Full options
- **WHEN** the user runs `nav-plan mow field.poly --width 0.53 --overlap 10 --heading 45 -o mission.waypoints`
- **THEN** the system uses the specified overlap, heading, and output path

#### Scenario: Missing required width
- **WHEN** the user runs `nav-plan mow field.poly` without --width
- **THEN** the CLI shows an error indicating --width is required
