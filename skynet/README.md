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
with `skynet pixhawk write <sidecar> --yes --include-calibration`.

## Commands

| Command | Description |
|---------|-------------|
| `connect` | Test connection, display heartbeat info |
| `read` | Fetch all params, display or save to file |
| `write FILE` | Write all params from file to device |
| `diff FILE` | Show differences between file and device |
| `sync FILE` | Smart sync — write only changed/added params |
| `backup` | Full backup to timestamped file |

### BlueOS host provisioning (`skynet config`)

| Command | Description |
|---------|-------------|
| `config download HOST [-o NAME]` | Snapshot a BlueOS host to `./config/<hostname>.yaml` (identity, extensions, bag, network, WiFi pins, hotspot, DHCP reservations, MediaMTX config, autopilot params that differ from `autopilot_base.yaml`) |
| `config upload HOST FILE` | Provision a BlueOS host from that YAML |

`config download` always writes into `./config/` (run it from `skynet/`). The file is named
after the device's BlueOS hostname, e.g. `config/sky1.yaml`, unless `-o NAME` gives another file
name. It never writes `autopilot_base.yaml`. Each download rewrites the whole file, so YAML
comments are not kept. It never records DHCP-client leases (`mode: client`, e.g. eth0 behind
Starlink): those addresses are always dynamic. Reach a rover by its NetBird name
(`<host>.netbird.cloud`) instead.

`config upload` applies, in order:

1. Hostname, vehicle name, bag entries
2. **Extensions** — installs any `extensions:` entry whose identifier/tag is not already installed
3. MediaMTX config file
4. `network.ethernet` addresses — `mode: unmanaged` → static IP; `mode: server` → BlueOS DHCP server on that interface (leases `.101`–`.200`)
5. **`network.dhcp_reservations`** — writes `/etc/blueos/dnsmasq.conf` on the host and bind-mounts it over `/etc/dnsmasq.conf` in `blueos-core` (via `/root/.config/blueos/bootstrap/startup.json`, backed up first)
6. **Autopilot hot-plug start** — `autopilot_autostart: true|false` installs/removes a udev rule
   + one-shot systemd service on the host (see below)
7. Autopilot parameters over MAVLink (`tcp:HOST:5760`): the fleet base plus the YAML's own
   `autopilot_params` (see below). Starts the BlueOS autopilot first if no board is running.
8. **WiFi** — for each `network.wifi_saved` SSID not already saved on the device, prompts for the
   password (hidden, entered twice; blank skips) at the start of the run, then connects at the end.
   Passwords are never written to the YAML. Joining a new network switches `wlan0` immediately, so a
   device reached over a different WiFi may drop off until it reappears on the new network.
   Entries with `interface` and/or `band` are then pinned in the host's NetworkManager profile and
   reconnected (see below).
9. **Hotspot** — `network.hotspot: true|false` turns the BlueOS hotspot on or off (saved by BlueOS)
10. **Reboot** — if step 5 changed anything, the host reboots so `blueos-core` is recreated with the bind mount

#### Autopilot not running in BlueOS

BlueOS's autopilot manager tries to start the autopilot at boot, retries 10 times 5 s apart, then
gives up until someone presses Start. A flight controller plugged in (or powered) after that shows
under available boards but MAVLink (port 5760) is never served. skynet handles this two ways:

- `config upload` (when writing params) and `config download` check
  `GET /ardupilot-manager/v1.0/board` and call `POST /start` when no board is running.
- `autopilot_autostart: true` installs `/etc/udev/rules.d/90-skynet-autopilot.rules`, which runs
  `skynet-autopilot-start.service` when a CubePilot/ArduPilot/Holybro/3DR USB board appears. The
  script waits for the board to leave its bootloader, then starts the autopilot only if none is
  running and it wasn't stopped in BlueOS (`start_on_boot: false`). Check it with
  `journalctl -u skynet-autopilot-start`. Download records whether it is installed.

#### Autopilot params: fleet base + per-rover overrides

`config/autopilot_base.yaml` holds the ArduPilot params shared by the whole fleet. A rover YAML's
`autopilot_params` only lists what differs for that rover — usually nothing:

```yaml
# config/sky2.yaml
autopilot_params:
  GPS1_TYPE: 5        # overrides the base value
  SERIAL4_BAUD: 230   # not in the base: added
```

- **upload** loads `autopilot_base.yaml` from the rover YAML's directory, applies the rover's
  `autopilot_params` on top (rover wins), then filters calibration params as usual. `--dry-run`
  marks rover-sourced values with `(rover)`.
- **download** writes only params that differ from `config/autopilot_base.yaml`, or are missing
  from it, so a re-download shows the rover's real differences. Without a base file it writes
  every param. It updates `autopilot_params` only when the autopilot responds. If the Pixhawk is
  offline, the file keeps its existing `autopilot_params`, and a new file gets none.
- `--base PATH` picks a different base file. With no base file, both commands behave as before.

**Deadman and E-stop:** the base sets ch5 as a hold-to-run switch (released → Hold), and the RC
failsafe to Hold. The E-stops cut the receiver's power, so the RC failsafe doubles as E-stop
feedback. With the mixed-mode track controller, ArduPilot E-stop and disarm do not stop steering,
so the primary stop is hardware: the deadman relay and wireless E-stop sit in series with the
rover's E-stop on its 12 V and 24 V leads. Read [`docs/DEADMAN.md`](docs/DEADMAN.md)
([wiring](docs/safety-chain.svg), [coverage](docs/stop-coverage.svg)) before field use; reboot the
Cube after uploading the base.

To change a param for the whole fleet, edit `autopilot_base.yaml`. Calibration params
(`CALIBRATION_PARAMS`) are vehicle-specific and don't belong in the base.

#### Second WiFi adapter: hotspot on the built-in radio, client on USB

BlueOS's wifi-manager runs its hotspot (`uap0`) on the first WiFi radio — the Pi's built-in
`wlan0` — and saves every client network pinned to `wlan0`. On one radio the two fight over the
channel. With a USB WiFi adapter (`wlan1`), pin the client network to it:

```yaml
network:
  wifi_saved:
  - ssid: '007'
    interface: wlan1   # NetworkManager connection.interface-name
    band: bg           # bg = 2.4 GHz only (longer range), a = 5 GHz only; omit for either
  hotspot: true        # BlueOS hotspot stays on wlan0
```

`config download` records `interface`/`band` from the host profile. Upload only changes
the keys that are present. The BlueOS WiFi page reports `wlan0` only, so it shows the client as
disconnected, and connecting a pinned network from that page will fail — use
`config upload` (or `nmcli`) instead.

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
