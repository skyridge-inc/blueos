## Context
New standalone project for generating mowing waypoint missions from polygon boundaries. Used by the Skyridge autonomous mower fleet running ArduPilot Rover on BlueOS. Must produce files compatible with Mission Planner and QGroundControl.

## Goals / Non-Goals
- Goals: Generate boustrophedon waypoint paths from polygon boundaries, output QGC WPL 110 files, auto-detect optimal mowing heading, configurable strip width and overlap
- Non-Goals: Spiral patterns (future), MAVLink upload (handled by mower_provisioner), obstacle avoidance within the polygon, headland passes

## Decisions

### Pure Python + Shapely for geometry
- Decision: Use shapely for polygon clipping, no heavy C++ dependencies
- Alternatives considered: Fields2Cover (too heavy, requires CMake/GDAL/Eigen), TrajGenPy (requires libcgal-dev), custom geometry without shapely (error-prone)
- Rationale: Shapely is pip-installable, well-tested, and handles all the polygon intersection we need

### Equirectangular projection for lat/lon to meters
- Decision: Use simple equirectangular projection (lon scaled by cos(lat)) rather than UTM
- Rationale: At lawn scale (< 1km), equirectangular error is < 0.1%. UTM adds complexity with zone selection for no practical benefit.

### Algorithm: rotate-sweep-clip-zigzag
- Decision: Rotate polygon to align mowing direction with X axis, sweep horizontal lines, clip to boundary, connect in zigzag
- Rationale: Working in rotated coordinates makes the sweep trivial (horizontal lines at fixed Y intervals). All the complexity is handled by shapely's intersection.

### Auto-heading from longest edge
- Decision: Default heading aligns with the longest polygon edge to minimize turns
- Rationale: The longest edge typically represents the dominant direction of the property. Fewer turns = faster mowing and less wear.

## Module Architecture

```
cli.py          Typer CLI, argument parsing, Rich output
    |
    v
polygon.py      Parse .poly files, lat/lon <-> XY projection
    |
    v
boustrophedon.py   Rotate, sweep, clip, zigzag (uses shapely)
    |
    v
waypoints.py    QGC WPL 110 file serialization
```

Data flow: `.poly file` -> `list[(lat,lon)]` -> `list[(x,y)]` (meters) -> `list[(x,y)]` (waypoints) -> `list[(lat,lon)]` -> `.waypoints file`

## Risks / Trade-offs
- Concave polygons may produce multiple clipped segments per sweep line. Shapely handles this correctly but zigzag connection order needs care — connect segments left-to-right within each sweep line, alternating direction between lines.
- Very narrow polygons at certain angles may produce zero-length segments. Filter these out.

## Open Questions
- None currently
