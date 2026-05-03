"""DataFlash-Over-MAVLink log downloader.

Used by the nav sim's AUTO-fail forensic capture path. When AUTO mode runs
without producing throttle for too long, the sim disarms (which seals the
autopilot's active dataflash log) and pulls that log to disk so the
internal `AR_WPNav` state — `NTUN`, `WPNV`, `RCOU`, `MOTB`, full `MSG`
text — that does not appear on the live MAVLink stream becomes
inspectable offline.

Protocol:
    1. LOG_REQUEST_LIST(0, 0xFFFF) → many LOG_ENTRY messages
    2. Pick the latest entry by log id
    3. LOG_REQUEST_DATA(id, ofs, count) → many LOG_DATA chunks of <=90 B
    4. LOG_REQUEST_END to politely close the session

The chunk-fetch loop tracks received offsets and re-requests the lowest
missing offset whenever the autopilot stalls — DataFlash-Over-MAVLink is
not lossless on a noisy serial link.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .exceptions import MowerProvisionerError


class LogDownloadError(MowerProvisionerError):
    """Raised when the log list/data exchange fails."""


@dataclass(frozen=True)
class LogEntry:
    log_id: int
    num_logs: int
    last_log_num: int
    time_utc: int
    size: int


# MAVLink LOG_DATA carries up to 90 bytes per chunk (spec-fixed).
CHUNK_SIZE = 90

# How long we'll wait for the LOG_ENTRY burst from LOG_REQUEST_LIST.
LIST_TIMEOUT_S = 5.0

# How long we'll wait between successive LOG_DATA chunks before treating
# the stream as stalled and re-requesting from the lowest missing offset.
CHUNK_STALL_S = 1.0

# Per-offset retry cap: if the same lowest missing offset stalls this
# many times in a row, give up to avoid a hang.
MAX_OFFSET_RETRIES = 5


def list_logs(conn: Any, *, timeout: float = LIST_TIMEOUT_S) -> list[LogEntry]:
    """Request the autopilot's log list and return entries sorted by id.

    Sends LOG_REQUEST_LIST(0, 0xFFFF) then drains LOG_ENTRY messages until
    we've seen `num_logs` of them or `timeout` elapses, whichever comes
    first. Empty list raises LogDownloadError.
    """
    conn.mav.log_request_list_send(
        conn.target_system, conn.target_component, 0, 0xFFFF
    )

    entries: dict[int, LogEntry] = {}
    expected: int | None = None
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        msg = conn.recv_match(type="LOG_ENTRY", blocking=True, timeout=0.5)
        if msg is None:
            continue
        entry = LogEntry(
            log_id=int(msg.id),
            num_logs=int(msg.num_logs),
            last_log_num=int(msg.last_log_num),
            time_utc=int(msg.time_utc),
            size=int(msg.size),
        )
        entries[entry.log_id] = entry
        if expected is None and entry.num_logs > 0:
            expected = entry.num_logs
        if expected is not None and len(entries) >= expected:
            break

    if not entries:
        raise LogDownloadError(
            "Autopilot returned no LOG_ENTRY messages — "
            "is logging enabled (LOG_DISARMED/LOG_REPLAY)?"
        )
    return sorted(entries.values(), key=lambda e: e.log_id)


def _missing_offsets(
    received: dict[int, bytes], total: int
) -> list[int]:
    """Chunk-aligned offsets in [0, total) we have not yet received."""
    missing: list[int] = []
    ofs = 0
    while ofs < total:
        if ofs not in received:
            missing.append(ofs)
        ofs += CHUNK_SIZE
    return missing


def download_log(
    conn: Any,
    log_id: int,
    size: int,
    dest: Path,
    *,
    progress_cb: Callable[[int, int], None] | None = None,
) -> Path:
    """Download a specific log to `dest`. Returns the path written.

    Streams LOG_DATA chunks from the autopilot, fills gaps via re-requests
    at the lowest missing offset, and reassembles in offset order.
    """
    if size <= 0:
        raise LogDownloadError(
            f"Log {log_id} reports size={size}; cannot download."
        )

    received: dict[int, bytes] = {}
    next_offset = 0
    retries_at_offset = 0
    bytes_done = 0

    while bytes_done < size:
        remaining = size - next_offset
        if remaining <= 0:
            # We've requested the tail; only gaps left to fetch.
            missing = _missing_offsets(received, size)
            if not missing:
                break
            next_offset = missing[0]
            remaining = size - next_offset

        conn.mav.log_request_data_send(
            conn.target_system,
            conn.target_component,
            log_id,
            next_offset,
            min(remaining, 0xFFFFFFFF),
        )

        last_recv = time.monotonic()
        while time.monotonic() - last_recv < CHUNK_STALL_S:
            msg = conn.recv_match(type="LOG_DATA", blocking=True, timeout=0.2)
            if msg is None:
                continue
            if int(msg.id) != log_id:
                continue
            ofs = int(msg.ofs)
            if ofs in received:
                continue
            count = int(msg.count)
            chunk = bytes(msg.data[:count])
            received[ofs] = chunk
            bytes_done = sum(len(c) for c in received.values())
            last_recv = time.monotonic()
            if progress_cb is not None:
                progress_cb(min(bytes_done, size), size)
            if bytes_done >= size:
                break

        if bytes_done >= size:
            break

        missing = _missing_offsets(received, size)
        if not missing:
            break
        if missing[0] == next_offset:
            retries_at_offset += 1
            if retries_at_offset > MAX_OFFSET_RETRIES:
                raise LogDownloadError(
                    f"Stalled at offset {next_offset} after "
                    f"{MAX_OFFSET_RETRIES} retries; got "
                    f"{bytes_done}/{size} bytes."
                )
        else:
            retries_at_offset = 0
        next_offset = missing[0]

    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as f:
        for ofs in sorted(received.keys()):
            f.write(received[ofs])

    try:
        conn.mav.log_request_end_send(
            conn.target_system, conn.target_component
        )
    except Exception:
        # Best-effort courtesy close; failure is non-fatal.
        pass

    return dest


def download_latest_log(
    conn: Any,
    dest_dir: Path,
    *,
    progress_cb: Callable[[int, int], None] | None = None,
    timestamp: str | None = None,
) -> Path:
    """Download the most recent log into `dest_dir` and return its path."""
    entries = list_logs(conn)
    # Latest log = highest id. Some autopilots report the active log
    # with size=0 until it's sealed, so we walk back to the newest
    # entry with non-zero size.
    candidate: LogEntry | None = None
    for entry in reversed(entries):
        if entry.size > 0:
            candidate = entry
            break
    if candidate is None:
        raise LogDownloadError(
            "All LOG_ENTRY entries reported size=0. "
            "Disarm first so the active log is sealed."
        )

    if timestamp is None:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"sim_dataflash_{timestamp}_log{candidate.log_id}.bin"
    return download_log(
        conn,
        candidate.log_id,
        candidate.size,
        dest,
        progress_cb=progress_cb,
    )
