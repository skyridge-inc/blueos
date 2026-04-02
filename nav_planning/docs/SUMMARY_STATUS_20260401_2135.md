# Nav Planning — Status Summary

**Date:** 2026-04-01 21:35
**Branch:** `feature/mower_provisioner`
**Last commit:** `3e33991` — feat(nav_planning): implement mow path planning CLI with boustrophedon algorithm

## Project Overview

Waypoint mission planning tool (`nav-plan`) for the Skyridge autonomous mower fleet. Takes KML polygon boundaries as input and generates QGC WPL 110 `.waypoints` files for ArduPilot Rover missions.

**CLI entry point:** `nav-plan mow <kml_file> --width <inches> [-o output]`

**Dependencies:** typer, rich, shapely (runtime); pytest, pytest-mock (dev). Managed with `uv` + `hatchling`.

## Architecture

| Module | Lines | Role |
|---|---|---|
| `polygon.py` | 179 | KML parsing, lat/lon ↔ XY projection, spine extraction, auto-heading |
| `contour.py` | 102 | Contour-following parallel offset path generation (current algorithm) |
| `boustrophedon.py` | 180 | Boustrophedon sweep path generation (superseded, still present) |
| `waypoints.py` | 55 | QGC WPL 110 read/write |
| `cli.py` | 75 | Typer CLI — `mow` command |
| **Total source** | **594** | |
| **Total tests** | **464** | 41 tests, all passing |

### Pipeline Flow

```
KML file → parse_kml_file() → to_xy() → extract_spine()
         → generate_contour_paths() → to_latlon() → write_waypoints()
```

## Completed Work (OpenSpec: replace-boustrophedon-with-contour-paths)

All tasks completed:

1. **Spine extraction** — `extract_spine()` added to `polygon.py`. Walks polygon vertices from index 0 until encountering a >= 90° turn. This defines the primary mow corridor direction.

2. **Contour path generation** — New `contour.py` module. Generates parallel offsets of the spine using Shapely `offset_curve()`, clipped to the polygon boundary. Automatically determines which side of the spine faces the polygon interior.

3. **CLI update** — `--width` now accepts inches (converted internally to meters). Removed `--overlap` and `--heading` options that were boustrophedon-specific. Output creates per-mower waypoint files (`_mower1.waypoints`, `_mower2.waypoints`, etc.) when multiple paths are generated.

4. **Integration verified** — 41 tests passing. Manual test with `input/700.kml` produced 41 mower paths at 21" width.

## Current Working Tree State

### Unstaged modifications (6 files, +334 / -136 lines)

These represent the contour-paths work applied on top of the last commit:

- `src/nav_planning/boustrophedon.py` — minor additions (still present, no longer called by CLI)
- `src/nav_planning/cli.py` — switched from boustrophedon to contour pipeline
- `src/nav_planning/polygon.py` — added `extract_spine()` and supporting geometry
- `tests/test_boustrophedon.py` — expanded tests
- `tests/test_cli.py` — updated for new CLI interface
- `tests/test_polygon.py` — spine extraction tests

### Untracked files

- `input/` — KML test files (`700.kml`, `700_long.kml`)
- `output/` — Generated waypoint files (`700.waypoints`)
- `src/nav_planning/contour.py` — New contour path module
- `tests/test_contour.py` — Contour path tests
- `openspec/changes/replace-boustrophedon-with-contour-paths/` — Change proposal + tasks

## Key Design Decisions

- **Contour over boustrophedon:** Skyridge mowing corridors are narrow and very long (miles). Contour-following paths run the full corridor length with minimal turns, vs. boustrophedon which generates short cross-strips and excessive turning.
- **Width in inches:** Mower cutting decks are specced in inches (e.g., 21"). The CLI accepts inches and converts internally.
- **One mower per path:** Each parallel offset becomes a separate mower's mission. No path splitting or multi-strip assignment.
- **Spine-based offsets:** The spine (first long edge of the KML polygon) defines path direction. Offsets are computed inward from the spine until they no longer intersect the polygon.

## Open Items

- `boustrophedon.py` is still in the codebase — unused by CLI, could be removed or kept for future alternative mode
- Working tree changes are **not committed** — the contour-paths implementation is complete but not yet staged/committed
- No linter or formatter configured
- No integration tests against real hardware or ArduPilot SITL
