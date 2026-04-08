# blueos-config Specification

## Purpose
Extract a BlueOS companion-computer's provisionable configuration to a YAML file and apply a YAML file back to a device. Captures only fields that meaningfully define a fleet vehicle (identity, installed extensions, network static IPs, extension settings, MediaMTX RTSP relay config) while explicitly excluding ephemeral runtime state and per-user UI preferences.

## Requirements

### Requirement: BlueOS HTTP Client
The system SHALL provide a `BlueOSClient` HTTP wrapper around the BlueOS REST API surface. The client SHALL be usable as a context manager that closes the underlying `httpx.Client` on exit. The client SHALL accept a `base_url` and an optional `httpx.Timeout`. URLs ending in `/` SHALL have the trailing slash stripped. The client SHALL distinguish between a hard connection failure on the very first request (raised as `BlueOSConnectionError`) and per-endpoint failures after at least one successful call (returned as `None` / `False` so partial extraction can continue).

#### Scenario: Context manager closes client
- **WHEN** `BlueOSClient(url)` is used inside a `with` block
- **THEN** the underlying `httpx.Client` is closed on exit

#### Scenario: First-request connection failure
- **WHEN** the very first endpoint call fails with `httpx.ConnectError`
- **THEN** `BlueOSConnectionError` is raised, identifying the base URL

#### Scenario: Partial reachability
- **WHEN** an early endpoint succeeds but a later endpoint returns an HTTP 404 or fails to parse as JSON
- **THEN** the failing call returns `None` and subsequent calls may still succeed

### Requirement: Identity Endpoints
The client SHALL expose `get_hostname()` and `get_vehicle_name()` returning the values from BlueOS Beacon (`/beacon/v1.0/hostname`, `/beacon/v1.0/vehicle_name`), and `set_hostname(name)` / `set_vehicle_name(name)` returning `True` on success and `False` on failure (POSTing to the same endpoints with the value as a query parameter).

#### Scenario: Read identity
- **WHEN** the device responds to the Beacon hostname endpoint with `"sky1"`
- **THEN** `client.get_hostname()` returns `"sky1"`

#### Scenario: Set identity
- **WHEN** `client.set_vehicle_name("sky1")` succeeds
- **THEN** the call returns `True`

### Requirement: Extensions Endpoint
The client SHALL expose `get_extensions()` returning the list of installed extensions from Kraken v2 (`/kraken/v2.0/extension/`), or `None` if the endpoint is unreachable.

#### Scenario: Extensions list
- **WHEN** the Kraken endpoint returns a JSON array of extension objects
- **THEN** `client.get_extensions()` returns that list as a Python `list`

### Requirement: Bag of Holding Endpoints
The client SHALL expose `get_bag()` returning the entire BlueOS Bag of Holding (`/bag/v1.0/get/*`) as a dict, and `set_bag(key, value)` POSTing JSON to `/bag/v1.0/set/<key>`. When extracting the bag for provisioning, the system SHALL exclude the keys `settings` (UI preferences), `wizard` (setup wizard state), and `cockpit` (per-user Cockpit layouts and the vehicle UUID) because they are ephemeral or per-user.

#### Scenario: Bag retrieval
- **WHEN** the bag endpoint returns `{"settings": {...}, "skyridge": {...}, "cockpit": {...}}`
- **AND** the result is passed through the extraction cleaner
- **THEN** the result contains only the `skyridge` key

#### Scenario: Bag write
- **WHEN** `client.set_bag("skyridge", {"foo": 1})` succeeds
- **THEN** the call returns `True`

### Requirement: Networking Endpoints
The client SHALL expose `get_ethernet()` (`/cable-guy/v1.0/ethernet`), `get_wifi_saved()` (`/wifi-manager/v1.0/saved`), `get_hotspot()` (`/wifi-manager/v1.0/hotspot`), and `add_ip(interface_name, ip_address)` (POST `/cable-guy/v1.0/address`) for adding a static (unmanaged) IP. When extracting ethernet entries for provisioning, the system SHALL strip ephemeral routing/info fields and retain only `name` and `addresses`.

#### Scenario: Ethernet extraction strips ephemera
- **WHEN** the device returns an ethernet interface with fields `name`, `addresses`, `info`, `routes`
- **AND** the result is passed through the extraction cleaner
- **THEN** the cleaned entry contains only `name` and `addresses`

#### Scenario: Add static IP
- **WHEN** `client.add_ip("eth0", "192.168.2.2")` succeeds
- **THEN** the call returns `True`

### Requirement: File Browser Endpoints
The client SHALL access arbitrary files on the device through the BlueOS file browser API (`/file-browser/api/...`). The client SHALL log in once to `/file-browser/api/login` with credentials `admin`/`admin`, cache the returned JWT token across calls, and pass it as the `X-Auth` header on subsequent reads/writes. `get_file(device_path)` SHALL return the file's text content or `None` on failure. `put_file(device_path, content)` SHALL PUT the new content and return `True` on success or `False` on failure. Leading slashes in `device_path` SHALL be stripped.

#### Scenario: Token caching
- **WHEN** `get_file()` is called twice in the same client session
- **THEN** the file browser login endpoint is hit only on the first call

