# Change: Add boustrophedon mow planning CLI

## Why
The Skyridge fleet needs a tool to generate waypoint missions for autonomous mowing. Existing tools (PrecisionMule.com, Mission Planner survey grid) are either unmaintained or require a full GUI. A CLI tool enables scripted, repeatable mission generation for fleet provisioning.

## What Changes
- New standalone Python project `nav_planning` with CLI entry point `nav-plan`
- `nav-plan mow` command: takes an ArduPilot .poly boundary file and generates a boustrophedon (parallel strips) waypoint path
- Outputs QGC WPL 110 .waypoints files loadable by Mission Planner and QGroundControl
- Configurable strip width, overlap percentage, and heading angle (auto-detected from longest polygon edge by default)

## Impact
- Affected specs: new `mow-planning` capability (no existing specs)
- Affected code: entirely new project at `/Users/jeff/code/skyridge/blueos/nav_planning/`
- No impact on existing `mower_provisioner` project
