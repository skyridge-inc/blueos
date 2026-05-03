"""Tests for the dataflash log downloader."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from skynet.log_download import (
    CHUNK_SIZE,
    LogDownloadError,
    LogEntry,
    download_latest_log,
    download_log,
    list_logs,
)


def _entry_msg(log_id: int, num_logs: int, last_log_num: int, size: int) -> Any:
    m = MagicMock()
    m.id = log_id
    m.num_logs = num_logs
    m.last_log_num = last_log_num
    m.time_utc = 0
    m.size = size
    return m


def _data_msg(log_id: int, ofs: int, payload: bytes) -> Any:
    m = MagicMock()
    m.id = log_id
    m.ofs = ofs
    m.count = len(payload)
    # Pad to 90 like the real wire format; download_log uses count to slice.
    m.data = list(payload) + [0] * (CHUNK_SIZE - len(payload))
    return m


class _ScriptedConn:
    """Mock conn that returns scripted recv_match responses by type."""

    def __init__(self, scripts: dict[str, list[Any]]):
        self.target_system = 1
        self.target_component = 1
        self.mav = MagicMock()
        self._scripts = {k: list(v) for k, v in scripts.items()}

    def recv_match(self, type: str, blocking: bool = False, timeout: float | None = None) -> Any:
        queue = self._scripts.get(type, [])
        if not queue:
            return None
        return queue.pop(0)


class TestListLogs:
    def test_returns_sorted_entries(self):
        conn = _ScriptedConn({
            "LOG_ENTRY": [
                _entry_msg(2, 3, 2, 200),
                _entry_msg(1, 3, 2, 100),
                _entry_msg(0, 3, 2, 50),
            ]
        })
        entries = list_logs(conn, timeout=1.0)
        assert [e.log_id for e in entries] == [0, 1, 2]
        conn.mav.log_request_list_send.assert_called_once_with(1, 1, 0, 0xFFFF)

    def test_raises_when_no_entries(self):
        conn = _ScriptedConn({"LOG_ENTRY": []})
        with pytest.raises(LogDownloadError, match="no LOG_ENTRY"):
            list_logs(conn, timeout=0.2)

    def test_stops_when_num_logs_satisfied(self):
        conn = _ScriptedConn({
            "LOG_ENTRY": [
                _entry_msg(0, 2, 1, 50),
                _entry_msg(1, 2, 1, 100),
                _entry_msg(2, 2, 1, 999),  # extra, should be ignored
            ]
        })
        entries = list_logs(conn, timeout=2.0)
        assert len(entries) == 2


class TestDownloadLog:
    def test_simple_full_download(self, tmp_path):
        log_id = 7
        size = CHUNK_SIZE * 3  # 270 bytes
        chunks = [
            _data_msg(log_id, 0, b"a" * CHUNK_SIZE),
            _data_msg(log_id, CHUNK_SIZE, b"b" * CHUNK_SIZE),
            _data_msg(log_id, 2 * CHUNK_SIZE, b"c" * CHUNK_SIZE),
        ]
        conn = _ScriptedConn({"LOG_DATA": chunks})

        dest = tmp_path / "out.bin"
        out = download_log(conn, log_id, size, dest)

        assert out == dest
        assert dest.read_bytes() == b"a" * CHUNK_SIZE + b"b" * CHUNK_SIZE + b"c" * CHUNK_SIZE

    def test_partial_final_chunk(self, tmp_path):
        log_id = 9
        size = CHUNK_SIZE + 30
        chunks = [
            _data_msg(log_id, 0, b"x" * CHUNK_SIZE),
            _data_msg(log_id, CHUNK_SIZE, b"y" * 30),
        ]
        conn = _ScriptedConn({"LOG_DATA": chunks})
        dest = tmp_path / "p.bin"
        download_log(conn, log_id, size, dest)
        assert dest.read_bytes() == b"x" * CHUNK_SIZE + b"y" * 30

    def test_ignores_other_log_ids(self, tmp_path):
        log_id = 4
        size = CHUNK_SIZE
        chunks = [
            _data_msg(99, 0, b"WRONG" * 18),  # 90 bytes, wrong id
            _data_msg(log_id, 0, b"R" * CHUNK_SIZE),
        ]
        conn = _ScriptedConn({"LOG_DATA": chunks})
        dest = tmp_path / "i.bin"
        download_log(conn, log_id, size, dest)
        assert dest.read_bytes() == b"R" * CHUNK_SIZE

    def test_dedupes_duplicate_offsets(self, tmp_path):
        log_id = 5
        size = CHUNK_SIZE * 2
        chunks = [
            _data_msg(log_id, 0, b"A" * CHUNK_SIZE),
            _data_msg(log_id, 0, b"A" * CHUNK_SIZE),  # duplicate
            _data_msg(log_id, CHUNK_SIZE, b"B" * CHUNK_SIZE),
        ]
        conn = _ScriptedConn({"LOG_DATA": chunks})
        dest = tmp_path / "d.bin"
        download_log(conn, log_id, size, dest)
        assert dest.read_bytes() == b"A" * CHUNK_SIZE + b"B" * CHUNK_SIZE

    def test_raises_when_size_zero(self, tmp_path):
        conn = _ScriptedConn({"LOG_DATA": []})
        with pytest.raises(LogDownloadError, match="size=0"):
            download_log(conn, 1, 0, tmp_path / "z.bin")

    def test_progress_callback(self, tmp_path):
        log_id = 1
        size = CHUNK_SIZE * 2
        chunks = [
            _data_msg(log_id, 0, b"a" * CHUNK_SIZE),
            _data_msg(log_id, CHUNK_SIZE, b"b" * CHUNK_SIZE),
        ]
        conn = _ScriptedConn({"LOG_DATA": chunks})

        seen: list[tuple[int, int]] = []
        download_log(
            conn, log_id, size, tmp_path / "pr.bin",
            progress_cb=lambda done, total: seen.append((done, total)),
        )
        assert seen == [(CHUNK_SIZE, size), (size, size)]

    def test_stalls_then_raises(self, tmp_path, monkeypatch):
        # No data ever returned — should hit MAX_OFFSET_RETRIES and raise.
        conn = _ScriptedConn({"LOG_DATA": []})

        # Speed up the test by making every recv_match wait short.
        # The CHUNK_STALL_S of 1.0 means each retry takes ~1s; 5 retries = 5s.
        # Patch the constants module-wide to keep total under 1s.
        from skynet import log_download as ld
        monkeypatch.setattr(ld, "CHUNK_STALL_S", 0.05)
        monkeypatch.setattr(ld, "MAX_OFFSET_RETRIES", 2)

        with pytest.raises(LogDownloadError, match="Stalled at offset 0"):
            download_log(conn, 1, CHUNK_SIZE * 4, tmp_path / "s.bin")


class TestDownloadLatestLog:
    def test_picks_largest_id_with_nonzero_size(self, tmp_path):
        log_id = 3
        size = CHUNK_SIZE
        conn = _ScriptedConn({
            "LOG_ENTRY": [
                _entry_msg(1, 3, 3, 100),
                _entry_msg(2, 3, 3, 200),
                _entry_msg(log_id, 3, 3, size),
            ],
            "LOG_DATA": [_data_msg(log_id, 0, b"L" * CHUNK_SIZE)],
        })
        out = download_latest_log(conn, tmp_path, timestamp="20260503_120000")
        assert out.name == f"sim_dataflash_20260503_120000_log{log_id}.bin"
        assert out.read_bytes() == b"L" * CHUNK_SIZE

    def test_skips_active_zero_size_log(self, tmp_path):
        # Latest log has size=0 (still active). Should fall back to the
        # most recent sealed log.
        sealed_id = 2
        conn = _ScriptedConn({
            "LOG_ENTRY": [
                _entry_msg(1, 3, 3, 50),
                _entry_msg(sealed_id, 3, 3, CHUNK_SIZE),
                _entry_msg(3, 3, 3, 0),  # active, unsealed
            ],
            "LOG_DATA": [_data_msg(sealed_id, 0, b"S" * CHUNK_SIZE)],
        })
        out = download_latest_log(conn, tmp_path, timestamp="t")
        assert f"log{sealed_id}" in out.name

    def test_raises_when_all_zero_size(self, tmp_path):
        conn = _ScriptedConn({
            "LOG_ENTRY": [_entry_msg(0, 1, 0, 0)],
        })
        with pytest.raises(LogDownloadError, match="size=0"):
            download_latest_log(conn, tmp_path)
