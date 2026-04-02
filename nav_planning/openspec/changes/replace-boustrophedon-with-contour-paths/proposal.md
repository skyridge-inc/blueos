# Change: Replace boustrophedon with contour-following paths

## Why
The Skyridge mowing areas are narrow (tens of feet) and very long (miles+). The boustrophedon pattern generates short back-and-forth strips across the narrow dimension, which is inefficient — mowers spend more time turning than mowing. A contour-following pattern where each mower traces the polygon edge (and parallel offsets) is the natural fit: each mower runs the full length of the corridor with minimal turns.

## What Changes
- Replace the boustrophedon path generation algorithm with a contour-following algorithm
- Path 1 traces KML vertices from the first point until encountering a ≥ 90° turn
- Subsequent paths are parallel offsets inward by the mower width (specified in inches)
- All paths are clipped to the polygon boundary, handling narrowing sections
- CLI changes: `--width` accepts inches (not meters), `--overlap` and `--heading` removed
- New module `contour.py` replaces `boustrophedon.py` in the pipeline

## Impact
- Affected specs: `mow-planning` (MODIFIED requirements for path generation, CLI interface)
- Affected code: `cli.py`, new `contour.py`, updated tests
- `boustrophedon.py` becomes unused (can be removed or kept for future use)
- `polygon.py` and `waypoints.py` unchanged
