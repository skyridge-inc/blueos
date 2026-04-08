# mission-planning Specification

## Purpose
Generate ArduPilot waypoint missions for the Skyridge mower fleet from KML field-boundary files. Produces one contour-following mowing path per mower, written as QGC WPL 110 `.waypoints` files that load directly into Mission Planner / QGroundControl. Optionally renders the same paths as an interactive HTML satellite map and as Google Earth KML tracks/tours for field review.

This capability is composed by the `nav-plan` command in `provisioning-cli` and is the in-tree replacement for the previously separate `nav_planning` project. It depends only on `shapely` for geometric operations — no MAVLink or HTTP transport.

## Requirements

### Requirement: KML Polygon Parsing
The system SHALL parse a KML file and extract the first `<Polygon>` element's outer boundary as a list of `(lat, lon)` tuples. KML coordinate triples (`lon,lat,alt`) SHALL be reordered to `(lat, lon)`. The system SHALL handle KML files with and without the `http://www.opengis.net/kml/2.2` namespace declaration. The polygon MUST be closed (the first and last coordinates SHALL match within `1e-9` degrees); the closing duplicate SHALL be stripped from the returned list. The polygon MUST contain at least 3 unique vertices after stripping the closing point.

#### Scenario: Closed namespaced polygon
- **WHEN** a KML file contains a `<kml xmlns="http://www.opengis.net/kml/2.2">` document with a `<Polygon><outerBoundaryIs><LinearRing><coordinates>` element holding 5 `lon,lat,alt` triples whose first and last entries match
- **THEN** the parser returns a list of 4 `(lat, lon)` tuples (closing duplicate stripped)

#### Scenario: KML without namespace
- **WHEN** the KML file omits the `xmlns` attribute
- **THEN** the parser still finds the `<Polygon>` element and returns its coordinates

#### Scenario: Polygon not closed
- **WHEN** the first and last coordinates of the polygon differ by more than `1e-9` degrees
- **THEN** the parser raises an error indicating the polygon is not closed

#### Scenario: Insufficient unique vertices
- **WHEN** the polygon has fewer than 3 unique vertices after stripping the closing point
- **THEN** the parser raises an error indicating a valid polygon requires at least 3 vertices

#### Scenario: No polygon present
- **WHEN** the KML file contains no `<Polygon>` element with coordinates
- **THEN** the parser raises a `ValueError` with the message "No <Polygon> with coordinates found in KML file"

### Requirement: Equirectangular Coordinate Projection
The system SHALL project WGS84 `(lat, lon)` coordinates to local `(x, y)` meters using an equirectangular projection centered on a chosen origin, and SHALL provide the inverse projection back to lat/lon. The projection SHALL use `meters_per_deg_lat = 111_320.0` and `meters_per_deg_lon = 111_320.0 * cos(origin_lat)`. When no origin is supplied, the arithmetic centroid of the input vertices SHALL be used.

#### Scenario: Projection round-trip
- **WHEN** lat/lon coordinates within 1 km of the origin are projected to XY meters and then back to lat/lon
- **THEN** the recovered coordinates match the originals within 0.001 m at lawn scale

#### Scenario: Default origin is centroid
- **WHEN** `to_xy` is called without an explicit origin
- **THEN** the returned origin equals the arithmetic mean of the input lat/lon vertices

### Requirement: Spine Extraction
The system SHALL extract a "spine" polyline from a projected polygon by walking vertices in order starting at vertex 0 and stopping at the first vertex whose absolute turn angle (between the incoming and outgoing edges) is greater than or equal to 90 degrees. Turn angles SHALL be normalized to the range `[-180°, 180°]`. The returned spine SHALL contain at least the first edge (vertices 0 and 1).

#### Scenario: Walks straight edges
- **WHEN** the polygon vertices form a straight corridor where vertex 2 has a turn angle below 90 degrees and vertex 3 has a turn of 95 degrees
- **THEN** the spine includes vertices 0, 1, 2, and 3 (stopping at the ≥ 90° turn at vertex 3)

#### Scenario: Minimum spine
- **WHEN** the very first interior vertex turns by 120 degrees
- **THEN** the spine still contains at least the first two vertices

#### Scenario: Too few vertices
- **WHEN** fewer than 2 vertices are provided
- **THEN** an error is raised indicating a spine requires at least 2 vertices

### Requirement: Contour-Following Path Generation
The system SHALL generate mowing paths as parallel offsets of the polygon spine, spaced by the mower cutting width. The first path SHALL be the spine itself, clipped to the polygon. Each subsequent path SHALL be the previous offset plus one additional `width_m` of inward offset, clipped to the polygon, until either the offset is empty or the clipped path has fewer than 2 coordinates. Mower width SHALL be specified in inches and converted to meters using `INCHES_TO_METERS = 0.0254`. Width MUST be strictly positive.

