# param-management Specification

## Purpose
Read, write, compare, and persist ArduPilot parameters between `.param` files on disk and the autopilot device over MAVLink, with calibration parameters protected from accidental overwrite during fleet provisioning.

## Requirements

### Requirement: Param File Loading
The system SHALL load `.param` files into a `dict[str, float]` mapping. The loader SHALL accept both comma-separated (`NAME,value`) and whitespace-separated (`NAME value`) formats on a per-line basis. Lines beginning with `#` SHALL be treated as comments and skipped. Blank lines SHALL be skipped. By default, parameter names present in `CALIBRATION_PARAMS` SHALL be filtered out; passing `include_calibration=True` SHALL include them.

#### Scenario: Comma-separated format
- **WHEN** a `.param` file containing `CRUISE_SPEED,2` is loaded
- **THEN** the resulting dict contains `{"CRUISE_SPEED": 2.0}`

#### Scenario: Whitespace-separated format
- **WHEN** a `.param` file containing `WP_RADIUS 3` is loaded
- **THEN** the resulting dict contains `{"WP_RADIUS": 3.0}`

#### Scenario: Comments and blank lines
- **WHEN** a `.param` file mixes `#` comment lines and blank lines with parameter lines
- **THEN** only parameter lines contribute to the result; comments and blanks are ignored

#### Scenario: Calibration filtered by default
- **WHEN** a `.param` file contains both `CRUISE_SPEED,2` and `COMPASS_OFS_X,0.5`
- **AND** the file is loaded with the default `include_calibration=False`
- **THEN** only `CRUISE_SPEED` appears in the result; `COMPASS_OFS_X` is filtered

#### Scenario: Calibration retained on opt-in
- **WHEN** the same file is loaded with `include_calibration=True`
- **THEN** both `CRUISE_SPEED` and `COMPASS_OFS_X` appear in the result

#### Scenario: Malformed line
- **WHEN** a `.param` file contains a line that has no separator (e.g. `JUSTANAME`)
- **THEN** `ParamFileError` is raised, identifying the file path and line number

#### Scenario: Non-numeric value
- **WHEN** a `.param` file contains `CRUISE_SPEED,fast`
- **THEN** `ParamFileError` is raised, identifying the offending value

#### Scenario: Unreadable file
- **WHEN** the target file does not exist or cannot be opened
- **THEN** `ParamFileError` is raised, wrapping the original `OSError`

### Requirement: Param File Saving
The system SHALL write a parameter dict to a `.param` file in comma-separated format, with parameter names sorted alphabetically. Integer-valued floats SHALL be written without a decimal point (e.g. `3` not `3.0`) when their absolute value is below `2**31`; other floats SHALL be written using Python's default float formatting. The output file SHALL end with a trailing newline. The system SHALL create any missing parent directories. By default, calibration parameters SHALL be included in the output (`include_calibration=True`); callers MAY pass `include_calibration=False` to filter them.

#### Scenario: Integer formatting
- **WHEN** the dict `{"CRUISE_SPEED": 2.0, "WP_RADIUS": 3.0}` is saved
- **THEN** the file contains `CRUISE_SPEED,2` and `WP_RADIUS,3` (no `.0` suffix)

#### Scenario: Float formatting
- **WHEN** the dict `{"NAVL1_PERIOD": 8.5}` is saved
- **THEN** the file contains `NAVL1_PERIOD,8.5`

#### Scenario: Sorted output
- **WHEN** the dict `{"WP_RADIUS": 3.0, "CRUISE_SPEED": 2.0}` is saved
- **THEN** the lines appear in alphabetical order: `CRUISE_SPEED` before `WP_RADIUS`

#### Scenario: Calibration filtering on save
- **WHEN** a dict containing both `CRUISE_SPEED` and `COMPASS_OFS_X` is saved with `include_calibration=False`
- **THEN** only `CRUISE_SPEED` appears in the output file

#### Scenario: Parent directory creation
- **WHEN** the output path's parent directory does not exist
- **THEN** the parent directory is created before writing

#### Scenario: Write failure
- **WHEN** the target path cannot be written (e.g. permission denied)
- **THEN** `ParamFileError` is raised, wrapping the original `OSError`

