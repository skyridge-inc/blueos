#!/bin/bash

# Upload a mission to the autopilot
echo "Uploading the waypoint mission..."
# skynet nav upload ./output/700_long_mower1.waypoints -d tcp:sky1.netbird.cloud:5760 --yes
echo "Uploaded the waypoint mission!"

# After starting the SIM, ARM the autopilot via QGroundControl
echo "After starting the SIM, ARM the autopilot via QGroundControl"

# Run the simulator
echo "About to run the simulator now..."
skynet nav sim -d tcp:sky1.netbird.cloud:5760 -y -v --duration 600 2>&1 | tee /tmp/sim.log
echo "Ran the simulator!"

echo "ARM THE AUTOPILOT"
