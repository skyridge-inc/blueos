## ADDED Requirements

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

## REMOVED Requirements

### Requirement: Boustrophedon Path Generation
**Reason**: Replaced by contour-following path generation, which is better suited for narrow, elongated mowing corridors.
**Migration**: The `--overlap` and `--heading` CLI options are removed. Path direction is determined by KML vertex order and polygon geometry.

### Requirement: Auto-Heading Detection
**Reason**: No longer needed. Path direction follows the polygon boundary vertices directly.
**Migration**: Remove `--heading` CLI option. The heading concept is replaced by spine extraction from KML vertex order.
