# provisioning-cli Specification

## Purpose
A Typer-based command-line tool (`mower-provision`, also exposed under the app name `skynet`) for provisioning ArduPilot Rover/Mower autopilots and BlueOS companion computers. Composes the `mavlink-connection`, `param-management`, and `blueos-config` capabilities into eight user-facing commands with consistent shared options and Rich-based terminal output.

## Requirements

### Requirement: Top-Level Application
The system SHALL expose a Typer application named `skynet` registered as the `mower-provision` console script. Invoking the CLI with no arguments SHALL show the help text. A `--version` / `-V` flag SHALL print the package version and exit.

#### Scenario: No arguments shows help
- **WHEN** `mower-provision` is run without arguments
- **THEN** the help text is printed and the process exits non-zero

#### Scenario: Version flag
- **WHEN** `mower-provision --version` is run
- **THEN** the package version is printed and the process exits zero

### Requirement: Shared Options
The system SHALL define a common set of options reused across MAVLink commands: `--device` / `-d` (default `/dev/ttyACM0`, overridable via the `MOWER_DEVICE` environment variable), `--baud` / `-b` (default 115200), and `--include-calibration` (default `False`). MAVLink-mutating commands SHALL also accept `--dry-run` and `--yes` / `-y` (skip confirmation prompt).

#### Scenario: Device from environment variable
- **WHEN** `MOWER_DEVICE=/dev/ttyUSB0` is set in the environment and a command is run without `--device`
- **THEN** the command connects to `/dev/ttyUSB0`

#### Scenario: Confirmation skipped
- **WHEN** a destructive command is run with `--yes`
- **THEN** no confirmation prompt is shown before the operation proceeds

### Requirement: connect Command
The `connect` command SHALL open a MAVLink connection, retrieve the heartbeat, and display a Rich table with Device, System ID, Component ID, Vehicle Type (decoded via `get_vehicle_type_name`), Autopilot, and Base Mode. On success it SHALL print a green "Connection successful!" message.

#### Scenario: Successful connection
- **WHEN** the user runs `mower-provision connect -d /dev/ttyACM0`
- **THEN** the CLI prints a Connection Info table with the device, system/component IDs, and vehicle type
- **AND** prints a green success message

### Requirement: read Command
The `read` command SHALL fetch all parameters from the device and either save them to a file (when `--output` / `-o` is provided) or print them in a Rich table sorted alphabetically. A progress bar SHALL be displayed during the fetch. The `--include-calibration` flag SHALL apply to the file save (the table display always shows everything that was fetched).

#### Scenario: Display only
- **WHEN** the user runs `mower-provision read` without `--output`
- **THEN** all fetched params are shown in a sorted Rich table

#### Scenario: Save to file
- **WHEN** the user runs `mower-provision read -o current.param`
- **THEN** the parameters are saved to `current.param`
- **AND** the count of received parameters is printed

#### Scenario: Calibration excluded by default in save
- **WHEN** the user runs `mower-provision read -o current.param` without `--include-calibration`
- **THEN** the saved file omits calibration parameters

### Requirement: write Command
The `write` command SHALL load parameters from a `.param` file argument and write them to the device. Without `--yes`, the user SHALL be prompted to confirm before any writes are made. With `--dry-run`, the command SHALL print every parameter that would be written and return without contacting the device. A progress bar SHALL be displayed during writes. On success, the count of written parameters SHALL be reported.

#### Scenario: Dry run
- **WHEN** the user runs `mower-provision write template.param --dry-run`
- **THEN** every parameter that would be written is printed
- **AND** no MAVLink connection is opened

#### Scenario: Confirmation prompt
- **WHEN** the user runs `mower-provision write template.param` without `--yes`
- **THEN** the user is prompted to confirm before writes begin
- **AND** declining aborts the command

#### Scenario: Confirmation skipped
- **WHEN** the user runs `mower-provision write template.param --yes`
- **THEN** writes proceed without prompting

#### Scenario: Calibration excluded by default
- **WHEN** the user runs `mower-provision write template.param --yes`
- **THEN** parameters in `CALIBRATION_PARAMS` are filtered before sending

### Requirement: diff Command
The `diff` command SHALL load a `.param` file, fetch device parameters, compute the diff via `diff_params`, and display the result as a Rich table with rows tagged `ADD` (green), `CHG` (yellow), or `DEL` (red). A summary line SHALL report the count of each category. When there are no differences, a green "No differences found." message SHALL be printed instead of an empty table.

#### Scenario: Differences shown
- **WHEN** the file and device differ on at least one parameter
- **THEN** the CLI prints a table with appropriate ADD/CHG/DEL rows
- **AND** a summary line reports the totals

#### Scenario: No differences
- **WHEN** the file and device are identical (modulo the calibration filter)
- **THEN** the CLI prints "No differences found."

