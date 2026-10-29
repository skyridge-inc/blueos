# BlueOS Extensions — Catalog Review

Snapshot of the official Blue Robotics **BlueOS Extensions Repository** taken
2026-10-28 from
`https://bluerobotics.github.io/BlueOS-Extensions-Repository/manifest.json`
(the same manifest the BlueOS "Extensions Manager" page reads).

- **61 extensions** listed, from Blue Robotics, sensor vendors, and community authors.
- Each extension is a Docker image that BlueOS pulls and runs alongside its core
  services. Most expose a web UI that is embedded in the BlueOS sidebar.
- The "Latest" column is the highest version string in the manifest, which may
  be a beta. "Arch" is the set of platforms the latest image was published for.
  `arm/v7` = 32-bit Pi userspace, `arm64` = 64-bit Pi, `amd64` = x86 (SITL/dev).

| Category (author-assigned) | Count |
|---|---|
| device-integration | 24 |
| other | 17 |
| tool | 13 |
| example | 6 |
| education | 1 |

Categories are chosen by each extension's author and are not always
consistent (e.g. Cerulean DVL is filed under "other", not
"device-integration"). The sections below regroup extensions by what they
actually do.

---

## Relevance to the Skyridge mower fleet

Most of the catalog targets underwater ROVs (ArduSub/BlueROV2) and the
BlueBoat. Items worth evaluating for ArduPilot Rover mowers:

| Extension | Why it might matter for us |
|---|---|
| **Ntrip** (`williangalvani.ntrip`) | NTRIP caster client → RTCM corrections injected into the autopilot. Directly relevant to RTK on the mosaic-H receiver, though corrections can also be fed straight to the receiver. |
| **MediaMTX** (`williangalvani.mediamtx`) | Packaged MediaMTX. We already maintain `mediamtx*.yml` configs by hand; this extension could replace a custom container. |
| **Dashcam** (`williangalvani.dashcam`) | On-vehicle video recording. Useful for incident review on mowers. |
| **ZeroTier** (`williangalvani.zerotier`) | Virtual network to reach vehicles from anywhere; an option for fleet remote access. |
| **Cellular Modem Manager** (`bluerobotics.cellular-modem-manager`) | Manage a USB LTE modem from BlueOS. Relevant if mowers get cellular backhaul. |
| **Mikrotik Monitor** (`vshie.mikrotik-monitor`) | Live link SNR/rate from a MikroTik radio, logged and sent to the autopilot as NAMED_VALUE_FLOAT. Good for range/coverage surveys if we use MikroTik radios. |
| **Vibration Analyzer** (`rafaellehmkuhl.vibration-analyzer`) | ArduPilot vibration/clipping, FFT, notch-filter lab. Mower decks put a lot of vibration into the IMU. |
| **DroneCAN GUI** (`williangalvani.dronecan-gui`) | Configure DroneCAN nodes (GPS, ESCs, sensors) over MAVLink from the browser. |
| **SITL Manager** (`armanzoli.sitl-manager`) | Configure SITL vehicle type, spawn location, simulated battery. Could complement `skynet nav sim`. |
| **Network Scanner** (`williangalvani.network-scanner`) | Find devices on the vehicle LAN (cameras, radios). |
| **Node-RED / Jupyter / OpenVSCoder** | On-vehicle development and scripting. Handy for bench work; not something to ship on production mowers. |
| **ROS2** (`itskalvik.ros2`) | Full ROS2 stack with Foxglove bridge. Only relevant if we add ROS2-based perception. |
| **Starlink Position** (`patrickelectric.starlink-position`) | Uses a Starlink dish as a position source. Niche, but a GNSS fallback option. |

Check architecture before installing: several extensions (Node-RED, OpenVSCoder,
Yacht, Starlink Position) only publish `arm/v7` images, and a few (Precision
Landing, OpticalFlow, Foxglove, Oak-D VINS) only publish `arm64`.

---

## Full catalog by function

### Navigation & positioning

