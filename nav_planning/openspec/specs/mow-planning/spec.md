# mow-planning Specification

## Purpose
TBD - created by archiving change add-mow-plan-cli. Update Purpose after archive.
## Requirements
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

### Requirement: Mow Path Visualization
The system SHALL generate a standalone HTML file that visualizes mower paths on an interactive satellite map when the `--visualize` flag is passed to `nav-plan mow`. The HTML file SHALL use Leaflet.js with Esri World Imagery tiles (no API key required). Each mower's path SHALL be rendered as a distinct colored polyline. An animated marker SHALL move along each path from start to finish. The visualization SHALL include play/pause control, speed adjustment, and the ability to toggle individual mower paths on/off. The map SHALL auto-center and zoom to fit all paths. The HTML file SHALL be self-contained (CDN references only, no local assets) and openable in any modern browser.

#### Scenario: Single mower visualization
- **WHEN** the user runs `nav-plan mow field.kml --width 42 --visualize`
- **THEN** the system generates both the `.waypoints` file and a `.html` file at the same base path
- **AND** the HTML file shows one colored polyline with an animated marker

#### Scenario: Multi-mower visualization
- **WHEN** the mow command generates multiple mower paths and `--visualize` is set
- **THEN** the HTML file shows each mower's path in a distinct color with individual toggle controls

#### Scenario: Visualization without affecting waypoint output
- **WHEN** the `--visualize` flag is used
- **THEN** all `.waypoints` files are generated identically to when the flag is omitted

#### Scenario: Map auto-centers on paths
- **WHEN** the visualization HTML is opened in a browser
- **THEN** the map automatically centers and zooms to show all mower paths within the viewport

### Requirement: KML Track Visualization
The system SHALL generate a KML file with `gx:Track` elements when the `--kml-track` flag is passed to `nav-plan mow`. Each mower's path SHALL be rendered as a separate `gx:Track` Placemark with a distinct line color. Timestamps SHALL be synthetic, spaced by inter-point distance divided by a constant speed, so all mowers animate in parallel during Google Earth timeline playback. Coordinates SHALL use KML `lon lat alt` ordering. The output file SHALL use a `_track.kml` suffix to avoid overwriting the input KML boundary file.

#### Scenario: Single mower KML track
- **WHEN** the user runs `nav-plan mow field.kml --width 42 --kml-track`
- **THEN** the system generates a `field_track.kml` file containing one `gx:Track` Placemark
- **AND** the waypoint files are generated identically to when the flag is omitted

#### Scenario: Multi-mower KML track
- **WHEN** the mow command generates multiple mower paths and `--kml-track` is set
- **THEN** the KML file contains one `gx:Track` Placemark per mower, each with a distinct style color

#### Scenario: Timestamps enable parallel animation
- **WHEN** the KML track file is opened in Google Earth
- **THEN** all mowers animate simultaneously because they share the same base start time

### Requirement: KML Tour Visualization
The system SHALL generate a KML file with a `gx:Tour` element when the `--kml-tour` flag is passed to `nav-plan mow`. The tour SHALL contain a `gx:Playlist` of `gx:FlyTo` directives that fly the camera along the first mower's path. All mower paths SHALL be rendered as both static `LineString` placemarks and animated `gx:Track` placemarks with synthetic timestamps, so mower markers are visible and moving during tour playback. The camera FlyTo timing SHALL be synchronized with the mower 1 track timestamps so the camera follows behind the moving mower. The output file SHALL use a `_tour.kml` suffix.

#### Scenario: Tour generation
- **WHEN** the user runs `nav-plan mow field.kml --width 42 --kml-tour`
- **THEN** the system generates a `field_tour.kml` file containing a `gx:Tour` with `gx:FlyTo` elements
- **AND** all mower paths are visible as static colored polylines
- **AND** all mowers have animated `gx:Track` markers that move during playback

#### Scenario: Camera follows mower 1
- **WHEN** the tour is played in Google Earth
- **THEN** the camera stays behind mower 1 as it moves along its path
- **AND** the camera heading rotates to follow the bearing of the mower's path

#### Scenario: Independent flags
- **WHEN** `--kml-track`, `--kml-tour`, and `--visualize` are all passed
- **THEN** the system generates `_track.kml`, `_tour.kml`, and `.html` files independently

### Requirement: Contour-Following Path Generation
The system SHALL generate mowing paths that follow the polygon boundary contour rather than back-and-forth strips. The first path SHALL start at the first KML vertex and follow subsequent vertices until encountering a turn of 90 degrees or more. Subsequent paths SHALL be parallel offsets inward from the first path, spaced by the mower width. All paths SHALL be clipped to remain within the polygon boundary. The system SHALL output one waypoint file per mower path.

#### Scenario: Simple rectangular corridor
- **WHEN** a rectangular polygon with 4 vertices is provided and the mower width is 21 inches
- **THEN** the first path follows the first edge (vertex 0 to vertex 1, stopping at the ≥ 90° turn), and subsequent paths are parallel offsets inward until the polygon width is filled

#### Scenario: Spine extraction stops at sharp turn
- **WHEN** the polygon vertices are walked from vertex 0 and vertex 2 has a turn angle of 95 degrees
- **THEN** the spine polyline includes vertices 0, 1, and 2 (stopping at the ≥ 90° turn at vertex 2)

#### Scenario: Narrowing polygon
- **WHEN** the polygon narrows such that only 3 offset paths fit at one section and 5 fit at another
- **THEN** paths 4 and 5 are shorter (clipped to the polygon boundary) and paths remain within the polygon area

#### Scenario: Last path stays within polygon
- **WHEN** offset paths are generated until no more fit within the polygon
- **THEN** the last path does not extend outside the polygon boundary lines

### Requirement: Mower Width in Inches
The system SHALL accept the mower cutting width as a `--width` CLI option specified in inches. The width SHALL be converted to meters internally for geometric calculations (1 inch = 0.0254 meters).

#### Scenario: Width in inches
- **WHEN** the user specifies `--width 21`
- **THEN** the system uses 0.5334 meters (21 × 0.0254) as the offset distance between paths

### Requirement: Mower Count Output
The system SHALL compute and display the number of mower paths (mowers required) based on the polygon geometry and mower width. Each path SHALL be written to a separate waypoint file.

#### Scenario: Multi-mower output
- **WHEN** the polygon width accommodates 5 offset paths at the given mower width
- **THEN** the system outputs 5 waypoint files (`_mower1.waypoints` through `_mower5.waypoints`) and displays "Mowers required: 5"

### Requirement: Contour Path Deduplication
The system SHALL remove consecutive duplicate coordinates from contour path output. When polygon intersection produces MultiLineString segments with shared endpoints, the resulting path SHALL contain each coordinate only once in sequence.

#### Scenario: MultiLineString deduplication
- **WHEN** the polygon intersection clips a spine into multiple line segments with shared vertices
- **THEN** the output path contains no consecutive duplicate coordinates

#### Scenario: Clean mower waypoints
- **WHEN** mower waypoint files are generated from contour paths
- **THEN** no waypoint appears at the same GPS position as the immediately preceding waypoint

