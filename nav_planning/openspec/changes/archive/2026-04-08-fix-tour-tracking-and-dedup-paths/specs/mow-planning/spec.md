## ADDED Requirements

### Requirement: Contour Path Deduplication
The system SHALL remove consecutive duplicate coordinates from contour path output. When polygon intersection produces MultiLineString segments with shared endpoints, the resulting path SHALL contain each coordinate only once in sequence.

#### Scenario: MultiLineString deduplication
- **WHEN** the polygon intersection clips a spine into multiple line segments with shared vertices
- **THEN** the output path contains no consecutive duplicate coordinates

#### Scenario: Clean mower waypoints
- **WHEN** mower waypoint files are generated from contour paths
- **THEN** no waypoint appears at the same GPS position as the immediately preceding waypoint

## MODIFIED Requirements

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