The offset direction SHALL be chosen automatically: the system SHALL generate small left/right test offsets and pick whichever side lies closer to the polygon centroid (i.e., points into the polygon interior).

#### Scenario: Width in inches
- **WHEN** the user specifies `--width 21`
- **THEN** the system uses `0.5334 m` as the spacing between successive offset paths

#### Scenario: Inward offset selection
- **WHEN** generating offsets from a spine that lies on the polygon boundary
- **THEN** the offsets are generated on the side whose test sample is closer to the polygon centroid

#### Scenario: Offset terminates inside polygon
- **WHEN** offsets are generated repeatedly until the next offset is empty or its clipped intersection has fewer than 2 coordinates
- **THEN** path generation stops and the last successful path is the final entry in the result

#### Scenario: Narrowing polygon clips later paths
- **WHEN** the polygon narrows so that some offsets do not span the full spine length
- **THEN** the affected paths are shorter (clipped to the polygon boundary) and remain inside the polygon

#### Scenario: Non-positive width rejected
- **WHEN** `width_inches` is `0` or negative
- **THEN** the path generator raises a `ValueError`

### Requirement: Coordinate Deduplication
The system SHALL remove consecutive duplicate coordinates from generated paths. When the polygon-clipping operation produces a `MultiLineString` whose segments share endpoints, those repeated endpoints SHALL be collapsed so each `(x, y)` appears at most once in immediate sequence in the resulting path.

#### Scenario: MultiLineString deduplication
- **WHEN** the polygon intersection of an offset line returns a `MultiLineString` whose adjacent segments share their endpoint
- **THEN** the extracted path contains no two consecutive identical coordinates

#### Scenario: Clean waypoint output
- **WHEN** mower waypoint files are written from contour paths
- **THEN** no waypoint appears at the same `(lat, lon)` as the immediately preceding waypoint

### Requirement: QGC WPL 110 Waypoint Output
The system SHALL write waypoints to a file in the QGC WPL 110 text format. The file SHALL begin with the literal header `QGC WPL 110` followed by a newline. A home waypoint SHALL be written first as index 0 with `current_wp=1`, frame 0, command 16 (MAV_CMD_NAV_WAYPOINT), all params zero, latitude/longitude from the supplied home position, altitude `0.000000`, and `autocontinue=1`. If no home position is supplied, the first mission waypoint SHALL be reused as home. Each subsequent waypoint SHALL be written with `current_wp=0`, frame 3 (MAV_FRAME_GLOBAL_RELATIVE_ALT), command 16, all params zero, lat/lon at 8 decimal places, altitude `0.000000`, and `autocontinue=1`. Fields SHALL be tab-separated. Writing an empty waypoint list SHALL raise a `ValueError`.

#### Scenario: Header and home row
- **WHEN** waypoints are written to a file
- **THEN** the first line is `QGC WPL 110`
- **AND** the second line is a tab-separated row whose index is `0`, current_wp is `1`, frame is `0`, command is `16`

#### Scenario: Mission rows use relative altitude frame
- **WHEN** a mission of N points is written
- **THEN** lines 3..N+2 use frame `3` (MAV_FRAME_GLOBAL_RELATIVE_ALT) with command `16`

#### Scenario: Loadable in Mission Planner
- **WHEN** the output `.waypoints` file is loaded in Mission Planner
- **THEN** it displays the correct number of waypoints at the correct GPS positions

#### Scenario: Empty waypoint list rejected
- **WHEN** `write_waypoints` is called with no waypoints
- **THEN** a `ValueError` is raised

### Requirement: Per-Mower File Output
The system SHALL emit one `.waypoints` file per generated path. When exactly one path is produced, the file SHALL be written to `<base>.waypoints`. When more than one path is produced, files SHALL be written as `<base>_mower<N>.waypoints` for `N = 1..num_paths`. The home position used for every file SHALL be the polygon's first KML vertex. When zero paths are generated (the polygon is too narrow for the requested width), the system SHALL print a red error and exit with non-zero status.

#### Scenario: Single mower
- **WHEN** the polygon admits exactly one contour path
- **THEN** the system writes `<base>.waypoints`

#### Scenario: Multi-mower
- **WHEN** five contour paths are generated
- **THEN** the system writes `<base>_mower1.waypoints` through `<base>_mower5.waypoints`
- **AND** prints "Mowers required: 5"

#### Scenario: Polygon too narrow
- **WHEN** the polygon cannot accommodate even a single offset at the requested width
- **THEN** the CLI prints a red error and exits with non-zero status

#### Scenario: Home position
- **WHEN** any per-mower waypoint file is written
- **THEN** its index-0 home row uses the first vertex of the input KML polygon

