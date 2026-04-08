## Tasks

### 1. Deduplicate contour paths
- [x] 1.1 Fix `_extract_coords()` in `contour.py` to skip consecutive duplicate coordinates from MultiLineString segments
- [x] 1.2 Add test in `test_contour.py` verifying no consecutive duplicate coordinates

### 2. Add animated tracks to KML tour
- [x] 2.1 Update `generate_kml_tour()` in `kml.py` to include `gx:Track` placemarks for all mowers with synthetic timestamps
- [x] 2.2 Synchronize `gx:FlyTo` durations with mower 1 track timing
- [x] 2.3 Update tour tests to verify `gx:Track` presence alongside `gx:Tour`

### 3. Verify
- [x] 3.1 Run full test suite — 77 passed
- [x] 3.2 Verified `input/37_long.kml` mower 1 has 11 clean waypoints (was 20 with 9 duplicates)
- [x] 3.3 Verified tour KML contains 28 Track + 1 Tour + 28 LineString + 11 FlyTo