| Name | Identifier | Latest | Arch | Description |
|---|---|---|---|---|
| Water Linked DVL | `bluerobotics.water-linked-dvl` | v1.0.11 | amd64, arm/v7, arm64 | DVL integration for ROV position hold and navigation. |
| Nortek Nucleus | `nortekgroup.nucleus` | 2.0.10 | amd64, arm/v7, arm64 | Nucleus1000 DVL for ROV navigation (water tracking, current profiling). |
| Cerulean DVL | `ceruleansonar.cerulean-dvl` | v1.0.8 | amd64, arm/v7 | Cerulean DVL driver. |
| Sonardyne NavSync Pro | `sonardyne.navsync_pro` | v1.0.11 | amd64, arm/v7, arm/v8, arm64 | Feeds SPRINT-Nav INS position to the vehicle for tracking and position hold. |
| Water Linked UGPS | `waterlinked.ugps` | v1.0.7-beta.5 | arm/v5 | Underwater GPS (short-baseline acoustic) position. |
| WL UGPS External | `clydemcqueen.wl_ugps_external` | v1.1.0-beta.2 | amd64, arm/v7 | Sends GNSS compass data to Water Linked UGPS topside. |
| Ntrip | `williangalvani.ntrip` | v0.0.5 | amd64, arm/v7, arm64 | NTRIP client for RTK corrections. |
| Starlink Position | `patrickelectric.starlink-position` | 1.0.4 | arm/v7 | Vehicle position from a Starlink antenna. |
| Oak-D Visual Odometry | `williangalvani.oakd vins` | v0.0.1 | arm64 | Visual-inertial odometry with Oak-D cameras. |
| OpticalFlow | `rmackay9.opticalflow` | 0.0.1 | arm64 | Optical flow from an Ethernet camera gimbal. |
| Precision Landing | `rmackay9.precision-landing` | 0.0.1 | arm64 | Precision landing on an AprilTag via an Ethernet camera gimbal. |

### Sonar & acoustic

| Name | Identifier | Latest | Arch | Description |
|---|---|---|---|---|
| Ping Viewer 2 | `bluerobotics.ping-viewer-next` | 1.0.0-beta.27 | amd64, arm/v7, arm64 | New Ping Viewer for Ping-protocol sonars (Ping2, Ping360). |
| SonarView | `ceruleansonar.sonarview` | 1.14.85 | amd64, arm/v7, arm64 | Cerulean cross-platform sonar viewer. |
| Water Linked 3D Sonar | `waterlinked.sonar` | v1.0.0 | arm/v7 | Configuration and point-cloud visualization, auto IP discovery. |
| Echologger | `eofeultrasonics.echologger` | 1.0.0-beta | arm64 | Echosounder configuration and data logging. |
| Simple Ping2 Survey | `vshie.pingSurvey` | v1.2.5 | amd64, arm/v7, arm64 | Simple bathymetry survey logging with a Ping2. |
| SGP-Tools | `itskalvik.sgptools` | 0.0.3 | amd64, arm64 | Autonomous approximate bathymetric survey planning (ROS2-based). |

### Cameras & video

| Name | Identifier | Latest | Arch | Description |
|---|---|---|---|---|
| 4K Cam Manager | `bluerobotics.radcam-manager` | 0.4.1 | amd64, arm/v7, arm64 | Official management UI for the Blue Robotics 4K camera. |
| DWE OS 2.0 | `deepwaterexploration.dwe_os_2` | v0.7.5-blueos | arm/v7, arm64 | Driver/UI for DeepWater Exploration exploreHD / stellarHD cameras. |
| Madrona | `marinesitu.madrona` | 1.16.0 | amd64, arm/v7, arm64 | OAK-D camera management and surveying for MarineSitu C3 cameras. |
| Oak-D Video Streams | `williangalvani.oakd` | v1.0.1-heta.1 | arm/v7 | Exposes Oak-D streams to Cockpit. |
| Camera Download | `rmackay9.camera-download` | 0.0.3 | amd64, arm/v7, arm64 | Download stills/video from Ethernet camera gimbals. |
| Dashcam | `williangalvani.dashcam` | v0.0.21 | amd64, arm/v7, arm64 | Local video recording on the vehicle. |
| SubReels: AUV | `vshie.subreels-auv` | 1.0.0 | amd64, arm/v7, arm64 | Onboard recording + Lua-scripted dive missions for hovering AUVs. |
| MediaMTX | `williangalvani.mediamtx` | v1.11.4 | amd64, arm/v7, arm64 | Wrapper for running the MediaMTX RTSP/WebRTC server. |
| MCM CPU Analyzer | `patrickelectric.mcm-cpu-analyzer` | 0.0.4 | amd64, arm/v7, arm64 | CPU profiling for mavlink-camera-manager. |

