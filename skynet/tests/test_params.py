"""Tests for params module — fetch, write, and diff logic."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from mower_provisioner.params import (
    EPSILON,
    ParamDiff,
    diff_params,
    fetch_all_params,
    write_params,
)
from mower_provisioner.exceptions import ParameterFetchError, ParameterWriteError


class TestDiffParams:
    def test_no_differences(self):
        params = {"A": 1.0, "B": 2.0}
        result = diff_params(params, params)
        assert not result.has_differences
        assert result.total_changes == 0

    def test_added_params(self):
        file_params = {"A": 1.0, "B": 2.0}
        device_params = {"A": 1.0}
        result = diff_params(file_params, device_params)
        assert result.added == {"B": 2.0}
        assert not result.changed
        assert not result.removed

    def test_removed_params(self):
        file_params = {"A": 1.0}
        device_params = {"A": 1.0, "B": 2.0}
        result = diff_params(file_params, device_params)
        assert result.removed == {"B": 2.0}
        assert not result.added
        assert not result.changed

    def test_changed_params(self):
        file_params = {"A": 1.0, "B": 3.0}
        device_params = {"A": 1.0, "B": 2.0}
        result = diff_params(file_params, device_params)
        assert result.changed == {"B": (3.0, 2.0)}
        assert not result.added
        assert not result.removed

    def test_epsilon_tolerance(self):
        file_params = {"A": 1.0}
        device_params = {"A": 1.0 + EPSILON / 2}
        result = diff_params(file_params, device_params)
        assert not result.has_differences

    def test_calibration_excluded_by_default(self):
        file_params = {"CRUISE_SPEED": 2.5, "INS_ACCOFFS_X": 0.1}
        device_params = {"CRUISE_SPEED": 2.5, "INS_ACCOFFS_X": 0.9}
        result = diff_params(file_params, device_params)
        assert not result.has_differences  # INS_ACCOFFS_X excluded

    def test_calibration_included(self):
        file_params = {"INS_ACCOFFS_X": 0.1}
        device_params = {"INS_ACCOFFS_X": 0.9}
        result = diff_params(file_params, device_params, include_calibration=True)
        assert result.changed == {"INS_ACCOFFS_X": (0.1, 0.9)}

    def test_mixed_changes(self):
        file_params = {"A": 1.0, "B": 5.0, "C": 3.0}
        device_params = {"A": 1.0, "B": 2.0, "D": 4.0}
        result = diff_params(file_params, device_params)
        assert result.added == {"C": 3.0}
        assert result.changed == {"B": (5.0, 2.0)}
        assert result.removed == {"D": 4.0}
        assert result.total_changes == 3


class TestWriteParams:
    def test_dry_run_returns_names(self, mock_conn):
        params = {"A": 1.0, "B": 2.0}
        result = write_params(mock_conn, params, dry_run=True)
        assert result == ["A", "B"]
        mock_conn.mav.param_set_send.assert_not_called()

    def test_calibration_excluded_by_default(self, mock_conn):
        params = {"CRUISE_SPEED": 2.5, "INS_ACCOFFS_X": 0.1}
        result = write_params(mock_conn, params, dry_run=True)
        assert result == ["CRUISE_SPEED"]

    def test_calibration_included(self, mock_conn):
        params = {"CRUISE_SPEED": 2.5, "INS_ACCOFFS_X": 0.1}
        result = write_params(
            mock_conn, params, dry_run=True, include_calibration=True
        )
        assert "INS_ACCOFFS_X" in result

    def test_write_sends_and_waits_for_ack(self, mock_conn):
        # Setup ack response
        ack_msg = MagicMock()
        ack_msg.param_id = "CRUISE_SPEED"
        mock_conn.recv_match.return_value = ack_msg

        result = write_params(mock_conn, {"CRUISE_SPEED": 2.5})
        assert result == ["CRUISE_SPEED"]
        mock_conn.mav.param_set_send.assert_called_once()

    def test_write_failure_raises(self, mock_conn):
        mock_conn.recv_match.return_value = None  # no ack
        with pytest.raises(ParameterWriteError, match="Failed to write"):
            write_params(mock_conn, {"CRUISE_SPEED": 2.5})


class TestFetchAllParams:
    def _make_param_msg(self, name: str, value: float, index: int, count: int):
        msg = MagicMock()
        msg.param_id = name.encode("utf-8")
        msg.param_value = value
        msg.param_index = index
        msg.param_count = count
        return msg

    def test_fetch_basic(self, mock_conn):
        msgs = [
            self._make_param_msg("A", 1.0, 0, 2),
            self._make_param_msg("B", 2.0, 1, 2),
        ]
        mock_conn.recv_match.side_effect = msgs

        result = fetch_all_params(mock_conn, timeout=5.0)
        assert result == {"A": 1.0, "B": 2.0}

    def test_fetch_timeout_raises(self, mock_conn):
        mock_conn.recv_match.return_value = None
        with pytest.raises(ParameterFetchError, match="Timeout"):
            fetch_all_params(mock_conn, timeout=0.1)

    def test_progress_callback(self, mock_conn):
        msgs = [
            self._make_param_msg("A", 1.0, 0, 2),
            self._make_param_msg("B", 2.0, 1, 2),
        ]
        mock_conn.recv_match.side_effect = msgs

        calls = []
        fetch_all_params(
            mock_conn,
            timeout=5.0,
            progress_callback=lambda r, t: calls.append((r, t)),
        )
        assert calls == [(1, 2), (2, 2)]
