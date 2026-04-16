"""MAVLink mission upload state machine."""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from pymavlink import mavutil

from .exceptions import MissionUploadError

logger = logging.getLogger(__name__)

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
            result = msg.type
            if result != mavutil.mavlink.MAV_MISSION_ACCEPTED:
                raise MissionUploadError(
                    f"Mission rejected early at seq {last_seq}: "
                    f"MAV_MISSION_RESULT={result}"
                )
            # Autopilot ACCEPTED the mission before we sent every seq.
            # Some ArduPilot versions (e.g. 4.6) skip seq 0 (the home row)
            # during upload and ACK after receiving seqs 1..N-1. Trust
            # the autopilot's acceptance and return success.
            return

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


def query_mission_count(conn: Any, timeout: float = 3.0) -> int:
    """Ask the autopilot how many mission items it currently stores.

    Sends MISSION_REQUEST_LIST and waits for MISSION_COUNT. One retry on
    timeout. Returns the count (0 if empty / home-only).

    Raises MissionUploadError on repeated timeouts — the caller will
    typically want to refuse entering AUTO rather than silently accept
    an unknown mission state, so the failure is explicit.
    """
    mission_type = mavutil.mavlink.MAV_MISSION_TYPE_MISSION
    for _ in range(2):
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
    raise MissionUploadError(
        f"Timeout waiting for MISSION_COUNT after 2 attempts "
        f"({timeout}s each)"
    )


def upload_and_verify(
    conn: Any,
    items: list[tuple[float, float]],
    *,
    max_attempts: int = 3,
    timeout: float = 15.0,
    progress_callback: ProgressCallback | None = None,
) -> int:
    """Upload a mission and verify the autopilot's stored count matches.

    Retries both on MissionUploadError (rejected / timeout) and on a
    successful upload where MISSION_COUNT readback does not match the
    expected length. Between attempts, drains any pending mission
    protocol traffic so a stale MISSION_REQUEST doesn't poison the next
    round.

    Returns the verified MISSION_COUNT on success (== len(items)).
    Raises MissionUploadError if all attempts fail.

    This is the path used by the sim after the GPS_TYPE reboot — the
    single-shot upload_mission call races the post-reboot MAVLink
    re-handshake on BlueOS+NetBird tunnels and was observed to be
    rejected mid-protocol with MAV_MISSION_RESULT=13 (INVALID_SEQUENCE),
    leaving a 1-WP stub that made AUTO mode refuse to drive. See
    docs/SIM_AUTOPILOT_ISSUE_V4.md §Issue 1.
    """
    if not items:
        raise MissionUploadError("upload_and_verify called with empty items")

    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            upload_mission(
                conn,
                items,
                progress_callback=progress_callback,
                timeout=timeout,
            )
        except MissionUploadError as e:
            last_error = f"attempt {attempt}/{max_attempts}: {e}"
            logger.warning("Mission upload failed: %s", last_error)
            _drain_mission_traffic(conn)
            time.sleep(1.0 + attempt)
            continue

        try:
            stored = query_mission_count(conn, timeout=3.0)
        except MissionUploadError as e:
            last_error = (
                f"attempt {attempt}/{max_attempts}: uploaded but "
                f"MISSION_COUNT readback failed: {e}"
            )
            logger.warning("Mission count readback failed: %s", last_error)
            time.sleep(1.0 + attempt)
            continue

        if stored == len(items):
            return stored

        last_error = (
            f"attempt {attempt}/{max_attempts}: autopilot stored "
            f"{stored} items, expected {len(items)}"
        )
        logger.warning("Mission count mismatch: %s", last_error)
        _drain_mission_traffic(conn)
        time.sleep(1.0 + attempt)

    raise MissionUploadError(
        f"Mission upload could not be verified after {max_attempts} "
        f"attempts. Last error: {last_error}"
    )


def _drain_mission_traffic(conn: Any, window: float = 0.5) -> None:
    """Consume pending MISSION_* messages so a stale request doesn't
    poison the next upload attempt."""
    deadline = time.monotonic() + window
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        msg = conn.recv_match(
            type=[
                "MISSION_REQUEST_INT",
                "MISSION_REQUEST",
                "MISSION_ACK",
                "MISSION_COUNT",
                "MISSION_ITEM_INT",
                "MISSION_ITEM",
            ],
            blocking=True,
            timeout=max(0.05, remaining),
        )
        if msg is None:
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
