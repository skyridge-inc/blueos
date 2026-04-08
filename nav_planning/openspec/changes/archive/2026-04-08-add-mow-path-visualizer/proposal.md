# Change: Add mow path visualization with animated map

## Why
After generating waypoint files, there's no way to visually verify the mowing paths or share the plan with stakeholders. An interactive map showing each mower's path with animation helps validate coverage, spot gaps, and demonstrate the plan before deploying to hardware.

## What Changes
- Add `--visualize` flag to `nav-plan mow` command
- When set, generates a standalone HTML file using Leaflet.js with satellite imagery (Esri World Imagery, no API key)
- The HTML shows each mower's path as a colored polyline with an animated marker that moves from start to finish
- Includes play/pause, speed control, and per-mower toggle visibility
- New module `visualize.py` generates the HTML from waypoint data
- HTML file is self-contained (inlines Leaflet from CDN) and opens in any browser

## Impact
- Affected specs: `mow-planning` (ADDED visualization requirement)
- Affected code: new `visualize.py`, modified `cli.py`
- No changes to path generation, waypoints, or polygon modules
