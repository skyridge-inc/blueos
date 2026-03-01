# RC and PWM Configuration Management in BlueOS

## Overview

BlueOS 1.5.0 beta 29 uses ArduPilot parameter files to manage PWM input/output configuration for both Linux-based boards (Navigator, Navigator64, Argonot) and serial boards (Pixhawk family). This document explains how to create, edit, and apply parameter configuration files to customize RC channel mapping and PWM output assignments.

Parameter files provide a text-based, version-controllable method for managing vehicle configuration, making it easy to:
- Define custom PWM output assignments (motors, servos, lights)
- Map RC input channels to vehicle functions
- Configure servo ranges and motor directions
- Create reproducible configurations for fleets
- Share and document vehicle setups

## Parameter File Format

BlueOS uses the ArduPilot `.params` file format, which is a simple CSV structure:

```
PARAM_NAME,value
```

Each line contains a parameter name and its value, separated by a comma. For example:

```
SERVO1_FUNCTION,33
SERVO1_MIN,1100
SERVO1_MAX,1900
SERVO1_REVERSED,0
RC_MAP_ROLL,1
RC_MAP_PITCH,2
```

**Format Rules:**
- One parameter per line
- No spaces around the comma
- Comments can be added with `#` at the start of a line
- Blank lines are ignored
- Parameter names are case-sensitive
- Values are typically integers or floats

## File Locations

### Linux Boards (Navigator, Navigator64, Argonot)

For Linux-based boards running ArduPilot on the host system, parameter files are stored at:

```
/usr/blueos/userdata/firmware/{platform_name}params.params
```

**Common paths:**
- **Navigator**: `/usr/blueos/userdata/firmware/ardupilot_navigatorparams.params`
- **Navigator64**: `/usr/blueos/userdata/firmware/ardupilot_navigator64params.params`
- **Argonot**: `/usr/blueos/userdata/firmware/ardupilot_argonotparams.params`

These files are read during ArduPilot startup and applied to the vehicle. You can edit them directly via SSH or through the BlueOS file manager.

### Serial Boards (Pixhawk Family)

For serial boards (Pixhawk 1-6, CubeOrange, etc.), parameters cannot be stored separately from the firmware. Instead, they must be embedded in the APJ firmware file when uploading via the BlueOS API:

- Use the `/install_firmware_from_url` or `/install_firmware_from_file` API endpoints
- Include parameters in the `parameters` JSON field
- Parameters are written to the board after firmware installation

## PWM Output Configuration

### SERVO_FUNCTION Parameters

The `SERVO{n}_FUNCTION` parameters (where `n` is 1-16) assign specific functions to each PWM output channel. This is the primary mechanism for configuring what each output does.

**Common SERVO_FUNCTION Values:**

| Value | Function | Description |
|-------|----------|-------------|
| 0 | Disabled | Output is disabled |
| 33 | Motor1 | First motor (front-right on quad) |
| 34 | Motor2 | Second motor (back-left on quad) |
| 35 | Motor3 | Third motor (front-left on quad) |
| 36 | Motor4 | Fourth motor (back-right on quad) |
| 37 | Motor5 | Fifth motor (ROVs, hexacopters) |
| 38 | Motor6 | Sixth motor (ROVs, hexacopters) |
| 7 | Servo Relay | Servo pass-through |
| 59 | ProfiLED | LED control (single channel) |
| 60 | ProfiLED_2 | LED control (channel 2) |
| 22 | Parachute | Parachute release |
| 28 | Gripper | Gripper control |
| 73 | ThrottleLeft | Left throttle (boats) |
| 74 | ThrottleRight | Right throttle (boats) |

**Example - BlueROV2 Configuration:**
```
# Main thrusters
SERVO1_FUNCTION,33  # Motor 1 - Vertical starboard
SERVO2_FUNCTION,34  # Motor 2 - Vertical port
SERVO3_FUNCTION,35  # Motor 3 - Forward starboard
SERVO4_FUNCTION,36  # Motor 4 - Forward port
SERVO5_FUNCTION,37  # Motor 5 - Lateral starboard
SERVO6_FUNCTION,38  # Motor 6 - Lateral port

# Accessories
SERVO9_FUNCTION,59  # Lights
SERVO10_FUNCTION,7  # Camera tilt servo
```