### Other sensors

| Name | Identifier | Latest | Arch | Description |
|---|---|---|---|---|
| ANB Sensors GUI | `anbsensors.pH_sensor` | 1.3.0 | amd64, arm/v7, arm64 | ANB Sensors pH sensor UI. |
| Marine Magnetics Explorer | `vshie.marine-magnetics-explorer` | 1.0.4 | amd64, arm/v7, arm64 | Magnetometer logging, deviation alarm, NAMED_VALUE_FLOAT to autopilot. |
| Airmar WX | `vshie.airmar-wx` | 1.1.4 | amd64, arm/v7, arm64 | Airmar 200WX/300WX weather stations over NMEA 0183; outputs to ArduPilot and Cockpit. |
| DORIS | `bluerobotics.blueos-doris` | 0.0.32 | amd64, arm/v7, arm64 | Deep Ocean Research and Imaging System. |
| PowerSwitch Calibration | `bluerobotics.power-switch-calibration` | v1.0.0 | arm/v7 | Calibrate current-sense offset on the BlueBoat power switch. |

### Communications & networking

| Name | Identifier | Latest | Arch | Description |
|---|---|---|---|---|
| Cellular Modem Manager | `bluerobotics.cellular-modem-manager` | 0.3.4 | amd64, arm/v7, arm64 | Manage cellular modems from BlueOS. |
| ZeroTier | `williangalvani.zerotier` | v1.14.3 | amd64, arm/v7, arm64 | Join a ZeroTier virtual network for remote operation. |
| Mikrotik Monitor | `vshie.mikrotik-monitor` | 1.3.0 | amd64, arm/v7, arm64 | MikroTik link metrics, distance/bearing, CSV + autopilot telemetry. |
| Tether Diagnostics | `williangalvani.plc-diagnostics` | v1.0.3 | amd64, arm/v7, arm64 | Diagnose tether (powerline comms) issues. |
| Network Scanner | `williangalvani.network-scanner` | v1.0.4 | amd64, arm/v7, arm64 | Discover devices on the BlueOS network. |
| BlueOS Proxy | `williangalvani.blueos-proxy` | v1.0.6 | amd64, arm/v7, arm64 | Proxy for BlueOS web services. |
| USBIP | `williangalvani.usbip` | v1.0.4 | amd64, arm/v7, arm64 | Share USB devices over IP (USB/IP protocol). |
| VirtualHere | `williangalvani.virtualhere` | v1.0.5 | amd64, arm/v7, arm64 | Share USB devices over IP (VirtualHere). |
| JM Connect | `jmrobotics.jm-connect` | 0.2.4 | arm/v7, arm64 | JM Robotics connectivity extension. |

### Vehicle control, autopilot & diagnostics

| Name | Identifier | Latest | Arch | Description |
|---|---|---|---|---|
| Cockpit Lite | `bluerobotics.cockpit` | v1.19.0-beta.19 | amd64, arm/v7, arm64 | Browser build of Blue Robotics' Cockpit control station. |
| Vibration Analyzer | `rafaellehmkuhl.vibration-analyzer` | 0.1.0 | amd64, arm/v7, arm64 | Live/log vibration, FFT, spectrogram, harmonic-notch tuning. |
| DroneCAN GUI | `williangalvani.dronecan-gui` | v1.0.1 | amd64, arm/v7, arm64 | Configure DroneCAN nodes through the autopilot over MAVLink. |
| SITL Manager | `armanzoli.sitl-manager` | 0.3.3 | amd64, arm/v7, arm64 | SITL vehicle type, environment, spawn location, simulated battery presets. |
| Surftrak Fixit | `clydemcqueen.surftrak_fixit` | v1.1.0-beta.1-dev | amd64, arm/v7, arm64 | Diagnose ArduSub Surftrak (rangefinder hold) problems. |
| Navigator WebAssistant | `bluerobotics.navigator-webassistant` | 1.0.0 | arm/v7, arm64 | Drive the Navigator flight controller's peripherals via web services. |

### Development & robotics frameworks

