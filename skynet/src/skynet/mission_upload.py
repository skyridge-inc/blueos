"""MAVLink mission upload state machine."""

from __future__ import annotations

import time
from typing import Any, Callable

from pymavlink import mavutil

from .exceptions import MissionUploadError

ProgressCallback = Callable[[int, int], None]


def upload_mission(
    conn: Any,
    items: list[tuple[float, float]],
    *,
    progress_callback: ProgressCallback | None = None,
    timeout: float = 5.0,
) -> None:
    """Upload a mission to the autopilot via the MAVLink mission protocol.

    Args:
        conn: Open mavutil MAVLink connection (target_system/component set).
        items: List of (lat, lon) tuples; index 0 = home, 1..N = waypoints.
        progress_callback: Optional callable(sent, total) after each accepted item.
        timeout: Per-item request wait in seconds. One retry is attempted
            before failing.

    Raises:
        MissionUploadError: On empty items, non-ACCEPTED ack, out-of-range
            seq request, or a second consecutive request timeout.
    """
    if not items:
        raise MissionUploadError("upload_mission called with empty items")

    total = len(items)
    mission_type = mavutil.mavlink.MAV_MISSION_TYPE_MISSION

    conn.mav.mission_count_send(
        conn.target_system,
        conn.target_component,
        total,
        mission_type,
    )

    sent: set[int] = set()
    last_seq: int = -1
    retried_seq: int | None = None

    while len(sent) < total:
        msg = conn.recv_match(
            type=["MISSION_REQUEST_INT", "MISSION_REQUEST", "MISSION_ACK"],
            blocking=True,
            timeout=timeout,
        )

        if msg is None:
            # No request arrived in time. Retry the current seq once.
            resend_seq = last_seq + 1 if last_seq + 1 < total else last_seq
            if retried_seq == resend_seq:
                raise MissionUploadError(
                    f"Timeout waiting for MISSION_REQUEST for seq {resend_seq}"
                )
            retried_seq = resend_seq
            _send_item(conn, resend_seq, items[resend_seq], mission_type)
            continue

        msg_type = msg.get_type()

        if msg_type == "MISSION_ACK":
            # Premature ack before we finished — treat as failure.
            result = msg.type
            if result != mavutil.mavlink.MAV_MISSION_ACCEPTED:
                raise MissionUploadError(
                    f"Mission rejected early at seq {last_seq}: "
                    f"MAV_MISSION_RESULT={result}"
                )
            raise MissionUploadError(
                f"Unexpected early MISSION_ACK(ACCEPTED) after seq {last_seq}, "
                f"expected {total - len(sent)} more items"
            )

        # MISSION_REQUEST or MISSION_REQUEST_INT
        seq = msg.seq
        if seq < 0 or seq >= total:
            raise MissionUploadError(
                f"Autopilot requested out-of-range seq {seq} (total={total})"
            )

        _send_item(conn, seq, items[seq], mission_type)
        retried_seq = None

        if seq not in sent:
            sent.add(seq)
            last_seq = seq
            if progress_callback is not None:
                progress_callback(len(sent), total)

    # All items sent — wait for final ACK.
    deadline = time.monotonic() + timeout
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MissionUploadError(
                f"Timeout waiting for MISSION_ACK after sending {total} items"
            )
        ack = conn.recv_match(
            type="MISSION_ACK",
            blocking=True,
            timeout=remaining,
        )
        if ack is None:
            continue
        result = ack.type
        if result != mavutil.mavlink.MAV_MISSION_ACCEPTED:
            raise MissionUploadError(
                f"Autopilot rejected mission at seq {last_seq}: "
                f"MAV_MISSION_RESULT={result}"
            )
        return


def _send_item(
    conn: Any,
    seq: int,
    latlon: tuple[float, float],
    mission_type: int,
) -> None:
    lat, lon = latlon
    conn.mav.mission_item_int_send(
        conn.target_system,
        conn.target_component,
        seq,
        mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT,
        mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
        1 if seq == 0 else 0,  # current
        1,  # autocontinue
        0.0,  # param1
        0.0,  # param2
        0.0,  # param3
        0.0,  # param4
        int(round(lat * 1e7)),
        int(round(lon * 1e7)),
        0.0,
        mission_type,
    )
