## 1. Project scaffolding
- [ ] 1.1 Create pyproject.toml with hatchling build, nav-plan entry point, dependencies (typer, rich, shapely)
- [ ] 1.2 Create src/nav_planning/__init__.py with version string
- [ ] 1.3 Run uv sync to install dependencies

## 2. Polygon parsing and projection
- [ ] 2.1 Implement parse_poly_file() in polygon.py — read .poly file, return list of (lat, lon) tuples
- [ ] 2.2 Implement to_xy() — equirectangular projection from lat/lon to local XY meters
- [ ] 2.3 Implement to_latlon() — reverse projection from XY meters back to lat/lon
- [ ] 2.4 Implement auto_heading() — find longest polygon edge and return its angle in degrees
- [ ] 2.5 Write tests for polygon parsing (valid file, comments, empty lines, malformed input)
- [ ] 2.6 Write tests for projection round-trip accuracy

## 3. Boustrophedon algorithm
- [ ] 3.1 Implement rotate_polygon() — rotate XY points by angle around centroid
- [ ] 3.2 Implement sweep_lines() — generate parallel horizontal lines across bounding box at given spacing
- [ ] 3.3 Implement clip_and_zigzag() — intersect sweep lines with polygon, connect segments in alternating direction
- [ ] 3.4 Implement generate_mow_path() — top-level function: takes polygon vertices (XY), width, overlap, heading; returns ordered waypoint list
- [ ] 3.5 Write tests with a simple rectangle (known number of strips, predictable waypoints)
- [ ] 3.6 Write tests with a concave L-shaped polygon (multiple segments per sweep line)

## 4. Waypoint file I/O
- [ ] 4.1 Implement write_waypoints() in waypoints.py — serialize list of (lat, lon) to QGC WPL 110 format
- [ ] 4.2 Implement read_waypoints() — parse QGC WPL 110 file back to list of (lat, lon) for testing/verification
- [ ] 4.3 Write tests for waypoint file round-trip and format compliance

## 5. CLI integration
- [ ] 5.1 Implement mow command in cli.py with Typer — wire arguments to polygon/boustrophedon/waypoints modules
- [ ] 5.2 Add Rich progress output (polygon info, strip count, waypoint count)
- [ ] 5.3 Write CLI integration test (invoke with a test .poly file, verify .waypoints output exists and is valid)

## 6. Validation
- [ ] 6.1 Run full test suite, ensure all tests pass
- [ ] 6.2 Test with a real-world polygon from a Skyridge property
