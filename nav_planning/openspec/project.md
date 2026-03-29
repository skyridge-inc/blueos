# Project Context

## Purpose
Navigation planning tools for the Skyridge autonomous mower fleet. Generates waypoint missions from boundary polygons for ArduPilot Rover vehicles running on BlueOS.

## Tech Stack
- Python 3.11+
- Typer (CLI framework)
- Rich (terminal UI)
- Shapely >= 2.0 (polygon geometry)
- hatchling (build system)
- uv (package manager)
- pytest (testing)

## Project Conventions

### Code Style
- Follow existing mower_provisioner patterns (sibling project)
- Type hints on all public functions
- No linter/formatter configured yet

### Architecture Patterns
- CLI entry point in `cli.py` using Typer
- Pure logic modules with no CLI dependencies (polygon.py, boustrophedon.py, waypoints.py)
- CLI wires user input to logic modules

### Testing Strategy
- pytest with no fixtures framework beyond standard
- Unit tests for each module
- Test with known polygon geometries and verify waypoint output

### Git Workflow
- Feature branches, conventional commits
- Part of the blueos monorepo

## Domain Context
- ArduPilot Rover firmware on Pixhawk controllers (CubeOrange+)
- QGC WPL 110 waypoint file format (Mission Planner / QGroundControl)
- ArduPilot .poly polygon files (one "lat lon" per line, space-separated)
- Boustrophedon = back-and-forth parallel strip coverage pattern
- Mower deck width determines strip spacing (e.g., 0.53m)
- GPS coordinates in WGS84 (decimal degrees)

## Important Constraints
- Output must be loadable by Mission Planner and QGroundControl
- Waypoint format: MAV_CMD_NAV_WAYPOINT (cmd 16), MAV_FRAME_GLOBAL_RELATIVE_ALT (frame 3)
- Equirectangular projection is sufficient at lawn scale (< 1km)
- No heavy C++ dependencies — pure Python + shapely only

## External Dependencies
- None (offline tool, generates files only)