| Name | Identifier | Latest | Arch | Description |
|---|---|---|---|---|
| Jupyter | `bluerobotics.jupyter` | 0.2.0 | arm/v7, arm64 | Python notebooks on the vehicle. |
| OpenVSCoder | `bluerobotics.openvscode` | 1.1.2 | arm/v7 | VS Code in the browser on the vehicle. |
| Node-RED | `bluerobotics.node-red` | 1.1.0 | arm/v7 | Low-code flow-based programming. |
| ROS | `bluerobotics.ros` | 0.0.2 | arm/v7, arm64 | ROS 1 environment. |
| ROS2 | `itskalvik.ros2` | 0.1.0 | amd64, arm64 | ROS2 with sonar/camera/Foxglove/navigation tooling. |
| BlueOS Foxglove | `patrickelectric.foxglove` | 0.0.4 | arm64 | Bridges BlueOS Zenoh data to Foxglove Studio. |
| Yacht | `bluerobotics.yacht` | 1.0.0 | arm/v7 | Docker container management dashboard. |

### Documentation

| Name | Identifier | Latest | Arch | Description |
|---|---|---|---|---|
| BR Documentation | `bluerobotics.blueos-documentation` | 2025.2.8 | amd64, arm/v7, arm64 | Offline Blue Robotics software docs. |
| Cerulean Docs | `ceruleansonar.cerulean-docs` | v1.1.0 | amd64, arm/v7 | Offline Cerulean Sonar docs. |

### Examples (for writing our own extensions)

| Name | Identifier | Latest | Description |
|---|---|---|---|
| Example 1 | `williangalvani.example1` | v1.0.1 | Hello World. |
| Example 2 | `williangalvani.example2` | v1.0.1 | Static HTML plus MAVLink data. |
| Example 3 | `williangalvani.example3` | v1.0.1 | Basic Vuetify UI. |
| Example 4 | `williangalvani.example4` | v1.0.1 | Vuetify + persistent backend. |
| Example 5 | `williangalvani.example5` | v1.0.1 | GPIO PWM control. |
| WebSocket Streamer for Cockpit | `rafaellehmkuhl.websocket-streamer-for-cockpit` | 0.1.2 | Streams data-lake variables to Cockpit over WebSocket. |

Source repos for the examples:
`https://github.com/Williangalvani/BlueOS-examples/` and
`https://github.com/rafaellehmkuhl/BlueOS-WebSocket-Server-For-Cockpit-Extension`.

---

## Source links

