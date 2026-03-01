"""Parameter fetch, write, and diff logic."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from pymavlink import mavutil

from .config import CALIBRATION_PARAMS
from .exceptions import ParameterFetchError, ParameterWriteError

# Tolerance for floating-point comparison
EPSILON = 1e-6

# Gap detection: seconds to wait before re-requesting missing params
GAP_TIMEOUT = 2.0

# Maximum retries for gap filling
MAX_GAP_RETRIES = 3

# Write retry count per parameter
WRITE_RETRIES = 3


def fetch_all_params(
    conn: Any,
    *,
    timeout: float = 30.0,
    progress_callback: Any | None = None,
) -> dict[str, float]:
    """Fetch all parameters from connected device using index-based gap detection.

    Args:
        conn: mavutil connection with target_system/target_component set.
        timeout: Overall timeout for the fetch operation.
        progress_callback: Optional callable(received, total) for progress updates.

    Returns:
        Dict of parameter name -> value.

    Raises:
        ParameterFetchError: If parameters cannot be fetched.
    """
    # Request all parameters
    conn.mav.param_request_list_send(
        conn.target_system, conn.target_component
    )

    params: dict[str, float] = {}
    param_count: int | None = None
    received_indices: set[int] = set()
    start = time.monotonic()
    last_recv = start

    while True:
        elapsed = time.monotonic() - start
        if elapsed > timeout:
            raise ParameterFetchError(
                f"Timeout after {timeout}s — received {len(params)}/{param_count or '?'} params"
            )

        msg = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=1.0)
        if msg is None:
            # Check for gaps if we know total count
            if param_count is not None and time.monotonic() - last_recv > GAP_TIMEOUT:
                missing = set(range(param_count)) - received_indices
                if not missing:
                    break
                # Re-request missing by index
                for idx in sorted(missing)[:10]:  # batch of 10
                    conn.mav.param_request_read_send(
                        conn.target_system,
                        conn.target_component,
                        b"",
                        idx,
                    )
            continue

        last_recv = time.monotonic()
        name = msg.param_id
        if isinstance(name, bytes):
            name = name.decode("utf-8").rstrip("\x00")

        params[name] = msg.param_value
        received_indices.add(msg.param_index)

        if param_count is None:
            param_count = msg.param_count

        if progress_callback:
            progress_callback(len(params), param_count)

        # All received?
        if param_count is not None and len(received_indices) >= param_count:
            break

    return params


def write_params(
    conn: Any,
    params: dict[str, float],
    *,
    include_calibration: bool = False,
    dry_run: bool = False,
    progress_callback: Any | None = None,
) -> list[str]:
    """Write parameters to connected device.

    Uses mavset() for battle-tested retry/encoding logic.

    Args:
        conn: mavutil connection.
        params: Dict of parameter name -> value to write.
        include_calibration: If False, skip calibration params.
        dry_run: If True, return list of params that would be written without writing.
        progress_callback: Optional callable(written, total) for progress updates.

    Returns:
        List of parameter names that were written (or would be written if dry_run).

    Raises:
        ParameterWriteError: If a parameter write fails after retries.
    """
    to_write: dict[str, float] = {}
    for name, value in sorted(params.items()):
        if not include_calibration and name in CALIBRATION_PARAMS:
            continue
        to_write[name] = value

    if dry_run:
        return list(to_write.keys())

    written: list[str] = []
    total = len(to_write)

    for i, (name, value) in enumerate(to_write.items()):
        success = False
        for attempt in range(WRITE_RETRIES):
            conn.mav.param_set_send(
                conn.target_system,
                conn.target_component,
                name.encode("utf-8"),
                value,
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
            )
            # Wait for acknowledgement
            ack = conn.recv_match(type="PARAM_VALUE", blocking=True, timeout=5.0)
            if ack is not None:
                ack_name = ack.param_id
                if isinstance(ack_name, bytes):
                    ack_name = ack_name.decode("utf-8").rstrip("\x00")
                if ack_name == name:
                    success = True
                    break

        if not success:
            raise ParameterWriteError(
                f"Failed to write {name}={value} after {WRITE_RETRIES} attempts"
            )

        written.append(name)
        if progress_callback:
            progress_callback(i + 1, total)

    return written


@dataclass
class ParamDiff:
    """Result of comparing file params vs device params."""

    added: dict[str, float]  # in file but not on device
    changed: dict[str, tuple[float, float]]  # name -> (file_value, device_value)
    removed: dict[str, float]  # on device but not in file

    @property
    def has_differences(self) -> bool:
        return bool(self.added or self.changed or self.removed)

    @property
    def total_changes(self) -> int:
        return len(self.added) + len(self.changed) + len(self.removed)


def diff_params(
    file_params: dict[str, float],
    device_params: dict[str, float],
    *,
    include_calibration: bool = False,
    epsilon: float = EPSILON,
) -> ParamDiff:
    """Compute differences between file parameters and device parameters.

    Args:
        file_params: Parameters from .param file.
        device_params: Parameters from device.
        include_calibration: If False, exclude calibration params from diff.
        epsilon: Tolerance for float comparison.

    Returns:
        ParamDiff with added, changed, and removed params.
    """
    added: dict[str, float] = {}
    changed: dict[str, tuple[float, float]] = {}
    removed: dict[str, float] = {}

    all_names = set(file_params) | set(device_params)

    for name in sorted(all_names):
        if not include_calibration and name in CALIBRATION_PARAMS:
            continue

        in_file = name in file_params
        in_device = name in device_params

        if in_file and not in_device:
            added[name] = file_params[name]
        elif not in_file and in_device:
            removed[name] = device_params[name]
        elif in_file and in_device:
            fval = file_params[name]
            dval = device_params[name]
            if abs(fval - dval) > epsilon:
                changed[name] = (fval, dval)

    return ParamDiff(added=added, changed=changed, removed=removed)
