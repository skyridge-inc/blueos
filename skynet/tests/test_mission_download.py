"""Tests for the MAVLink mission download state machine."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from pymavlink import mavutil

from skynet.exceptions import MissionDownloadError, MowerProvisionerError
from skynet.mission_download import download_mission


def _count(n: int) -> MagicMock:
    msg = MagicMock()
    msg.get_type.return_value = "MISSION_COUNT"
    msg.count = n
    return msg


def _item(seq: int, lat: float, lon: float) -> MagicMock:
    msg = MagicMock()
    msg.get_type.return_value = "MISSION_ITEM_INT"
    msg.seq = seq
    msg.x = int(round(lat * 1e7))
    msg.y = int(round(lon * 1e7))
    return msg


def _fake_conn(messages: list) -> MagicMock:
    conn = MagicMock()
    conn.target_system = 1
    conn.target_component = 1
    conn.mav = MagicMock()
    conn._inbox = list(messages)

    def _recv_match(type=None, blocking=True, timeout=None):
        if not conn._inbox:
            return None
        head = conn._inbox[0]
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


class TestDownloadMission:
    def test_happy_path(self):
        conn = _fake_conn(
            [
                _count(3),
                _item(0, 40.0, -80.0),
                _item(1, 40.001, -80.0),
                _item(2, 40.002, -80.0),
            ]
        )
        result = download_mission(conn)
        assert len(result) == 3
        assert result[0] == pytest.approx((40.0, -80.0), abs=1e-7)
        assert result[1] == pytest.approx((40.001, -80.0), abs=1e-7)
        assert result[2] == pytest.approx((40.002, -80.0), abs=1e-7)

        # MISSION_REQUEST_LIST sent once, REQUEST_INT once per seq, ACK at end
        conn.mav.mission_request_list_send.assert_called_once()
        assert conn.mav.mission_request_int_send.call_count == 3
        seqs = [c.args[2] for c in conn.mav.mission_request_int_send.call_args_list]
        assert seqs == [0, 1, 2]
        conn.mav.mission_ack_send.assert_called_once()
        ack_args = conn.mav.mission_ack_send.call_args.args
        assert ack_args[2] == mavutil.mavlink.MAV_MISSION_ACCEPTED
        assert ack_args[3] == mavutil.mavlink.MAV_MISSION_TYPE_MISSION

    def test_progress_callback(self):
        conn = _fake_conn(
            [
                _count(2),
                _item(0, 40.0, -80.0),
                _item(1, 40.001, -80.0),
            ]
        )
        progress: list[tuple[int, int]] = []
        download_mission(
            conn, progress_callback=lambda r, t: progress.append((r, t))
        )
        assert progress == [(1, 2), (2, 2)]

    def test_empty_mission_rejected(self):
        conn = _fake_conn([_count(0)])
        with pytest.raises(MissionDownloadError, match="no mission"):
            download_mission(conn)
        conn.mav.mission_request_int_send.assert_not_called()

    def test_only_home_rejected(self):
        conn = _fake_conn([_count(1)])
        with pytest.raises(MissionDownloadError, match="only a home"):
            download_mission(conn)

    def test_retry_on_per_item_timeout(self):
        conn = _fake_conn(
            [
                _count(2),
                _item(0, 40.0, -80.0),
                None,  # miss seq 1 first time
                _item(1, 40.001, -80.0),
            ]
        )
        result = download_mission(conn, timeout=0.01)
        assert len(result) == 2
        # REQUEST_INT sent for seq 0 once, seq 1 twice
        seqs = [c.args[2] for c in conn.mav.mission_request_int_send.call_args_list]
        assert seqs == [0, 1, 1]

    def test_second_timeout_fails(self):
        conn = _fake_conn(
            [
                _count(2),
                _item(0, 40.0, -80.0),
                None,
                None,
            ]
        )
        with pytest.raises(MissionDownloadError, match="seq 1"):
            download_mission(conn, timeout=0.01)

    def test_out_of_range_seq(self):
        conn = _fake_conn(
            [
                _count(3),
                _item(0, 40.0, -80.0),
                _item(99, 40.001, -80.0),
            ]
        )
        with pytest.raises(MissionDownloadError, match="out-of-range"):
            download_mission(conn, timeout=0.01)

    def test_count_timeout_retries(self):
        conn = _fake_conn(
            [
                None,  # no MISSION_COUNT first time
                _count(2),
                _item(0, 40.0, -80.0),
                _item(1, 40.001, -80.0),
            ]
        )
        download_mission(conn, timeout=0.01)
        assert conn.mav.mission_request_list_send.call_count == 2

    def test_count_timeout_twice_fails(self):
        conn = _fake_conn([None, None])
        with pytest.raises(MissionDownloadError, match="MISSION_COUNT"):
            download_mission(conn, timeout=0.01)

    def test_round_trip_with_upload(self):
        from skynet.mission_upload import upload_mission

        items = [(40.0, -80.0), (40.001, -80.001), (40.002, -80.002), (40.003, -80.003)]

        # Stage 1: build a fake autopilot that answers upload...
        up_conn = MagicMock()
        up_conn.target_system = 1
        up_conn.target_component = 1
        up_conn.mav = MagicMock()
        up_inbox = []
        for seq in range(len(items)):
            req = MagicMock()
            req.get_type.return_value = "MISSION_REQUEST_INT"
            req.seq = seq
            up_inbox.append(req)
        ack = MagicMock()
        ack.get_type.return_value = "MISSION_ACK"
        ack.type = mavutil.mavlink.MAV_MISSION_ACCEPTED
        up_inbox.append(ack)
        up_conn._inbox = up_inbox

        def _up_recv(type=None, blocking=True, timeout=None):
            if not up_conn._inbox:
                return None
            head = up_conn._inbox[0]
            if isinstance(type, list):
                if head.get_type() not in type:
                    return None
            return up_conn._inbox.pop(0)

        up_conn.recv_match.side_effect = _up_recv
        upload_mission(up_conn, items)

        # Reconstruct lat/lon from what the upload pushed into mission_item_int_send
        sent_items: list[tuple[float, float]] = []
        for call in up_conn.mav.mission_item_int_send.call_args_list:
            args = call.args
            sent_items.append((args[11] / 1e7, args[12] / 1e7))

        # Stage 2: feed those as a mission_download script
        dl_inbox = [_count(len(sent_items))]
        for seq, (lat, lon) in enumerate(sent_items):
            dl_inbox.append(_item(seq, lat, lon))
        dl_conn = _fake_conn(dl_inbox)
        result = download_mission(dl_conn)

        assert len(result) == len(items)
        for got, want in zip(result, items):
            assert got == pytest.approx(want, abs=1e-7)

    def test_hierarchy(self):
        assert issubclass(MissionDownloadError, MowerProvisionerError)
