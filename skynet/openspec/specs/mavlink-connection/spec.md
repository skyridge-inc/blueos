# mavlink-connection Specification

## Purpose
Manage the lifecycle of a MAVLink connection to an ArduPilot Rover/Mower autopilot, providing a context-managed handle that is guaranteed to have completed a heartbeat handshake before use, and that closes the underlying transport on exit (success or failure).

## Requirements

### Requirement: Connection Context Manager
The system SHALL provide a `mavlink_connection(device, baud, timeout)` context manager that opens a `pymavlink` connection to the given device string, waits for a HEARTBEAT message, populates `target_system` and `target_component` from the heartbeat source, yields the connection, and closes it on exit. The default baud rate SHALL be 115200 and the default heartbeat timeout SHALL be 10 seconds.

#### Scenario: Successful USB serial connection
- **WHEN** `mavlink_connection("/dev/ttyACM0")` is entered and a heartbeat arrives within the timeout
- **THEN** the yielded object's `target_system` and `target_component` are set from the heartbeat's source IDs
- **AND** the underlying MAVLink connection is closed when the context block exits

#### Scenario: Successful TCP connection
- **WHEN** `mavlink_connection("tcp:192.168.2.2:5760")` is entered against a BlueOS device
- **THEN** the same connect → heartbeat → yield → close lifecycle applies

#### Scenario: Cleanup on caller exception
- **WHEN** the caller raises an exception inside the `with` block
- **THEN** the connection is still closed before the exception propagates

### Requirement: Connection Failure Handling
The system SHALL raise `ConnectionError` (a subclass of `MowerProvisionerError`) when the underlying transport cannot be opened, wrapping the original exception as the cause. No partial connection state SHALL leak to the caller on failure.

#### Scenario: Device not present
- **WHEN** the device path does not exist or is otherwise unopenable
- **THEN** `ConnectionError` is raised with a message that includes the device string and the original error
- **AND** no context object is yielded

### Requirement: Heartbeat Timeout
The system SHALL raise `HeartbeatTimeout` (a subclass of `ConnectionError`) when no HEARTBEAT message is received within the configured timeout. Before raising, the system SHALL close the partially-opened MAVLink connection so no file descriptors leak.

#### Scenario: Silent device
- **WHEN** the device opens successfully but never sends a heartbeat
- **THEN** after the timeout elapses, `HeartbeatTimeout` is raised
- **AND** the underlying connection has been closed

### Requirement: Vehicle Type Naming
The system SHALL provide `get_vehicle_type_name(mav_type)` that maps MAVLink `MAV_TYPE` enum integers to human-readable vehicle names. Known mappings SHALL include at least: 0 (Generic), 1 (Fixed Wing), 2 (Quadrotor), 10 (Ground Rover), 11 (Surface Boat). Unknown values SHALL be returned as `Unknown (<n>)`.

#### Scenario: Known vehicle type
- **WHEN** `get_vehicle_type_name(10)` is called
- **THEN** the function returns `"Ground Rover"`

#### Scenario: Unknown vehicle type
- **WHEN** `get_vehicle_type_name(99)` is called
- **THEN** the function returns `"Unknown (99)"`