### Requirement: Interactive HTML Visualization
When the `--visualize` flag is set, the system SHALL generate a standalone HTML file at `<base>.html` that renders the mower paths on an interactive Leaflet satellite map. The HTML SHALL reference Leaflet and Esri World Imagery via CDN only (no API key required, no local assets). Each mower path SHALL be drawn as a distinct colored polyline, with an animated marker that traverses the path from start to finish. The visualization SHALL include play/pause, speed adjustment, and per-mower toggles. The map SHALL auto-fit the viewport to all paths. Generating the visualization SHALL NOT change the contents of the `.waypoints` files.

#### Scenario: Self-contained file
- **WHEN** the HTML file is opened in a modern browser with no internet caching
- **THEN** the page loads Leaflet and the satellite tiles from public CDNs and renders without needing local assets

#### Scenario: Single mower visualization
- **WHEN** `--visualize` is passed with one mower path
- **THEN** the HTML file is written next to the `.waypoints` file and shows one polyline with an animated marker

#### Scenario: Multi-mower visualization
- **WHEN** multiple mower paths are generated with `--visualize`
- **THEN** each mower has a distinct color and an individual visibility toggle

#### Scenario: Map auto-fit
- **WHEN** the visualization HTML is opened
- **THEN** the map centers and zooms automatically to fit all rendered paths

#### Scenario: Visualization preserves waypoint output
- **WHEN** `--visualize` is set
- **THEN** the `.waypoints` files are byte-identical to those that would be written without the flag

### Requirement: KML Track Output
When the `--kml-track` flag is set, the system SHALL write a KML file at `<base>_track.kml` containing one `gx:Track` `Placemark` per mower. Coordinates inside `gx:coord` elements SHALL use KML `lon lat alt` ordering. Each track SHALL include a `<when>` timestamp per coordinate, computed from a fixed base time and the haversine distance between consecutive points divided by a constant `speed_mps` (default `1.0 m/s`), so that all mowers begin animating at the same instant during Google Earth timeline playback. Each `Placemark` SHALL have a distinct `LineStyle` color drawn from a fixed palette of 20 colors (cycling for additional mowers). The output filename suffix `_track.kml` SHALL distinguish the track file from the input KML boundary file.

#### Scenario: Single mower KML track
- **WHEN** the user runs the planner with `--kml-track`
- **THEN** a `<base>_track.kml` file is written containing exactly one `gx:Track` Placemark

#### Scenario: Multi-mower KML track
- **WHEN** multiple mower paths exist
- **THEN** the KML file contains one `gx:Track` Placemark per mower, each with a distinct line color

#### Scenario: Parallel animation
- **WHEN** the KML track file is opened in Google Earth and the timeline is played
- **THEN** all mowers begin moving at the same instant because they share the same base start time

#### Scenario: KML preserves waypoint output
- **WHEN** `--kml-track` is set
- **THEN** the `.waypoints` files are byte-identical to those that would be written without the flag

### Requirement: KML Tour Output
When the `--kml-tour` flag is set, the system SHALL write a KML file at `<base>_tour.kml` containing a `gx:Tour` element with a `gx:Playlist` of `gx:FlyTo` directives that fly the camera along the first mower's path. Every mower path SHALL also be embedded in the same KML file as both a static `LineString` Placemark (for visibility outside playback) and an animated `gx:Track` Placemark (so all mowers move during the tour). The `gx:FlyTo` timing SHALL be aligned with the mower-1 track timestamps so that the camera follows behind mower 1 as it moves, and the camera heading SHALL rotate to match the bearing of mower 1's path.

#### Scenario: Tour file contents
- **WHEN** the user runs the planner with `--kml-tour`
- **THEN** the resulting `<base>_tour.kml` contains a `gx:Tour` with `gx:FlyTo` elements
- **AND** every mower path is present as both a `LineString` and a `gx:Track`

#### Scenario: Camera follows mower 1
- **WHEN** the tour is played in Google Earth
- **THEN** the camera stays behind mower 1 as it moves along its path
- **AND** the camera heading rotates to match the bearing of the mower's current segment

#### Scenario: Tour preserves waypoint output
- **WHEN** `--kml-tour` is set
- **THEN** the `.waypoints` files are byte-identical to those that would be written without the flag

### Requirement: Independent Output Flags
The visualization output flags `--visualize`, `--kml-track`, and `--kml-tour` SHALL be independent of one another and of the base waypoint output. Any combination of them MAY be set in a single invocation, and each enabled flag SHALL produce its own file alongside the `.waypoints` file(s).

#### Scenario: All flags together
- **WHEN** `--visualize`, `--kml-track`, and `--kml-tour` are all passed in one invocation
- **THEN** the system writes `.waypoints` file(s), `<base>.html`, `<base>_track.kml`, and `<base>_tour.kml`