### Servo Range Configuration

Each servo output has configurable PWM range parameters:

- **`SERVO{n}_MIN`** - Minimum PWM value in microseconds (typically 1000-1100)
- **`SERVO{n}_TRIM`** - Center/neutral position (typically 1500)
- **`SERVO{n}_MAX`** - Maximum PWM value in microseconds (typically 1900-2000)
- **`SERVO{n}_REVERSED`** - Reverse the servo direction (0 = normal, 1 = reversed)

**Example:**
```
SERVO10_MIN,1100
SERVO10_TRIM,1500
SERVO10_MAX,1900
SERVO10_REVERSED,0
```

### Motor Direction

For submarines and underwater vehicles, motor direction can be configured independently:

- **`MOT_{n}_DIRECTION`** - Motor rotation direction (1 = normal, -1 = reversed)
  - Where `n` corresponds to the motor number (1-8)

**Example:**
```
MOT_1_DIRECTION,1
MOT_2_DIRECTION,-1
MOT_3_DIRECTION,1
MOT_4_DIRECTION,-1
```

This is often used instead of `SERVO_REVERSED` for underwater thrusters.

## PWM Input Configuration

### RC Channel Mapping

The `RC_MAP_*` parameters map physical RC receiver channels to ArduPilot control functions:

**Flight Control Mapping:**
- **`RC_MAP_ROLL`** - Channel for roll control (default: 1)
- **`RC_MAP_PITCH`** - Channel for pitch control (default: 2)
- **`RC_MAP_THROTTLE`** - Channel for throttle control (default: 3)
- **`RC_MAP_YAW`** - Channel for yaw control (default: 4)

**ROV-Specific Mapping:**
- **`RC_MAP_FORWARD`** - Channel for forward/backward movement
- **`RC_MAP_LATERAL`** - Channel for left/right movement

**Auxiliary Functions:**
- **`RC_MAP_AUX1`** through **`RC_MAP_AUX6`** - Additional channels for switches, modes, etc.

**Example - Standard Configuration:**
```
RC_MAP_ROLL,1
RC_MAP_PITCH,2
RC_MAP_THROTTLE,3
RC_MAP_YAW,4
RC_MAP_FORWARD,5
RC_MAP_LATERAL,6
```

## Configuration Methods

### Method 1: Web Interface

The easiest way to configure PWM settings is through the BlueOS web interface:

1. **Parameter Editor:**
   - Navigate to `Vehicle Setup` → `Parameter Editor`
   - Search for parameters (e.g., "SERVO1_FUNCTION")
   - Edit values directly
   - Click "Write Parameters" to apply

2. **PWM Setup Page:**
   - Navigate to `Vehicle Setup` → `PWM Setup`
   - Visual interface for testing motors and servos
   - Configure function assignments with dropdowns
   - Test outputs in real-time

### Method 2: REST API

For programmatic configuration, use the ArduPilot Manager API:

**Endpoint:** `POST /install_firmware_from_url` or `POST /install_firmware_from_file`

**Request Body:**
```json
{
  "url": "https://firmware.ardupilot.org/Sub/stable/navigator/ardusub",
  "parameters": {
    "SERVO1_FUNCTION": 33,
    "SERVO2_FUNCTION": 34,
    "SERVO3_FUNCTION": 35,
    "SERVO4_FUNCTION": 36,
    "RC_MAP_ROLL": 1,
    "RC_MAP_PITCH": 2,
    "RC_MAP_THROTTLE": 3
  }
}
```

**Example using curl:**
```bash
curl -X POST http://blueos.local/ardupilot-manager/v1/install_firmware_from_url \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://firmware.ardupilot.org/Sub/stable/navigator/ardusub",
    "parameters": {
      "SERVO1_FUNCTION": 33,
      "SERVO2_FUNCTION": 34
    }
  }'
```