### Requirement: sync Command
The `sync` command SHALL load a `.param` file, fetch device parameters, compute a diff, and write only the parameters that are added or changed (removed parameters SHALL NOT be deleted from the device). The user SHALL be prompted to confirm before any writes unless `--yes` is passed. With `--dry-run`, the command SHALL print the parameters it would sync without writing. When there are no differences, the command SHALL print "Device is in sync. Nothing to do." and exit. The internal call to `write_params` SHALL pass `include_calibration=True` because the diff has already filtered.

#### Scenario: Sync needed
- **WHEN** the file has 3 added and 2 changed parameters relative to the device
- **AND** `--yes` is passed
- **THEN** all 5 parameters are written to the device
- **AND** parameters present only on the device (not in the file) are not deleted

#### Scenario: Already in sync
- **WHEN** the file matches the device (within calibration filtering)
- **THEN** the CLI prints "Device is in sync. Nothing to do." and exits without writing

#### Scenario: Sync dry run
- **WHEN** the user runs `mower-provision sync template.param --dry-run`
- **THEN** the parameters that would be synced are printed and no writes occur

### Requirement: backup Command
The `backup` command SHALL fetch all parameters from the device (including calibration) and save them to a UTC-timestamped file under the directory given by `--output-dir` / `-o` (default `.`). The filename SHALL match the pattern `backup_YYYYMMDD_HHMMSS.param`. The success message SHALL report the count of backed-up parameters and the absolute path of the file.

#### Scenario: Default output directory
- **WHEN** the user runs `mower-provision backup`
- **THEN** the file `backup_<timestamp>.param` is created in the current directory
- **AND** the file includes all parameters, including calibration

#### Scenario: Custom directory
- **WHEN** the user runs `mower-provision backup --output-dir backups/`
- **THEN** the file is created under `backups/`

### Requirement: extract-config Command
The `extract-config` command SHALL connect to a BlueOS device by URL (a bare host SHALL be normalized to `http://<host>`), call `extract_config`, and write the resulting YAML to a file (default: derived from the URL via `output_filename`). The command SHALL report the number of extensions captured and warn (to stderr) about any top-level keys that came back as `None`. On a connection failure (`BlueOSConnectionError`), the command SHALL print the error to stderr and exit non-zero.

#### Scenario: Successful extraction
- **WHEN** the user runs `mower-provision extract-config blueos.local`
- **THEN** `http://blueos.local` is contacted and the result is written to `blueos.local.yaml`
- **AND** the extension count is printed

#### Scenario: Connection failure
- **WHEN** BlueOS is unreachable
- **THEN** the command prints a red error to stderr and exits with code 1

### Requirement: download Command
The `download` command SHALL combine a BlueOS extraction (HTTP) with an autopilot parameter fetch (MAVLink TCP at port 5760) into a single YAML file. The command SHALL fetch the BlueOS configuration via `extract_config`, then fetch the MediaMTX configuration via `fetch_mediamtx_config` and store it under the `mediamtx` key, then connect to MAVLink at `tcp:<host>:5760` and store the parameters under the `autopilot_params` key (sorted alphabetically). When `--include-calibration` is not passed, calibration parameters SHALL be filtered out of `autopilot_params`. If the MAVLink fetch fails with `MowerProvisionerError`, the command SHALL print a yellow warning to stderr but still write the YAML with `autopilot_params: null`. The output path defaults to `<host>.yaml` and may be overridden via `--output` / `-o`.

#### Scenario: Full download
- **WHEN** the user runs `mower-provision download 192.168.2.2`
- **THEN** the resulting `192.168.2.2.yaml` contains BlueOS config, MediaMTX config, and autopilot parameters

#### Scenario: Calibration filtered by default
- **WHEN** `mower-provision download 192.168.2.2` is run without `--include-calibration`
- **THEN** the `autopilot_params` section excludes calibration parameters

#### Scenario: Autopilot unreachable
- **WHEN** the BlueOS HTTP API is reachable but the MAVLink TCP port is not
- **THEN** a yellow warning is printed to stderr
- **AND** the YAML still saves successfully with `autopilot_params: null`

#### Scenario: BlueOS unreachable
- **WHEN** the BlueOS HTTP API is unreachable on the very first call
- **THEN** the command exits with code 1 after printing a red error to stderr

### Requirement: upload Command
The `upload` command SHALL load a YAML configuration file and apply its writable sections back to a BlueOS device. The command SHALL summarize the changes that will be made before acting and SHALL prompt for confirmation unless `--yes` is passed. With `--dry-run`, the command SHALL print the summary (and the parameter list, if any) and exit without making changes. The applicable sections SHALL be: `hostname` (via `set_hostname`), `vehicle_name` (via `set_vehicle_name`), `bag` entries (via `set_bag` per key), `mediamtx` (via `push_mediamtx_config`), `network.ethernet` static IPs (via `add_ip` for each address whose `mode == "unmanaged"` that is not already present on the device), and `autopilot_params` (via `write_params` over MAVLink TCP at port 5760). If the YAML has no writable sections, a yellow "Nothing to upload" message SHALL be printed and the command SHALL exit. By default, calibration parameters SHALL be filtered out of `autopilot_params` before upload; `--include-calibration` SHALL bypass that filter. Per-section failures SHALL be reported as yellow warnings to stderr but SHALL NOT abort the overall command. A `BlueOSConnectionError` SHALL exit with code 1.