### Requirement: Calibration Parameter Set
The system SHALL define `CALIBRATION_PARAMS` as a frozenset of parameter names that are vehicle-specific and MUST NOT be overwritten during fleet provisioning unless explicitly opted in. The set SHALL include IMU offsets and scales (`INS_ACC*`, `INS_GYR*`), compass offsets/diagonals/off-diagonals/motor compensation (`COMPASS_*`), battery voltage/current calibration (`BATT*_VOLT_MULT`, `BATT*_AMP_*`), RC channel min/max/trim values (`RC1`–`RC8`), the system identifier `SYSID_THISMAV`, runtime statistics (`STAT_*`), barometer ground pressure (`BARO*_GND_PRESS`), and gyro calibration temperatures (`INS_GYR*_CALTEMP`).

#### Scenario: IMU calibration is protected
- **WHEN** any of `INS_ACCOFFS_X`, `INS_GYROFFS_Z`, `INS_ACC2SCAL_Y` is checked for membership
- **THEN** the parameter is in `CALIBRATION_PARAMS`

#### Scenario: Compass calibration is protected
- **WHEN** any of `COMPASS_OFS_X`, `COMPASS_DIA_Y`, `COMPASS_MOT_Z` is checked
- **THEN** the parameter is in `CALIBRATION_PARAMS`

#### Scenario: Battery and RC calibration are protected
- **WHEN** `BATT_VOLT_MULT`, `BATT2_AMP_OFFSET`, `RC1_MIN`, `RC8_TRIM` are checked
- **THEN** all are in `CALIBRATION_PARAMS`

#### Scenario: Runtime statistics are protected
- **WHEN** `STAT_BOOTCNT`, `STAT_RUNTIME`, `BARO1_GND_PRESS`, `INS_GYR1_CALTEMP` are checked
- **THEN** all are in `CALIBRATION_PARAMS` (these change every boot and would otherwise generate spurious diffs)

#### Scenario: Tunable params are not protected
- **WHEN** typical tunable parameters such as `CRUISE_SPEED`, `WP_RADIUS`, or `NAVL1_PERIOD` are checked
- **THEN** none are in `CALIBRATION_PARAMS`

### Requirement: Parameter Fetch with Gap Detection
The system SHALL fetch all parameters from a connected MAVLink device using index-based gap detection rather than a simple request-and-wait. The system SHALL send a `PARAM_REQUEST_LIST`, then collect `PARAM_VALUE` messages, tracking received indices against the `param_count` reported by the device. When more than `GAP_TIMEOUT` (2.0 seconds) elapses without a new message, the system SHALL re-request missing parameter indices in batches of up to 10 via `PARAM_REQUEST_READ`. The fetch SHALL complete when all `param_count` indices have been received. An overall `timeout` (default 30.0 seconds) SHALL bound the operation; on timeout, `ParameterFetchError` SHALL be raised. An optional `progress_callback(received, total)` SHALL be invoked after each received message.

#### Scenario: All params arrive in order
- **WHEN** the device streams all `PARAM_VALUE` messages without loss
- **THEN** `fetch_all_params()` returns a dict containing every parameter, keyed by decoded UTF-8 name

#### Scenario: Dropped messages re-requested
- **WHEN** the device reports `param_count=100` but only indices 0–95 and 97–99 arrive in the first burst
- **AND** more than 2 seconds elapse without further messages
- **THEN** the system sends `PARAM_REQUEST_READ` for index 96
- **AND** when index 96 arrives, the fetch completes

#### Scenario: Param name decoding
- **WHEN** a `PARAM_VALUE` message arrives with `param_id` as null-padded bytes (e.g. `b"CRUISE_SPEED\x00\x00\x00\x00"`)
- **THEN** the resulting dict key is the trimmed UTF-8 string `"CRUISE_SPEED"`

#### Scenario: Progress callback
- **WHEN** a `progress_callback` is provided
- **THEN** it is called after every received `PARAM_VALUE` with `(len(params), param_count)`

#### Scenario: Overall timeout
- **WHEN** the total elapsed time exceeds the `timeout` argument
- **THEN** `ParameterFetchError` is raised, including the count received so far

### Requirement: Parameter Write with Acknowledgement
The system SHALL write each parameter individually using `PARAM_SET` with type `MAV_PARAM_TYPE_REAL32`, then wait for a matching `PARAM_VALUE` ack identified by parameter name. Each write SHALL be retried up to `WRITE_RETRIES` (3) times before failing. While waiting for the matching ack, unrelated `PARAM_VALUE` messages SHALL be drained without consuming the retry budget. By default the write SHALL filter out parameters in `CALIBRATION_PARAMS`; `include_calibration=True` SHALL bypass that filter. A `dry_run=True` argument SHALL return the list of parameter names that would be written without sending any MAVLink traffic. An optional `progress_callback(written, total)` SHALL be invoked after each successful write. On exhausted retries, `ParameterWriteError` SHALL be raised identifying the failing parameter and value.