### Method 3: Direct File Edit

For Linux boards, you can directly edit the parameter file:

**Steps:**
1. SSH into the BlueOS device: `ssh pi@blueos.local`
2. Edit the parameter file:
   ```bash
   sudo nano /usr/blueos/userdata/firmware/ardupilot_navigatorparams.params
   ```
3. Make your changes (follow the format: `PARAM_NAME,value`)
4. Save and exit
5. Restart ArduPilot or reboot:
   ```bash
   sudo systemctl restart ardupilot
   ```

**Note:** Direct edits only work for Linux boards. Serial boards require API-based updates.

### Method 4: Firmware Installation

When installing custom firmware, include a complete parameter file:

1. Prepare your `.params` file with all desired settings
2. Upload firmware through BlueOS interface
3. Include parameters in the upload request (via API) or
4. Apply parameters afterward via Parameter Editor

## Examples

### BlueROV2 Configuration

Typical BlueROV2 Heavy configuration with 6 thrusters and accessories:

```
# Thruster configuration
SERVO1_FUNCTION,33
SERVO2_FUNCTION,34
SERVO3_FUNCTION,35
SERVO4_FUNCTION,36
SERVO5_FUNCTION,37
SERVO6_FUNCTION,38

# Thruster ranges
SERVO1_MIN,1100
SERVO1_MAX,1900
SERVO2_MIN,1100
SERVO2_MAX,1900
SERVO3_MIN,1100
SERVO3_MAX,1900
SERVO4_MIN,1100
SERVO4_MAX,1900
SERVO5_MIN,1100
SERVO5_MAX,1900
SERVO6_MIN,1100
SERVO6_MAX,1900

# Motor directions (for balanced movement)
MOT_1_DIRECTION,1
MOT_2_DIRECTION,-1
MOT_3_DIRECTION,1
MOT_4_DIRECTION,-1
MOT_5_DIRECTION,1
MOT_6_DIRECTION,-1

# Accessories
SERVO9_FUNCTION,59    # Lights
SERVO10_FUNCTION,7    # Camera tilt servo
SERVO10_MIN,1100
SERVO10_MAX,1900

# RC input mapping
RC_MAP_ROLL,1
RC_MAP_PITCH,2
RC_MAP_THROTTLE,3
RC_MAP_YAW,4
RC_MAP_FORWARD,5
RC_MAP_LATERAL,6

# Frame configuration
FRAME_CONFIG,1        # BlueROV2 frame
```

### BlueBoat Configuration

Surface boat with differential thrust:

```
# Main thrusters (differential)
SERVO1_FUNCTION,73    # Left throttle
SERVO2_FUNCTION,74    # Right throttle

# Thruster ranges
SERVO1_MIN,1000
SERVO1_MAX,2000
SERVO2_MIN,1000
SERVO2_MAX,2000

# Accessories
SERVO3_FUNCTION,59    # Navigation lights

# RC input mapping
RC_MAP_ROLL,1         # Used for steering
RC_MAP_THROTTLE,3     # Forward/backward
RC_MAP_YAW,4          # Trim/fine steering

# Frame type
FRAME_TYPE,1          # Boat frame
```

### Custom Configuration

Example for a custom underwater vehicle with 8 thrusters and gripper:

