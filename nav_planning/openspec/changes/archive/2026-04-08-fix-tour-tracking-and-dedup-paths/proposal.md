# Change: Fix KML tour to track mower 1 and deduplicate contour paths

## Why
Two bugs discovered testing with `input/37_long.kml`:
1. The `--kml-tour` flyover is camera-only — no animated mower marker is visible, so the camera appears to fly the path alone rather than following a mower. The user expects to see mower 1 moving with the camera behind it.
2. Contour path generation produces consecutive duplicate waypoints when `polygon.intersection()` returns a MultiLineString. Mower 1's path has 20 waypoints (9 duplicates) instead of the expected 11 clean KML spine vertices. This also causes tour FlyTo artifacts (duplicate entries at the same location with heading=0).

## What Changes
- `contour.py`: `_extract_coords()` deduplicates consecutive coordinates from MultiLineString segments
- `kml.py`: `generate_kml_tour()` adds `gx:Track` placemarks for all mowers (animated markers with timestamps), synchronized with the camera `gx:Tour` FlyTo timing

## Impact
- Affected specs: `mow-planning` (MODIFIED: KML Tour Visualization, contour path dedup)
- Affected code: `contour.py`, `kml.py`, updated tests
- All downstream outputs (waypoints, visualizations) benefit from dedup — fewer redundant waypoints for Mission Planner to process