| Identifier | Repository / website |
|---|---|
| `anbsensors.pH_sensor` | https://github.com/dbtuna/BlueOS-UI |
| `armanzoli.sitl-manager` | https://github.com/ArturoManzoli/blueos-sitl-manager |
| `bluerobotics.blueos-doris` | https://github.com/bluerobotics/blueos-doris-extension |
| `bluerobotics.blueos-documentation` | https://github.com/bluerobotics/BlueRobotics-docs-Extension |
| `bluerobotics.cellular-modem-manager` | https://github.com/bluerobotics/cellphone-modem-manager |
| `bluerobotics.cockpit` | https://github.com/bluerobotics/cockpit |
| `bluerobotics.jupyter` | https://github.com/BlueOS-Community/blueos-jupyter |
| `bluerobotics.navigator-webassistant` | https://github.com/RaulTrombin/blueos-navigator-web-assistant |
| `bluerobotics.node-red` | https://github.com/BlueOS-Community/blueos-node-red |
| `bluerobotics.openvscode` | https://github.com/BlueOS-Community/blueos-code-server |
| `bluerobotics.ping-viewer-next` | https://github.com/bluerobotics/ping-viewer-next |
| `bluerobotics.power-switch-calibration` | https://github.com/rjehangir/BlueOS-PS-Calibration/ |
| `bluerobotics.radcam-manager` | https://github.com/bluerobotics/br4kcam-manager |
| `bluerobotics.ros` | https://github.com/BlueOS-Community/blueos-ros |
| `bluerobotics.water-linked-dvl` | https://github.com/bluerobotics/BlueOS-Water-Linked-DVL/ |
| `bluerobotics.yacht` | https://github.com/BlueOS-Community/blueos-yacht |
| `ceruleansonar.cerulean-docs` | https://github.com/ceruleansonar/BlueOS-Cerulean-Docs/ |
| `ceruleansonar.cerulean-dvl` | https://github.com/ceruleansonar/BlueOS-Cerulean-DVL/ |
| `ceruleansonar.sonarview` | https://sonarview.io/ |
| `clydemcqueen.surftrak_fixit` | https://github.com/clydemcqueen/surftrak_fixit |
| `clydemcqueen.wl_ugps_external` | https://github.com/clydemcqueen/wl_ugps_external_extension |
| `deepwaterexploration.dwe_os_2` | https://github.com/DeepwaterExploration/DWE_OS_2 |
| `eofeultrasonics.echologger` | https://github.com/Echologger/BlueOS-Echologger-extension |
| `itskalvik.ros2` | https://github.com/itskalvik/blueos-ros2 |
| `itskalvik.sgptools` | https://www.itskalvik.com/sgp-tools/blueos.html |
| `jmrobotics.jm-connect` | https://www.jmrobotics.no |
| `marinesitu.madrona` | https://gitlab.com/marinesitu-public/madrona/madrona |
| `nortekgroup.nucleus` | https://github.com/nortekgroup/nucleus_driver/tree/main/blueos_extension |
| `patrickelectric.foxglove` | https://github.com/patrickelectric/blueos-foxglove |
| `patrickelectric.mcm-cpu-analyzer` | https://github.com/patrickelectric/blueos-mavlink-camera-manager-analyzer |
| `patrickelectric.starlink-position` | https://github.com/patrickelectric/blueos-starlink-position |
| `rafaellehmkuhl.vibration-analyzer` | https://github.com/rafaellehmkuhl/blueos-vibration-analyzer |
| `rmackay9.camera-download` | https://github.com/rmackay9/blueos-camera-download |
| `rmackay9.opticalflow` | https://github.com/BlueOS-Community/blueos-opticalflow |
| `rmackay9.precision-landing` | https://github.com/BlueOS-Community/blueos-precision-landing |
| `sonardyne.navsync_pro` | https://github.com/Sonardyne/blueos-sprint-nav-extension |
| `vshie.airmar-wx` | https://github.com/vshie/Airmar-WX |
| `vshie.marine-magnetics-explorer` | https://github.com/vshie/BlueOS-Marine-Magnetics-Explorer |
| `vshie.mikrotik-monitor` | https://github.com/vshie/Mikrotik-Monitor |
| `vshie.pingSurvey` | https://github.com/vshie/pingSurvey |
| `vshie.subreels-auv` | https://github.com/vshie/SubReels |
| `waterlinked.sonar` | https://github.com/waterlinked/BlueOS-Sonar-Extension |
| `waterlinked.ugps` | https://github.com/waterlinked/blueos-ugps-extension |
| `williangalvani.blueos-proxy` | https://github.com/Williangalvani/Blueos-Proxy-Extension |
| `williangalvani.dashcam` | https://github.com/Williangalvani/BlueOS-Dashcam/ |
| `williangalvani.dronecan-gui` | https://github.com/Williangalvani/blueos-dronecan-gui |
| `williangalvani.mediamtx` | https://github.com/Williangalvani/blueos-extension-MediaMTX |
| `williangalvani.network-scanner` | https://github.com/Williangalvani/BlueOS-extension-network-scanner |
| `williangalvani.ntrip` | https://github.com/Williangalvani/BlueOS-Ntrip-extension |
| `williangalvani.oakd` | https://github.com/Williangalvani/Oakd-extension |
| `williangalvani.oakd vins` | https://github.com/Williangalvani/Blueos-oakd-vins |
| `williangalvani.plc-diagnostics` | https://github.com/Williangalvani/plc-extension |
| `williangalvani.usbip` | https://github.com/Williangalvani/blueos-usbip |
| `williangalvani.virtualhere` | https://github.com/Williangalvani/BlueOS-VirtualHere |
| `williangalvani.zerotier` | https://github.com/BlueOS-Community/ZeroTierOne |

## Refreshing this document

The catalog changes often. To regenerate the raw data:

```bash
curl -sSL https://bluerobotics.github.io/BlueOS-Extensions-Repository/manifest.json -o manifest.json
# each entry: identifier, name, website, description,
#   versions.<ver>.{type, authors, filter_tags, images[].platform}
```