#### Scenario: File read
- **WHEN** `client.get_file("extensions/mediamtx/mediamtx.yml")` succeeds
- **THEN** the function returns the file content as a string

#### Scenario: File write
- **WHEN** `client.put_file("extensions/mediamtx/mediamtx.yml", new_yaml)` succeeds
- **THEN** the function returns `True`

#### Scenario: Auth failure
- **WHEN** the file browser login fails
- **THEN** `get_file()` and `put_file()` return `None` / `False` without retrying the login on every call

### Requirement: MediaMTX Configuration Round-Trip
The system SHALL fetch the MediaMTX configuration from a BlueOS device by trying a list of candidate file paths under the file browser root (defaulting to `extensions/mediamtx/mediamtx.yml`) and parsing the first successful response as YAML. The result SHALL be a dict with two keys: `config_path` (the path that succeeded) and `config` (the parsed YAML mapping). Pushing the configuration back SHALL serialize the `config` dict to YAML using block style (`default_flow_style=False`, `sort_keys=False`, `allow_unicode=True`) and write it to the same `config_path` via the file browser PUT endpoint. If `config_path` is missing or `config` is not a dict, the push SHALL return `False` without writing.

#### Scenario: Default candidate succeeds
- **WHEN** `fetch_mediamtx_config(client)` is called and the default path `extensions/mediamtx/mediamtx.yml` returns valid YAML
- **THEN** the result is `{"config_path": "extensions/mediamtx/mediamtx.yml", "config": <parsed dict>}`

#### Scenario: Caller-provided path
- **WHEN** a `config_path` argument is supplied
- **THEN** that path is tried first instead of the default candidates

#### Scenario: All candidates fail
- **WHEN** every candidate path returns `None` or unparseable YAML
- **THEN** `fetch_mediamtx_config()` returns `None`

#### Scenario: Push round-trip
- **WHEN** `push_mediamtx_config(client, {"config_path": "extensions/mediamtx/mediamtx.yml", "config": {"paths": {}}})` is called
- **THEN** the file browser PUT endpoint receives YAML-serialized content at the same path
- **AND** the function returns `True`

#### Scenario: Malformed input rejected
- **WHEN** `push_mediamtx_config()` is called with a dict missing `config_path` or with a non-dict `config`
- **THEN** the function returns `False` without making any HTTP calls

### Requirement: Configuration Extraction
The system SHALL provide `extract_config(client)` returning a dict with the following provisionable fields, in this exact key order: `hostname`, `vehicle_name`, `extensions`, `bag` (with ephemeral keys removed), `network` (containing `ethernet` with cleaned interfaces, `wifi_saved`, and `hotspot`). Unreachable endpoints SHALL appear as `None`. Runtime state such as version, board, firmware, services, and routes SHALL NOT be included.

#### Scenario: Full extraction
- **WHEN** `extract_config(client)` is called against a fully reachable device
- **THEN** the result dict contains exactly the keys `hostname`, `vehicle_name`, `extensions`, `bag`, `network`
- **AND** `network` contains exactly `ethernet`, `wifi_saved`, `hotspot`

#### Scenario: Partial reachability
- **WHEN** the wifi-manager endpoints return errors
- **THEN** `result["network"]["wifi_saved"]` and `result["network"]["hotspot"]` are `None`
- **AND** other fields are still populated

### Requirement: YAML Persistence
The system SHALL provide `save_yaml(config, path)` that writes a config dict to a YAML file using block style (`default_flow_style=False`, `sort_keys=False`, `allow_unicode=True`), creating any missing parent directories. It SHALL also provide `load_yaml(path)` that reads and parses a YAML file, raising `ParamFileError` if the file cannot be read, the YAML cannot be parsed, or the top-level value is not a mapping.

#### Scenario: Save round-trip
- **WHEN** a config dict is saved with `save_yaml()` and then loaded with `load_yaml()`
- **THEN** the loaded dict equals the original

#### Scenario: Key order preserved on save
- **WHEN** a dict with keys `[hostname, vehicle_name, extensions]` is saved
- **THEN** the YAML file lists those keys in insertion order, not alphabetized

#### Scenario: Invalid YAML on load
- **WHEN** `load_yaml()` is called on a file containing malformed YAML
- **THEN** `ParamFileError` is raised, identifying the file path

#### Scenario: Non-mapping YAML on load
- **WHEN** `load_yaml()` is called on a file whose top-level value is a list or scalar
- **THEN** `ParamFileError` is raised, identifying the actual top-level type

#### Scenario: Missing file on load
- **WHEN** `load_yaml()` is called with a path that does not exist
- **THEN** `ParamFileError` is raised, wrapping the original `OSError`

### Requirement: Output Filename Derivation
The system SHALL derive a default YAML output filename from a target URL by extracting the hostname (or path if hostname is empty) and appending `.yaml`.

#### Scenario: URL with scheme
- **WHEN** `output_filename("http://blueos.local")` is called
- **THEN** the result is `Path("blueos.local.yaml")`

#### Scenario: Bare hostname
- **WHEN** `output_filename("blueos.local")` is called (no scheme)
- **THEN** the result is `Path("blueos.local.yaml")` (the path component is used as fallback)
