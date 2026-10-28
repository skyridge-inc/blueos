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

# Run a HW-in-the-loop GPS/heading simulator so ArduRover flies the uploaded
# mission on a real Pixhawk Cube Orange+ with no real GPS. The simulator
# reads SERVO_OUTPUT_RAW, runs a skid-steer kinematic model, and injects
# GPS_INPUT back to the autopilot. Arm in AUTO from Mission Planner.
skynet nav sim -d tcp:192.168.2.2:5760 --ground-speed 2 --yes
```

**Note on `nav sim`**: the command temporarily rewrites `GPS_TYPE`,
`AHRS_EKF_TYPE`, and `EK3_SRC1_*` params to put the autopilot into external
GPS mode. Originals are saved to a sidecar file at
`~/.config/skynet/sim_restore_<slug>.param` before any mutation and
restored on exit. If the process is killed (`kill -9`) mid-run, recover
with `skynet misc write <sidecar> --yes --include-calibration`.

## Commands

| Command | Description |
|---------|-------------|
| `connect` | Test connection, display heartbeat info |
| `read` | Fetch all params, display or save to file |
| `write FILE` | Write all params from file to device |
| `diff FILE` | Show differences between file and device |
| `sync FILE` | Smart sync — write only changed/added params |
| `backup` | Full backup to timestamped file |

### BlueOS host provisioning (`skynet config_blueos`)

| Command | Description |
|---------|-------------|
| `config_blueos download HOST` | Snapshot a BlueOS host to YAML (identity, extensions, bag, network, DHCP reservations, MediaMTX config, autopilot params) |
| `config_blueos upload HOST FILE` | Provision a BlueOS host from that YAML |

`config_blueos upload` applies, in order:

1. Hostname, vehicle name, bag entries
2. **Extensions** — installs any `extensions:` entry whose identifier/tag is not already installed
3. MediaMTX config file
4. `network.ethernet` addresses — `mode: unmanaged` → static IP; `mode: server` → BlueOS DHCP server on that interface (leases `.101`–`.200`)
5. **`network.dhcp_reservations`** — writes `/etc/blueos/dnsmasq.conf` on the host and bind-mounts it over `/etc/dnsmasq.conf` in `blueos-core` (via `/root/.config/blueos/bootstrap/startup.json`, backed up first)
6. Autopilot parameters over MAVLink (`tcp:HOST:5760`)
7. **WiFi** — for each `network.wifi_saved` SSID not already saved on the device, prompts for the
   password (hidden, entered twice; blank skips) at the start of the run, then connects at the end.
   Passwords are never written to the YAML. Joining a new network switches `wlan0` immediately, so a
   device reached over a different WiFi may drop off until it reappears on the new network.
8. **Reboot** — if step 5 changed anything, the host reboots so `blueos-core` is recreated with the bind mount

```yaml
network:
  ethernet:
  - name: eth1                      # camera NIC
    addresses:
    - {ip: 192.168.10.1, mode: server}
  dhcp_reservations:
  - {mac: 64:35:1c:00:f0:79, ip: 192.168.10.2, hostname: routecam}
mediamtx:
  config:
    paths:
      front:
        source: rtsp://192.168.10.2:5005/routecam
```

Reserved IPs should sit outside the `.101`–`.200` lease pool. Use `--dry-run` to preview.
Host-specific entries (e.g. the `wt0` NetBird address, per-host static IPs) should be removed
from a YAML before using it as a template for a different rover.

### GNSS RTK/heading receiver (`skynet config_gps`)

Plug the receiver's USB port into the machine running skynet. Both commands scan USB serial
ports for a supported receiver (currently Septentrio, USB vendor `0x152A`, e.g. the mosaic-H on
an ArduSimple simpleRTK3B Heading); pass `--port` if several are attached.

| Command | Description |
|---------|-------------|
| `config_gps download [-o FILE]` | Save the receiver's identity and Boot config to YAML (default `gps-<serial>.yaml`) |
| `config_gps upload FILE` | Reset the running config to factory defaults, replay the YAML commands, save to Boot, read back to verify |

The `config:` list is the receiver's own `lstConfigFile, Boot` output (settings that differ from
factory defaults), so it replays verbatim on a replacement receiver.

```yaml
receiver: {vendor: Septentrio, product: mosaic-H, serial: '3806485', firmware: 4.14.4}
config:
- setDataInOut, COM1, , none
- setSBFOutput, Stream3, COM3
- setSBFOutput, Stream3, , AuxAntPositions+BaseVectorGeod+PVTGeodetic+VelCovGeodetic+DOP+ReceiverStatus+AttCovEuler
- setSBFOutput, Stream3, , , msec100
- setCOMSettings, COM1, baud230400
- setCOMSettings, COM3, baud230400
- setGNSSAttitude, , Float+Fixed
```

**sky1 (`config/sky1_gps.yaml`)**: the Cube's TELEM1 TX goes to mosaic COM1 RX but its RX comes
from mosaic COM3 TX, so ArduPilot can't auto-configure the receiver (`GPS_AUTO_CONFIG=0`,
`GPS1_TYPE=26` in `config/sky1.yaml`). The receiver streams SBF on COM3 and takes RTCM
corrections on COM1, both at 230400 — the baud the Cube detects and transmits at.

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
