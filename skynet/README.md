# Mower Provisioner

MAVLink fleet provisioning CLI for ArduPilot Rover/Mower vehicles on Pixhawk controllers.

## Installation

```bash
# Development install
uv sync

# Global tool install
uv tool install .
```

## Quick Start

```bash
# Test connection to Pixhawk
mower-provision connect

# Read all parameters from device
mower-provision read --output current.param

# Show differences between template and device
mower-provision diff templates/mower_base.param

# Sync only changed params to device
mower-provision sync templates/mower_base.param

# Full backup before changes
mower-provision backup --output-dir backups/

# Plan a mowing mission from a KML field boundary
skynet nav plan field.kml --width 21

# Upload a .waypoints mission to the autopilot via the BlueOS MAVLink proxy
skynet nav upload ./output/700_long_mower1.waypoints -d tcp:192.168.2.2:5760 --yes
```

## Commands

| Command | Description |
|---------|-------------|
| `connect` | Test connection, display heartbeat info |
| `read` | Fetch all params, display or save to file |
| `write FILE` | Write all params from file to device |
| `diff FILE` | Show differences between file and device |
| `sync FILE` | Smart sync — write only changed/added params |
| `backup` | Full backup to timestamped file |

## Common Options

- `--device`, `-d` — Connection string (default: `/dev/ttyACM0`, env: `MOWER_DEVICE`)
- `--baud`, `-b` — Serial baud rate (default: 115200)
- `--include-calibration` — Include calibration parameters (excluded by default)
- `--dry-run` — Show what would happen without making changes
- `--yes`, `-y` — Skip confirmation prompts

## Calibration Protection

By default, vehicle-specific calibration parameters (IMU, compass, battery, RC, SYSID) are excluded from read/write/diff/sync operations. This prevents accidentally overwriting sensor calibration when applying fleet templates.

Use `--include-calibration` to include them when needed (e.g., for full backups).

## Development

```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --tb=short -v
```

## Template Format

Standard ArduPilot `.param` format — one parameter per line, comma-separated:

```
CRUISE_SPEED,2
WP_RADIUS,3
NAVL1_PERIOD,8
```

Compatible with Mission Planner, QGroundControl, and MAVProxy.
