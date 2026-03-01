"""MAVLink connection management."""

from __future__ import annotations

import contextlib
from collections.abc import Generator
from typing import Any

from pymavlink import mavutil

from .exceptions import ConnectionError, HeartbeatTimeout

# MAVLink vehicle type names (MAV_TYPE enum subset)
VEHICLE_TYPES: dict[int, str] = {
    0: "Generic",
    1: "Fixed Wing",
    2: "Quadrotor",
    10: "Ground Rover",
    11: "Surface Boat",
}


def get_vehicle_type_name(mav_type: int) -> str:
    """Return human-readable vehicle type name."""
    return VEHICLE_TYPES.get(mav_type, f"Unknown ({mav_type})")


@contextlib.contextmanager
def mavlink_connection(
    device: str,
    baud: int = 115200,
    timeout: float = 10.0,
) -> Generator[Any, None, None]:
    """Context manager that connects to a MAVLink device and waits for heartbeat.

    Yields the mavutil.mavlink_connection object with target_system and
    target_component set from the first heartbeat.

    Raises:
        ConnectionError: If the device cannot be opened.
        HeartbeatTimeout: If no heartbeat is received within timeout.
    """
    try:
        conn = mavutil.mavlink_connection(device, baud=baud)
    except Exception as e:
        raise ConnectionError(f"Cannot open {device}: {e}") from e

    msg = conn.wait_heartbeat(timeout=timeout)
    if msg is None:
        conn.close()
        raise HeartbeatTimeout(
            f"No heartbeat from {device} within {timeout}s"
        )

    conn.target_system = msg.get_srcSystem()
    conn.target_component = msg.get_srcComponent()

    try:
        yield conn
    finally:
        conn.close()