#### Scenario: Full upload
- **WHEN** the user runs `mower-provision upload 192.168.2.2 sky1.yaml --yes`
- **THEN** hostname, vehicle name, bag entries, MediaMTX config, missing static IPs, and autopilot params are all written to the device
- **AND** a single summary line at the end lists each section that was uploaded

#### Scenario: Dry run
- **WHEN** the user runs `mower-provision upload 192.168.2.2 sky1.yaml --dry-run`
- **THEN** the summary of changes is printed
- **AND** the autopilot parameter list is printed
- **AND** no HTTP or MAVLink writes occur

#### Scenario: Empty YAML
- **WHEN** the user uploads a YAML file with none of the writable sections populated
- **THEN** the CLI prints a yellow "Nothing to upload" message and exits without contacting the device

#### Scenario: Idempotent static IPs
- **WHEN** an unmanaged IP listed in the YAML is already configured on the device's matching interface
- **THEN** that IP is counted as success and not re-POSTed

#### Scenario: Calibration filtered by default
- **WHEN** the YAML's `autopilot_params` includes calibration entries
- **AND** `--include-calibration` is not passed
- **THEN** calibration entries are filtered before the MAVLink writes

#### Scenario: Per-section failure non-fatal
- **WHEN** the hostname set succeeds but the bag write fails for a single key
- **THEN** a yellow warning is printed to stderr
- **AND** the remaining sections still attempt to upload

#### Scenario: Confirmation prompt
- **WHEN** the user runs `mower-provision upload 192.168.2.2 sky1.yaml` without `--yes`
- **THEN** a confirmation prompt is shown after the summary
- **AND** declining aborts the command

### Requirement: nav-plan Command
The `nav-plan` command SHALL generate contour-following mowing missions from a KML polygon boundary file by composing the `mission-planning` capability. It SHALL accept a positional `kml_file` argument and a required `--width` / `-w` option in inches. It SHALL accept an optional `--output` / `-o` base path; when omitted, the base path SHALL be the input KML path with its extension stripped. It SHALL accept three independent visualization flags: `--visualize` (HTML map), `--kml-track` (Google Earth track), and `--kml-tour` (Google Earth tour). The command SHALL print, in order: the polygon vertex count, the spine vertex count, the mower width in both inches and meters, the number of mowers required, the path of each `.waypoints` file written, and the path of any visualization file generated. The command MUST NOT open any MAVLink or HTTP connection — it is purely a file-to-file operation.

#### Scenario: Minimal invocation
- **WHEN** the user runs `mower-provision nav-plan field.kml --width 21`
- **THEN** the command parses `field.kml`, generates contour-following paths at 21 inches (0.5334 m) spacing, and writes one or more `.waypoints` files next to the input
- **AND** no MAVLink or HTTP connection is opened

#### Scenario: Custom output base
- **WHEN** the user runs `mower-provision nav-plan field.kml --width 21 -o /tmp/mission`
- **THEN** waypoint files are written under `/tmp/mission` (e.g. `/tmp/mission.waypoints` or `/tmp/mission_mowerN.waypoints`) regardless of any extension on `-o`

#### Scenario: Multi-mower output naming
- **WHEN** the polygon admits more than one contour path
- **THEN** files are named `<base>_mower1.waypoints` … `<base>_mowerN.waypoints` and the CLI prints "Mowers required: N" along with each written path

#### Scenario: All visualization flags together
- **WHEN** the user runs `mower-provision nav-plan field.kml --width 21 --visualize --kml-track --kml-tour`
- **THEN** the command additionally writes `<base>.html`, `<base>_track.kml`, and `<base>_tour.kml`
- **AND** the `.waypoints` file contents are unchanged versus an invocation without those flags

#### Scenario: Polygon too narrow
- **WHEN** the polygon cannot accommodate even a single contour path at the requested width
- **THEN** the CLI prints a red error indicating the polygon may be too narrow for the mower width and exits with non-zero status

#### Scenario: Missing required width
- **WHEN** the user runs `mower-provision nav-plan field.kml` without `--width`
- **THEN** Typer prints an error indicating `--width` is required and exits non-zero

### Requirement: Exception Mapping
The system SHALL define an exception hierarchy rooted at `MowerProvisionerError`, with three independent branches: `ConnectionError` (with subclass `HeartbeatTimeout`), `ParameterError` (with subclasses `ParameterFetchError` and `ParameterWriteError`), `ParamFileError`, and `BlueOSError` (with subclass `BlueOSConnectionError`). All exceptions raised by the library SHALL inherit from `MowerProvisionerError`.

#### Scenario: Catch-all
- **WHEN** any library function raises an exception
- **THEN** that exception is an instance of `MowerProvisionerError`

#### Scenario: Heartbeat timeout is a connection error
- **WHEN** `HeartbeatTimeout` is raised
- **THEN** it is also catchable as `ConnectionError` and `MowerProvisionerError`
