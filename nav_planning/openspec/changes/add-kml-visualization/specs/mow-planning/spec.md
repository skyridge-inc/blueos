## ADDED Requirements

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
The system SHALL generate a KML file with a `gx:Tour` element when the `--kml-tour` flag is passed to `nav-plan mow`. The tour SHALL contain a `gx:Playlist` of `gx:FlyTo` directives that fly the camera along the first mower's path. All mower paths SHALL be rendered as static `LineString` placemarks visible during the tour. The camera SHALL use `LookAt` with heading following the path direction. The output file SHALL use a `_tour.kml` suffix.

#### Scenario: Tour generation
- **WHEN** the user runs `nav-plan mow field.kml --width 42 --kml-tour`
- **THEN** the system generates a `field_tour.kml` file containing a `gx:Tour` with `gx:FlyTo` elements
- **AND** all mower paths are visible as static colored polylines

#### Scenario: Camera follows path direction
- **WHEN** the tour is played in Google Earth
- **THEN** the camera heading rotates to follow the bearing of the mower's path at each waypoint

#### Scenario: Independent flags
- **WHEN** `--kml-track`, `--kml-tour`, and `--visualize` are all passed
- **THEN** the system generates `_track.kml`, `_tour.kml`, and `.html` files independently
