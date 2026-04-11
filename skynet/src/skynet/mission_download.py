"""MAVLink mission download state machine."""

from __future__ import annotations

from typing import Any, Callable

from pymavlink import mavutil

from .exceptions import MissionDownloadError

ProgressCallback = Callable[[int, int], None]


def download_mission(
    conn: Any,
    *,
    timeout: float = 5.0,
    progress_callback: ProgressCallback | None = None,
) -> list[tuple[float, float]]:
    """Download the mission currently on the autopilot.

    Returns a list of (lat, lon) tuples with index 0 = home and
    indices 1..N = mission waypoints, matching the convention used by
    `read_waypoints(include_home=True)` and `upload_mission`.

    Raises:
        MissionDownloadError: On empty mission (count <= 1), out-of-range
            seq, or repeated timeouts (one retry is attempted).
    """
    mission_type = mavutil.mavlink.MAV_MISSION_TYPE_MISSION

    # Step 1/2: request the list, accept one retry on timeout for MISSION_COUNT.
    count = _request_count(conn, mission_type, timeout)

    if count == 0:
        raise MissionDownloadError(
            "Autopilot has no mission loaded (count=0). Upload one with "
            "`skynet nav upload` first."
        )
    if count == 1:
        raise MissionDownloadError(
            "Autopilot has only a home row (count=1). Upload a real "
            "mission with `skynet nav upload` first."
        )

    # Step 3: per-seq request/response with one retry per item.
    items: dict[int, tuple[float, float]] = {}
    for seq in range(count):
        item = _request_item(conn, mission_type, seq, count, timeout)
        items[seq] = item
        if progress_callback is not None:
            progress_callback(len(items), count)

    # Step 4: close out the session.
    conn.mav.mission_ack_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_MISSION_ACCEPTED,
        mission_type,
    )

    return [items[i] for i in range(count)]


def _request_count(conn: Any, mission_type: int, timeout: float) -> int:
    for attempt in range(2):
        conn.mav.mission_request_list_send(
            conn.target_system,
            conn.target_component,
            mission_type,
        )
        msg = conn.recv_match(
            type="MISSION_COUNT", blocking=True, timeout=timeout
        )
        if msg is not None:
            return int(msg.count)
    raise MissionDownloadError(
        f"Timeout waiting for MISSION_COUNT after 2 attempts "
        f"({timeout}s each)"
    )


def _request_item(
    conn: Any,
    mission_type: int,
    seq: int,
    count: int,
    timeout: float,
) -> tuple[float, float]:
    for attempt in range(2):
        conn.mav.mission_request_int_send(
            conn.target_system,
            conn.target_component,
            seq,
            mission_type,
        )
        msg = conn.recv_match(
            type="MISSION_ITEM_INT", blocking=True, timeout=timeout
        )
        if msg is None:
            continue
        if msg.seq < 0 or msg.seq >= count:
            raise MissionDownloadError(
                f"Autopilot sent out-of-range seq {msg.seq} (count={count})"
            )
        if msg.seq != seq:
            # Skew — retry the same seq.
            continue
        lat = msg.x / 1e7
        lon = msg.y / 1e7
        return (lat, lon)
    raise MissionDownloadError(
        f"Timeout waiting for MISSION_ITEM_INT seq {seq} after 2 attempts"
    )
