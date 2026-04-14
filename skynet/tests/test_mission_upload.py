"""Tests for the MAVLink mission upload state machine and CLI wiring."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pymavlink import mavutil
from typer.testing import CliRunner

from skynet.cli import app
from skynet.exceptions import MissionUploadError, MowerProvisionerError
from skynet.mission_planning import read_waypoints, write_waypoints
from skynet.mission_upload import upload_mission


def _make_request(seq: int, int_form: bool = True) -> MagicMock:
    msg = MagicMock()
    msg.get_type.return_value = (
        "MISSION_REQUEST_INT" if int_form else "MISSION_REQUEST"
    )
    msg.seq = seq
    return msg


def _make_ack(result: int) -> MagicMock:
    msg = MagicMock()
    msg.get_type.return_value = "MISSION_ACK"
    msg.type = result
    return msg


def _fake_conn(messages: list) -> MagicMock:
    """Build a mock conn whose recv_match pops from a script."""
    conn = MagicMock()
    conn.target_system = 1
    conn.target_component = 1
    conn.mav = MagicMock()
    # Mutable list so retries can be observed in tests.
    conn._inbox = list(messages)

    def _recv_match(type=None, blocking=True, timeout=None):
        if not conn._inbox:
            return None
        head = conn._inbox[0]
        # Support sentinel None = "simulate timeout once"
        if head is None:
            conn._inbox.pop(0)
            return None
        if isinstance(type, list):
            if head.get_type() not in type:
                return None
        elif type is not None:
            if head.get_type() != type:
                return None
        return conn._inbox.pop(0)

    conn.recv_match.side_effect = _recv_match
    return conn


class TestUploadMission:
    def test_successful_upload(self):
        items = [(40.0, -80.0), (40.001, -80.0), (40.002, -80.0)]
        conn = _fake_conn(
            [
                _make_request(0),
                _make_request(1),
                _make_request(2),
                _make_ack(mavutil.mavlink.MAV_MISSION_ACCEPTED),
            ]
        )

        progress: list[tuple[int, int]] = []
        upload_mission(
            conn, items, progress_callback=lambda s, t: progress.append((s, t))
        )

        # MISSION_COUNT was sent once with the right count + type
        conn.mav.mission_count_send.assert_called_once()
        count_args = conn.mav.mission_count_send.call_args.args
        assert count_args[0] == 1  # target_system
        assert count_args[1] == 1  # target_component
        assert count_args[2] == 3  # count
        assert count_args[3] == mavutil.mavlink.MAV_MISSION_TYPE_MISSION

        # MISSION_ITEM_INT sent once per seq, in order
        assert conn.mav.mission_item_int_send.call_count == 3
        for seq, call in enumerate(conn.mav.mission_item_int_send.call_args_list):
            args = call.args
            assert args[2] == seq  # seq
            assert args[3] == mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT
            assert args[4] == mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
            assert args[5] == (1 if seq == 0 else 0)  # current
            assert args[6] == 1  # autocontinue
            # lat/lon scaled int32
            assert args[11] == int(round(items[seq][0] * 1e7))
            assert args[12] == int(round(items[seq][1] * 1e7))
            assert args[14] == mavutil.mavlink.MAV_MISSION_TYPE_MISSION

        # Progress fired for every item, ending at total
        assert progress == [(1, 3), (2, 3), (3, 3)]

    def test_rejected_mission_raises(self):
        items = [(40.0, -80.0), (40.001, -80.0)]
        conn = _fake_conn(
            [
                _make_request(0),
                _make_request(1),
                _make_ack(mavutil.mavlink.MAV_MISSION_ERROR),
            ]
        )
        with pytest.raises(MissionUploadError, match="seq 1"):
            upload_mission(conn, items)

    def test_early_ack_accepted_counts_as_success(self):
        """ArduPilot 4.6+ sometimes ACKs after seqs 1..N-1 without
        requesting seq 0 (the home row). An ACCEPTED ack mid-upload
        should be treated as success, not a premature-ack error."""
        items = [(40.0, -80.0), (40.001, -80.0), (40.002, -80.0)]  # 3 items
        # Autopilot requests only seqs 1 and 2 (skipping seq 0), then ACKs.
        conn = _fake_conn(
            [
                _make_request(1),
                _make_request(2),
                _make_ack(mavutil.mavlink.MAV_MISSION_ACCEPTED),
            ]
        )
        # Must not raise.
        upload_mission(conn, items)
        # Only 2 items should have been sent (seqs 1 and 2).
        assert conn.mav.mission_item_int_send.call_count == 2
        sent_seqs = [
            c.args[2] for c in conn.mav.mission_item_int_send.call_args_list
        ]
        assert sent_seqs == [1, 2]

    def test_early_ack_error_still_raises(self):
        """A non-ACCEPTED early ack is still a failure."""
        items = [(40.0, -80.0), (40.001, -80.0), (40.002, -80.0)]
        conn = _fake_conn(
            [
                _make_request(0),
                _make_ack(mavutil.mavlink.MAV_MISSION_ERROR),
            ]
        )
        with pytest.raises(MissionUploadError, match="rejected early"):
            upload_mission(conn, items)

    def test_legacy_mission_request_accepted(self):
        items = [(40.0, -80.0), (40.001, -80.0)]
        conn = _fake_conn(
            [
                _make_request(0, int_form=False),
                _make_request(1, int_form=False),
                _make_ack(mavutil.mavlink.MAV_MISSION_ACCEPTED),
            ]
        )
        upload_mission(conn, items)
        assert conn.mav.mission_item_int_send.call_count == 2

    def test_retry_on_single_timeout(self):
        items = [(40.0, -80.0), (40.001, -80.0)]
        conn = _fake_conn(
            [
                _make_request(0),
                None,  # timeout waiting for seq 1
                _make_request(1),
                _make_ack(mavutil.mavlink.MAV_MISSION_ACCEPTED),
            ]
        )
        upload_mission(conn, items, timeout=0.01)
        # seq 1 was sent twice (retry), seq 0 once → 3 total sends
        assert conn.mav.mission_item_int_send.call_count == 3
        sent_seqs = [
            c.args[2] for c in conn.mav.mission_item_int_send.call_args_list
        ]
        assert sent_seqs == [0, 1, 1]

    def test_second_timeout_fails(self):
        items = [(40.0, -80.0), (40.001, -80.0)]
        conn = _fake_conn(
            [
                _make_request(0),
                None,
                None,
            ]
        )
        with pytest.raises(MissionUploadError, match="seq 1"):
            upload_mission(conn, items, timeout=0.01)

    def test_empty_items_rejected(self):
        conn = _fake_conn([])
        with pytest.raises(MissionUploadError, match="empty"):
            upload_mission(conn, [])
        conn.mav.mission_count_send.assert_not_called()

    def test_hierarchy(self):
        assert issubclass(MissionUploadError, MowerProvisionerError)


class TestReadWaypointsIncludeHome:
    def test_include_home_round_trip(self, tmp_path: Path):
        wps = [(40.1, -80.1), (40.2, -80.2), (40.3, -80.3)]
        home = (39.9, -79.9)
        path = str(tmp_path / "m.waypoints")
        write_waypoints(path, wps, home=home)

        result = read_waypoints(path, include_home=True)
        assert len(result) == 4
        assert result[0] == pytest.approx(home, abs=1e-8)
        for got, want in zip(result[1:], wps):
            assert got == pytest.approx(want, abs=1e-8)

    def test_default_skips_home(self, tmp_path: Path):
        wps = [(40.1, -80.1), (40.2, -80.2)]
        path = str(tmp_path / "m.waypoints")
        write_waypoints(path, wps, home=(39.9, -79.9))
        result = read_waypoints(path)
        assert len(result) == 2


class TestNavUploadCli:
    def test_dry_run_opens_no_connection(self, tmp_path: Path, monkeypatch):
        wps = [(40.1, -80.1), (40.2, -80.2)]
        path = tmp_path / "m.waypoints"
        write_waypoints(str(path), wps, home=(39.9, -79.9))

        # Fail loudly if anyone touches MAVLink.
        import skynet.cli as cli_mod

        def _boom(*a, **kw):
            raise AssertionError(
                "mavlink_connection must not be opened in dry-run"
            )

        monkeypatch.setattr(cli_mod, "mavlink_connection", _boom)

        runner = CliRunner()
        result = runner.invoke(
            app, ["nav", "upload", str(path), "--dry-run"]
        )
        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output
        assert "home" in result.output
        assert "wp1" in result.output
        assert "wp2" in result.output

    def test_missing_file(self, tmp_path: Path):
        runner = CliRunner()
        result = runner.invoke(
            app, ["nav", "upload", str(tmp_path / "nope.waypoints")]
        )
        assert result.exit_code != 0