```
# 8-thruster configuration
SERVO1_FUNCTION,33
SERVO2_FUNCTION,34
SERVO3_FUNCTION,35
SERVO4_FUNCTION,36
SERVO5_FUNCTION,37
SERVO6_FUNCTION,38
SERVO7_FUNCTION,39    # Motor 7 (if supported)
SERVO8_FUNCTION,40    # Motor 8 (if supported)

# All thrusters standard range
SERVO1_MIN,1100
SERVO1_MAX,1900
SERVO2_MIN,1100
SERVO2_MAX,1900
SERVO3_MIN,1100
SERVO3_MAX,1900
SERVO4_MIN,1100
SERVO4_MAX,1900
SERVO5_MIN,1100
SERVO5_MAX,1900
SERVO6_MIN,1100
SERVO6_MAX,1900
SERVO7_MIN,1100
SERVO7_MAX,1900
SERVO8_MIN,1100
SERVO8_MAX,1900

# Accessories
SERVO9_FUNCTION,59    # Lights
SERVO10_FUNCTION,28   # Gripper
SERVO11_FUNCTION,7    # Camera tilt

# Standard RC mapping
RC_MAP_ROLL,1
RC_MAP_PITCH,2
RC_MAP_THROTTLE,3
RC_MAP_YAW,4
RC_MAP_FORWARD,5
RC_MAP_LATERAL,6
```

## Parameter Reference

### Essential PWM Output Parameters

| Parameter | Range | Description |
|-----------|-------|-------------|
| `SERVO{n}_FUNCTION` | 0-100+ | Assigns function to PWM output |
| `SERVO{n}_MIN` | 500-2500 | Minimum PWM pulse width (µs) |
| `SERVO{n}_TRIM` | 500-2500 | Center/neutral PWM value (µs) |
| `SERVO{n}_MAX` | 500-2500 | Maximum PWM pulse width (µs) |
| `SERVO{n}_REVERSED` | 0-1 | Reverse servo direction |
| `MOT_{n}_DIRECTION` | -1, 1 | Motor rotation direction |

### Essential PWM Input Parameters

| Parameter | Range | Description |
|-----------|-------|-------------|
| `RC_MAP_ROLL` | 0-16 | RC channel for roll control |
| `RC_MAP_PITCH` | 0-16 | RC channel for pitch control |
| `RC_MAP_THROTTLE` | 0-16 | RC channel for throttle |
| `RC_MAP_YAW` | 0-16 | RC channel for yaw control |
| `RC_MAP_FORWARD` | 0-16 | RC channel for forward/back |
| `RC_MAP_LATERAL` | 0-16 | RC channel for left/right |
| `RC_MAP_AUX{n}` | 0-16 | RC channel for auxiliary function |

### Frame and Vehicle Type Parameters

| Parameter | Range | Description |
|-----------|-------|-------------|
| `FRAME_TYPE` | 0-15 | Vehicle frame type (0=multirotor, 1=boat, etc.) |
| `FRAME_CONFIG` | 0-15 | Specific frame configuration |
| `FRAME_CLASS` | 0-9 | Vehicle class (1=Quad, 2=Hexa, etc.) |

## Additional Resources

### ArduPilot Documentation
- [Complete Parameter List](https://ardupilot.org/copter/docs/parameters.html)
- [Servo Output Setup](https://ardupilot.org/rover/docs/servo-configuration.html)
- [RC Input Setup](https://ardupilot.org/copter/docs/common-rc-systems.html)

### BlueOS Resources
- BlueOS Documentation: https://docs.bluerobotics.com/blueos/
- ArduPilot Manager API: `http://blueos.local/ardupilot-manager/docs`
- Parameter Editor: `http://blueos.local/#/vehicle/params`
- PWM Setup: `http://blueos.local/#/vehicle/pwm`

### Source Code References
- Firmware Management: `/core/services/ardupilot_manager/firmware/FirmwareManagement.py:52-143`
- PWM Setup UI: `/core/frontend/src/components/vehiclesetup/PwmSetup.vue`
- API Endpoints: `/core/services/ardupilot_manager/api/v1/routers/index.py:164,193`

### Example Configuration Files
- BlueROV2: `/deploy/image-customization/overlay_bluerov2/usr/blueos/userdata/firmware/ardupilot_navigatorparams.params`
- BlueBoat: `/deploy/image-customization/overlay_blueboat120/usr/blueos/userdata/firmware/ardupilot_navigatorparams.params`

---

**Version:** BlueOS 1.5.0 beta 29
**Last Updated:** 2026-02-10
**Feedback:** Report issues at https://github.com/bluerobotics/BlueOS/issues
