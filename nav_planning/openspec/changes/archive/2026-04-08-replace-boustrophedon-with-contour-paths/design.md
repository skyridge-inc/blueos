## Context
Replace boustrophedon (back-and-forth strip) coverage with contour-following paths for narrow, elongated mowing corridors. Each mower runs the full length of one offset path.

## Goals / Non-Goals
- Goals: Contour-following paths from KML vertices, parallel offsets at mower width (inches), polygon-clipped, multi-mower output
- Non-Goals: Boustrophedon patterns (removed), spiral patterns, obstacle avoidance

## Decisions

### Algorithm: spine extraction + parallel offset
- Decision: Extract a "spine" polyline by walking KML vertices until a ≥ 90° turn, then generate parallel offsets using Shapely's `offset_curve()`
- Rationale: For narrow corridors, the polygon boundary itself defines the mowing direction. No rotation or sweep-line logic needed. Shapely handles offset geometry including curves.

### Turn angle threshold: 90°
- Decision: A turn of ≥ 90° (absolute exterior angle) terminates the spine
- Rationale: For narrow polygons, the long edges have gentle curves (< 90°) while the short ends are sharp turns (≥ 90°). This naturally separates "follow the edge" from "this is the polygon end."

### Width unit: inches
- Decision: CLI `--width` accepts inches, converted to meters internally (× 0.0254)
- Rationale: Mower deck widths are specified in inches in the US market (21", 42", etc.)

### Offset direction: toward polygon interior
- Decision: Offset direction determined by checking which side of the spine the polygon centroid lies on
- Rationale: Ensures all paths move inward from the boundary edge, never outward

### Path clipping for narrowing
- Decision: Each offset path is intersected with the polygon boundary using Shapely
- Rationale: Where the polygon narrows, outer offset paths may extend beyond the boundary. Clipping ensures all waypoints stay within the mowing area.

## Module Architecture

```
cli.py          Typer CLI, argument parsing, Rich output
    |
    v
polygon.py      Parse KML files, lat/lon <-> XY projection, spine extraction
    |
    v
contour.py      Parallel offset path generation (uses shapely)
    |
    v
waypoints.py    QGC WPL 110 file serialization
```

Data flow: `.kml file` → `list[(lat,lon)]` → spine polyline (XY) → offset paths (XY) → `list[(lat,lon)]` per mower → `.waypoints files`

## Algorithm Detail

1. **Parse KML** → ordered polygon vertices (lat,lon)
2. **Project to XY** meters (equirectangular)
3. **Extract spine**: Walk vertices from index 0. At each vertex, compute the absolute turn angle between incoming and outgoing edges. Stop when turn ≥ 90°. The spine is the polyline from vertex 0 to the stopping vertex.
4. **Generate offset paths**:
   - Path 1 = the spine itself
   - Path 2 = `spine.offset_curve(width_m, side)` where `side` is toward polygon interior
   - Path N = `spine.offset_curve((N-1) * width_m, side)`
   - Continue until the offset no longer intersects the polygon interior
5. **Clip each path** to the polygon boundary
6. **Convert back** to lat/lon, write one `.waypoints` file per mower

## Risks / Trade-offs
- Shapely's `offset_curve()` can produce self-intersecting results on very sharp curves. For gentle corridor curves this is unlikely but should be tested.
- Very narrow sections may cause offset paths to collapse. The polygon intersection step handles this naturally — the path simply becomes shorter or disappears.
