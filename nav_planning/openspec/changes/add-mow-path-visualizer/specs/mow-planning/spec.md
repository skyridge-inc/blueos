## ADDED Requirements

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
