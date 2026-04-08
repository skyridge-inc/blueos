# Change: Add KML Track and Tour visualization flags

## Why
The existing `--visualize` flag produces a Leaflet HTML map, but Google Earth is the standard tool for reviewing GPS missions in the ArduPilot ecosystem. KML Track output enables animated playback of mower paths in Google Earth's timeline, useful for field verification. KML Tour output provides cinematic flyover demos for stakeholders. Both require no API keys and work offline once loaded.

## What Changes
- Add `--kml-track` flag to `nav-plan mow` — generates a `.kml` file with `gx:Track` elements (one per mower) with synthetic timestamps for animated playback
- Add `--kml-tour` flag to `nav-plan mow` — generates a `.kml` file with a `gx:Tour` cinematic flyover following the mower path
- New module `kml.py` with `generate_kml_track()` and `generate_kml_tour()` using stdlib `xml.etree.ElementTree`
- Both flags are independent and can be combined with each other and `--visualize`

## Impact
- Affected specs: `mow-planning` (ADDED: KML Track Visualization, KML Tour Visualization)
- Affected code: new `kml.py`, modified `cli.py`
- No changes to path generation, waypoints, polygon, or existing HTML visualization
- No new dependencies (uses stdlib `xml.etree.ElementTree`)