#### Scenario: Successful write
- **WHEN** `write_params(conn, {"CRUISE_SPEED": 2.0})` is called and the device acknowledges
- **THEN** the function returns `["CRUISE_SPEED"]`

#### Scenario: Calibration filtered by default
- **WHEN** `write_params(conn, {"CRUISE_SPEED": 2.0, "COMPASS_OFS_X": 0.5})` is called with the default `include_calibration=False`
- **THEN** only `CRUISE_SPEED` is sent over MAVLink and only it appears in the returned list

#### Scenario: Calibration written on opt-in
- **WHEN** the same call is made with `include_calibration=True`
- **THEN** both parameters are sent and both appear in the returned list

#### Scenario: Retry on missing ack
- **WHEN** the device fails to acknowledge a `PARAM_SET` within 5 seconds on the first attempt
- **THEN** the system resends the same `PARAM_SET` (up to 3 attempts total)
- **AND** the write succeeds if any retry receives a matching ack

#### Scenario: Failure after exhausted retries
- **WHEN** all 3 attempts fail to receive a matching ack
- **THEN** `ParameterWriteError` is raised, identifying the parameter name and value

#### Scenario: Unrelated acks ignored
- **WHEN** the device sends `PARAM_VALUE` messages for other parameters while waiting for the ack of the current write
- **THEN** those messages are drained and the system continues waiting for the matching ack until the per-attempt deadline

#### Scenario: Dry run
- **WHEN** `write_params(..., dry_run=True)` is called
- **THEN** no MAVLink traffic is sent
- **AND** the function returns the list of parameter names that would have been written (after calibration filtering)

#### Scenario: Progress callback
- **WHEN** a `progress_callback` is provided
- **THEN** it is invoked with `(i+1, total)` after each successful parameter write

### Requirement: Parameter Diffing
The system SHALL compute the difference between a `file_params` dict (loaded from disk) and a `device_params` dict (fetched from device), returning a `ParamDiff` dataclass with three fields: `added` (in file but not on device), `changed` (in both, but values differ), and `removed` (on device but not in file). Float comparison SHALL use a tolerance of `EPSILON = 1e-6` (overridable via the `epsilon` keyword). By default, calibration parameters SHALL be excluded from all three buckets; passing `include_calibration=True` SHALL include them. The `ParamDiff` dataclass SHALL expose `has_differences` (bool) and `total_changes` (int) properties.

#### Scenario: New params on file
- **WHEN** the file contains `{"NEW_PARAM": 1.0}` and the device contains `{}`
- **THEN** `result.added == {"NEW_PARAM": 1.0}`, `result.changed == {}`, `result.removed == {}`

#### Scenario: Changed values
- **WHEN** the file contains `{"CRUISE_SPEED": 2.5}` and the device contains `{"CRUISE_SPEED": 2.0}`
- **THEN** `result.changed == {"CRUISE_SPEED": (2.5, 2.0)}`

#### Scenario: Float tolerance
- **WHEN** the file contains `{"CRUISE_SPEED": 2.0}` and the device contains `{"CRUISE_SPEED": 2.0000001}`
- **THEN** the difference is below the default `1e-6` epsilon and `result.changed` is empty

#### Scenario: Removed params
- **WHEN** the file contains `{}` and the device contains `{"OLD_PARAM": 1.0}`
- **THEN** `result.removed == {"OLD_PARAM": 1.0}`

#### Scenario: Calibration excluded by default
- **WHEN** the file and device differ only on `COMPASS_OFS_X`
- **THEN** with default `include_calibration=False`, `result.has_differences` is `False`

#### Scenario: Calibration included on opt-in
- **WHEN** the same comparison is run with `include_calibration=True`
- **THEN** the `COMPASS_OFS_X` discrepancy appears in `result.changed`

#### Scenario: Diff summary properties
- **WHEN** `result.added`, `result.changed`, and `result.removed` together contain 5 entries
- **THEN** `result.has_differences` is `True` and `result.total_changes` is `5`
