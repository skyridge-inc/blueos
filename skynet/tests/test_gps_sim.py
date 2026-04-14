"""Tests for the GPS/heading simulator components and nav sim CLI."""

from __future__ import annotations

import math
import signal
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pymavlink import mavutil
from typer.testing import CliRunner

from skynet.cli import app
from skynet.exceptions import (
    FrameMismatchError,
    GpsSimError,
    MowerProvisionerError,
)
from skynet.gps_sim import (
    DRIVE_ACKERMANN,
    DRIVE_SKID_STEER,
    MPH_TO_MPS,
    SIM_PARAMS,
    AckermannModel,
    GpsInputEmitter,
    ServoNormalizer,
    SimParamContext,
    SkidSteerModel,
    StopWatcher,
    deduplicate_mission,
    detect_drive_type,
    device_slug,
    offset_spawn_behind_waypoint,
    request_diagnostic_streams,
    request_servo_output_stream,
    resolve_sim_params,
    set_target_groundspeed,
    severity_label,
    sidecar_path,
    validate_skid_steer,
    warn_on_zero_speed_params,
)


# ==================== SkidSteerModel ====================


class TestSkidSteerModel:
    def test_zero_throttle_stationary(self):
        m = SkidSteerModel(
            start_lat=40.0,
            start_lon=-80.0,
            max_speed_mps=1.0,
            track_width_m=0.5,
        )
        lat, lon, hdg, vn, ve = m.step(0.2, 0.0, 0.0)
        assert lat == pytest.approx(40.0, abs=1e-9)
        assert lon == pytest.approx(-80.0, abs=1e-9)
        assert vn == 0.0
        assert ve == 0.0
        assert hdg == 0.0

    def test_symmetric_forward_goes_north(self):
        m = SkidSteerModel(
            start_lat=40.0,
            start_lon=-80.0,
            start_heading_deg=0.0,
            max_speed_mps=1.0,
            track_width_m=0.5,
        )
        lat, lon, hdg, vn, ve = m.step(1.0, 1.0, 1.0)
        # Approximately 1 m north of start
        expected_lat = 40.0 + 1.0 / 111_320.0
        assert lat == pytest.approx(expected_lat, abs=1e-9)
        assert lon == pytest.approx(-80.0, abs=1e-9)
        assert vn == pytest.approx(1.0, abs=1e-9)
        assert ve == pytest.approx(0.0, abs=1e-9)
        assert hdg == pytest.approx(0.0, abs=1e-9)

    def test_full_reverse_both_goes_south(self):
        m = SkidSteerModel(
            start_lat=40.0,
            start_lon=-80.0,
            start_heading_deg=0.0,
            max_speed_mps=1.0,
            track_width_m=0.5,
        )
        lat, _, _, vn, _ = m.step(1.0, -1.0, -1.0)
        assert vn == pytest.approx(-1.0, abs=1e-9)
        assert lat < 40.0

    def test_in_place_pivot_leaves_position_alone(self):
        m = SkidSteerModel(
            start_lat=40.0,
            start_lon=-80.0,
            max_speed_mps=1.0,
            track_width_m=0.5,
        )
        start_lat, start_lon = m.lat, m.lon
        # 10 pivot steps: left=-1, right=+1 → v=0, omega nonzero
        for _ in range(10):
            m.step(0.01, -1.0, 1.0)
        assert m.lat == pytest.approx(start_lat, abs=1e-12)
        assert m.lon == pytest.approx(start_lon, abs=1e-12)
        assert m.heading_deg != 0.0

    def test_heading_east_integrates_east(self):
        m = SkidSteerModel(
            start_lat=40.0,
            start_lon=-80.0,
            start_heading_deg=90.0,  # east
            max_speed_mps=1.0,
            track_width_m=0.5,
        )
        lat, lon, _, vn, ve = m.step(1.0, 1.0, 1.0)
        assert vn == pytest.approx(0.0, abs=1e-9)
        assert ve == pytest.approx(1.0, abs=1e-9)
        assert lat == pytest.approx(40.0, abs=1e-9)
        assert lon > -80.0  # east of start

    def test_input_clamping(self):
        m = SkidSteerModel(
            start_lat=0.0,
            start_lon=0.0,
            max_speed_mps=1.0,
            track_width_m=0.5,
        )
        _, _, _, vn1, _ = m.step(1.0, 5.0, 5.0)  # both > 1
        assert vn1 == pytest.approx(1.0, abs=1e-9)


# ==================== AckermannModel ====================


class TestAckermannModel:
    def test_zero_throttle_stationary(self):
        m = AckermannModel(
            start_lat=40.0, start_lon=-80.0, max_speed_mps=1.0, wheelbase_m=0.5
        )
        lat, lon, hdg, vn, ve = m.step(0.2, 0.0, 0.0)
        assert lat == pytest.approx(40.0, abs=1e-9)
        assert lon == pytest.approx(-80.0, abs=1e-9)
        assert vn == 0.0
        assert ve == 0.0

    def test_straight_forward(self):
        m = AckermannModel(
            start_lat=40.0,
            start_lon=-80.0,
            start_heading_deg=0.0,
            max_speed_mps=1.0,
            wheelbase_m=0.5,
        )
        lat, lon, hdg, vn, ve = m.step(1.0, 0.0, 1.0)  # steer=0, throttle=1
        expected_lat = 40.0 + 1.0 / 111_320.0
        assert lat == pytest.approx(expected_lat, abs=1e-9)
        assert lon == pytest.approx(-80.0, abs=1e-9)
        assert hdg == pytest.approx(0.0, abs=1e-9)

    def test_right_turn(self):
        m = AckermannModel(
            start_lat=40.0,
            start_lon=-80.0,
            start_heading_deg=0.0,
            max_speed_mps=1.0,
            wheelbase_m=0.5,
            max_steer_angle_deg=45.0,
        )
        # Full right steer + full throttle for a short time
        _, _, hdg, _, _ = m.step(0.1, 1.0, 1.0)
        assert hdg > 0.0  # turned right (heading increased)

    def test_reverse(self):
        m = AckermannModel(
            start_lat=40.0,
            start_lon=-80.0,
            start_heading_deg=0.0,
            max_speed_mps=1.0,
            wheelbase_m=0.5,
        )
        lat, _, _, vn, _ = m.step(1.0, 0.0, -1.0)
        assert vn == pytest.approx(-1.0, abs=1e-9)
        assert lat < 40.0

    def test_zero_steer_no_heading_change(self):
        m = AckermannModel(
            start_lat=40.0,
            start_lon=-80.0,
            start_heading_deg=45.0,
            max_speed_mps=1.0,
            wheelbase_m=0.5,
        )
        _, _, hdg, _, _ = m.step(1.0, 0.0, 1.0)
        assert hdg == pytest.approx(45.0, abs=1e-9)


# ==================== ServoNormalizer ====================


class TestServoNormalizer:
    def _params(self, lo=1000, tr=1500, hi=2000):
        return {
            "SERVO1_MIN": float(lo),
            "SERVO1_TRIM": float(tr),
            "SERVO1_MAX": float(hi),
        }

    def test_trim_is_zero(self):
        n = ServoNormalizer(1, self._params())
        assert n.normalize(1500) == 0.0

    def test_full_forward(self):
        n = ServoNormalizer(1, self._params())
        assert n.normalize(2000) == 1.0

    def test_full_reverse(self):
        n = ServoNormalizer(1, self._params())
        assert n.normalize(1000) == -1.0

    def test_half_forward(self):
        n = ServoNormalizer(1, self._params())
        assert n.normalize(1750) == pytest.approx(0.5)

    def test_half_reverse(self):
        n = ServoNormalizer(1, self._params())
        assert n.normalize(1250) == pytest.approx(-0.5)

    def test_above_max_saturates(self):
        n = ServoNormalizer(1, self._params())
        assert n.normalize(2500) == 1.0

    def test_below_min_saturates(self):
        n = ServoNormalizer(1, self._params())
        assert n.normalize(500) == -1.0

    def test_missing_params_fallback(self, caplog):
        # Clear the class-level "already warned" set
        ServoNormalizer._warned.clear()
        with caplog.at_level("WARNING"):
            n = ServoNormalizer(7, {})
        assert n.min_pwm == 1000.0
        assert n.trim_pwm == 1500.0
        assert n.max_pwm == 2000.0
        assert any("SERVO7" in r.message for r in caplog.records)

    def test_asymmetric_trim(self):
        n = ServoNormalizer(1, self._params(lo=1100, tr=1500, hi=1900))
        assert n.normalize(1500) == 0.0
        assert n.normalize(1900) == 1.0
        assert n.normalize(1100) == -1.0


# ==================== SimParamContext ====================


class TestSimParamContext:
    def _fake_conn_with_params(self, original: dict[str, float]) -> MagicMock:
        conn = MagicMock()
        conn.target_system = 1
        conn.target_component = 1
        conn.mav = MagicMock()

        # Drive fetch_all_params via scripted PARAM_VALUE messages
        names = sorted(original)
        total = len(names)
        inbox: list = []
        for idx, name in enumerate(names):
            m = MagicMock()
            m.get_type.return_value = "PARAM_VALUE"
            m.param_id = name.encode()
            m.param_value = original[name]
            m.param_count = total
            m.param_index = idx
            inbox.append(m)
        conn._inbox = inbox

        def _recv(type=None, blocking=True, timeout=None):
            if not conn._inbox:
                return None
            head = conn._inbox[0]
            if isinstance(type, list):
                if head.get_type() not in type:
                    return None
            elif type is not None and head.get_type() != type:
                return None
            # For write_params ack simulation, echo the param_id
            return conn._inbox.pop(0)

        conn.recv_match.side_effect = _recv
        return conn

    def _originals(self):
        return {name: 0.0 for name in SIM_PARAMS}

    def test_sidecar_path_derived(self, tmp_path: Path):
        p = sidecar_path("tcp:192.168.2.2:5760", sidecar_dir=tmp_path)
        assert p.parent == tmp_path
        assert "tcp_192_168_2_2_5760" in p.name

    def test_device_slug(self):
        assert device_slug("/dev/ttyACM0") == "_dev_ttyACM0"
        assert device_slug("tcp:192.168.2.2:5760") == "tcp_192_168_2_2_5760"

    def test_leftover_sidecar_loaded_and_cleared(self, tmp_path: Path):
        """A leftover sidecar's contents should become the restore originals,
        then the file should be deleted and re-created fresh."""
        conn = MagicMock()
        conn.target_system = 1
        conn.target_component = 1
        conn.mav = MagicMock()

        existing = tmp_path / "sim_restore_test.param"
        # Prior-run originals: GPS_TYPE was 1 (auto) before sim took over.
        existing.write_text(
            "GPS_TYPE,1\nGPS_TYPE2,0\nAHRS_EKF_TYPE,3\n"
            "EK3_SRC1_POSXY,3\nEK3_SRC1_VELXY,3\n"
            "EK3_SRC1_POSZ,1\nEK3_SRC1_YAW,1\n"
        )

        # Simulate autopilot currently in sim mode (crashed prior run).
        current_state = {name: 14 if name == "GPS_TYPE" else 99.0
                         for name in SIM_PARAMS}
        with patch(
            "skynet.gps_sim.fetch_all_params", return_value=current_state
        ), patch("skynet.gps_sim.write_params"):
            ctx = SimParamContext(conn, "test", sidecar_dir=tmp_path)
            ctx.sidecar = existing
            ctx.__enter__()
            try:
                # Originals should come from the sidecar, NOT the current state.
                assert ctx._originals["GPS_TYPE"] == 1
                assert ctx._originals["EK3_SRC1_YAW"] == 1
                # Fresh sidecar exists.
                assert ctx.sidecar.exists()
            finally:
                ctx.__exit__(None, None, None)
        # After exit, sidecar gone.
        assert not ctx.sidecar.exists()

    def test_happy_restore(self, tmp_path: Path):
        # Use mocked fetch/write_params for clarity
        conn = MagicMock()
        conn.target_system = 1
        conn.target_component = 1
        conn.mav = MagicMock()
        originals = {name: 77.0 for name in SIM_PARAMS}

        with patch(
            "skynet.gps_sim.fetch_all_params", return_value=originals
        ), patch("skynet.gps_sim.write_params") as mock_write:
            ctx = SimParamContext(conn, "/dev/ttyACM0", sidecar_dir=tmp_path)
            with ctx:
                # Sidecar exists on disk while context is active
                assert ctx.sidecar.exists()
                # First write_params was the sim values
                first_call = mock_write.call_args_list[0]
                written = first_call.args[1]
                assert written["GPS_TYPE"] == 14

            # On exit, originals were restored
            last_call = mock_write.call_args_list[-1]
            restored = last_call.args[1]
            assert restored == originals

        # Sidecar was deleted
        assert not ctx.sidecar.exists()

    def test_exception_still_restores(self, tmp_path: Path):
        conn = MagicMock()
        conn.mav = MagicMock()
        originals = {name: 7.0 for name in SIM_PARAMS}

        with patch(
            "skynet.gps_sim.fetch_all_params", return_value=originals
        ), patch("skynet.gps_sim.write_params") as mock_write:
            ctx = SimParamContext(conn, "/dev/ttyACM0", sidecar_dir=tmp_path)
            with pytest.raises(RuntimeError, match="boom"):
                with ctx:
                    raise RuntimeError("boom")
            # Restore was called during __exit__
            restored = mock_write.call_args_list[-1].args[1]
            assert restored == originals
        assert not ctx.sidecar.exists()

    def test_sidecar_is_valid_param_file(self, tmp_path: Path):
        from skynet.config import load_param_file

        conn = MagicMock()
        conn.mav = MagicMock()
        originals = {name: float(i) for i, name in enumerate(SIM_PARAMS)}

        with patch(
            "skynet.gps_sim.fetch_all_params", return_value=originals
        ), patch("skynet.gps_sim.write_params"):
            ctx = SimParamContext(conn, "/dev/ttyACM0", sidecar_dir=tmp_path)
            ctx.__enter__()
            try:
                loaded = load_param_file(ctx.sidecar, include_calibration=True)
                assert loaded == originals
            finally:
                ctx.__exit__(None, None, None)


# ==================== GpsInputEmitter ====================


class TestGpsInputEmitter:
    def test_emit_shape(self):
        conn = MagicMock()
        conn.mav = MagicMock()
        model = SkidSteerModel(
            start_lat=40.0,
            start_lon=-80.0,
            start_heading_deg=45.0,
            max_speed_mps=1.0,
            track_width_m=0.5,
        )
        emitter = GpsInputEmitter(conn, model, rate_hz=5)
        emitter.set_velocity(0.707, 0.707)
        emitter.emit()

        conn.mav.gps_input_send.assert_called_once()
        args = conn.mav.gps_input_send.call_args.args
        # ignore_flags=0, fix_type=6 (RTK_FIXED) — required for EKF3 to
        # trust GPS yaw.
        assert args[2] == 0  # ignore_flags
        assert args[5] == 6  # fix_type = MAV_GPS_FIX_TYPE_RTK_FIXED
        # lat/lon int32 scaled
        assert args[6] == int(round(40.0 * 1e7))
        assert args[7] == int(round(-80.0 * 1e7))
        # vn/ve from set_velocity
        assert args[11] == pytest.approx(0.707)
        assert args[12] == pytest.approx(0.707)
        # vd = 0
        assert args[13] == 0.0
        # sats_visible = 20 (RTK-quality)
        assert args[17] == 20
        # yaw in centidegrees
        assert args[18] == 4500  # 45.0 * 100

    def test_fix_type_is_rtk_fixed(self):
        """GPS_INPUT.fix_type must be 6 (RTK_FIXED). EKF3 requires RTK
        quality to accept GPS yaw; with a plain 3D fix (3) the nav
        controller refuses to engage even though position is accepted.
        """
        conn = MagicMock()
        conn.mav = MagicMock()
        model = SkidSteerModel(start_lat=0.0, start_lon=0.0)
        GpsInputEmitter(conn, model, rate_hz=5).emit()
        fix_type = conn.mav.gps_input_send.call_args.args[5]
        assert fix_type == mavutil.mavlink.GPS_FIX_TYPE_RTK_FIXED == 6

    def test_yaw_floor(self):
        conn = MagicMock()
        conn.mav = MagicMock()
        model = SkidSteerModel(
            start_lat=0.0,
            start_lon=0.0,
            start_heading_deg=0.0,
            max_speed_mps=1.0,
            track_width_m=0.5,
        )
        emitter = GpsInputEmitter(conn, model, rate_hz=5)
        emitter.emit()
        yaw_cdeg = conn.mav.gps_input_send.call_args.args[18]
        assert yaw_cdeg == 1  # floored, not 0

    def test_rate_clamp_high(self, caplog):
        conn = MagicMock()
        model = SkidSteerModel(start_lat=0.0, start_lon=0.0)
        with caplog.at_level("WARNING"):
            e = GpsInputEmitter(conn, model, rate_hz=50)
        assert e.rate_hz == 20

    def test_rate_clamp_low(self, caplog):
        conn = MagicMock()
        model = SkidSteerModel(start_lat=0.0, start_lon=0.0)
        with caplog.at_level("WARNING"):
            e = GpsInputEmitter(conn, model, rate_hz=0.1)
        assert e.rate_hz == 1

    def test_multiple_emits_monotonic_time(self):
        conn = MagicMock()
        conn.mav = MagicMock()
        model = SkidSteerModel(start_lat=0.0, start_lon=0.0)
        emitter = GpsInputEmitter(conn, model, rate_hz=5)
        emitter.emit()
        emitter.emit()
        emitter.emit()
        assert conn.mav.gps_input_send.call_count == 3
        t0 = conn.mav.gps_input_send.call_args_list[0].args[0]
        t1 = conn.mav.gps_input_send.call_args_list[1].args[0]
        t2 = conn.mav.gps_input_send.call_args_list[2].args[0]
        assert t0 <= t1 <= t2


# ==================== StopWatcher ====================


class TestStopWatcher:
    def test_disarm_after_sustained_arm(self):
        w = StopWatcher(last_mission_seq=5)
        armed = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        w.observe_heartbeat(armed)
        assert not w.should_stop
        # Simulate time passing beyond MIN_ARMED_SECONDS
        w._armed_at = time.monotonic() - 10.0
        w.observe_heartbeat(0)  # disarmed after 10s
        assert w.should_stop
        assert w.stop_reason == "DISARM"

    def test_transient_disarm_resets_latch(self):
        w = StopWatcher(last_mission_seq=5)
        armed = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        w.observe_heartbeat(armed)
        assert w.armed_latch is True
        # Disarm within MIN_ARMED_SECONDS — transient, should NOT stop
        w.observe_heartbeat(0)
        assert not w.should_stop
        assert w.armed_latch is False  # latch reset

    def test_re_arm_after_transient_works(self):
        w = StopWatcher(last_mission_seq=5)
        armed = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        # First arm/disarm cycle (transient)
        w.observe_heartbeat(armed)
        w.observe_heartbeat(0)
        assert not w.should_stop
        # Re-arm, hold for long enough, then disarm
        w.observe_heartbeat(armed)
        w._armed_at = time.monotonic() - 10.0
        w.observe_heartbeat(0)
        assert w.should_stop
        assert w.stop_reason == "DISARM"

    def test_disarm_before_arm_ignored(self):
        w = StopWatcher(last_mission_seq=5)
        w.observe_heartbeat(0)
        w.observe_heartbeat(0)
        assert not w.should_stop

    def test_mission_reached_last_seq(self):
        w = StopWatcher(last_mission_seq=5)
        w.observe_mission_reached(4)
        assert not w.should_stop
        w.observe_mission_reached(5)
        assert w.should_stop

    def test_duration_expiry(self):
        import time as _t

        w = StopWatcher(last_mission_seq=5, duration_seconds=0.001)
        w._start_monotonic = _t.monotonic() - 1.0
        w.check_duration()
        assert w.should_stop

    def test_duration_none_never_trips(self):
        w = StopWatcher(last_mission_seq=5, duration_seconds=None)
        w._start_monotonic = 0.0
        w.check_duration()
        assert not w.should_stop

    def test_trip_is_idempotent(self):
        w = StopWatcher(last_mission_seq=5)
        w.trip("first")
        w.trip("second")
        assert w.stop_reason == "first"

    def test_signal_handlers_installed_and_restored(self):
        prev = signal.getsignal(signal.SIGINT)
        with StopWatcher(last_mission_seq=1) as w:
            assert signal.getsignal(signal.SIGINT) is not prev
        assert signal.getsignal(signal.SIGINT) is prev


# ==================== validate_skid_steer ====================


class TestStreamRequests:
    def _conn(self) -> MagicMock:
        conn = MagicMock()
        conn.target_system = 1
        conn.target_component = 1
        conn.mav = MagicMock()
        return conn

    def test_request_servo_output_stream(self):
        conn = self._conn()
        request_servo_output_stream(conn, rate_hz=10.0)
        assert conn.mav.command_long_send.call_count == 1
        args = conn.mav.command_long_send.call_args.args
        # MAV_CMD_SET_MESSAGE_INTERVAL
        assert args[2] == mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL
        # param1 = message id
        assert args[4] == float(
            mavutil.mavlink.MAVLINK_MSG_ID_SERVO_OUTPUT_RAW
        )
        # param2 = interval in microseconds (100_000us = 10 Hz)
        assert args[5] == 100_000.0

    def test_request_diagnostic_streams_subscribes_all(self):
        """request_diagnostic_streams must subscribe to 5 streams at 1 Hz:
        MISSION_CURRENT, NAV_CONTROLLER_OUTPUT, VFR_HUD,
        GLOBAL_POSITION_INT, EKF_STATUS_REPORT.
        """
        conn = self._conn()
        request_diagnostic_streams(conn)
        assert conn.mav.command_long_send.call_count == 5

        requested_msg_ids = set()
        for call in conn.mav.command_long_send.call_args_list:
            args = call.args
            assert args[2] == mavutil.mavlink.MAV_CMD_SET_MESSAGE_INTERVAL
            msg_id = int(args[4])
            interval_us = args[5]
            assert interval_us == 1_000_000.0, (
                f"msg_id {msg_id} requested at {interval_us}µs, expected 1 Hz"
            )
            requested_msg_ids.add(msg_id)

        assert requested_msg_ids == {
            mavutil.mavlink.MAVLINK_MSG_ID_MISSION_CURRENT,
            mavutil.mavlink.MAVLINK_MSG_ID_NAV_CONTROLLER_OUTPUT,
            mavutil.mavlink.MAVLINK_MSG_ID_VFR_HUD,
            mavutil.mavlink.MAVLINK_MSG_ID_GLOBAL_POSITION_INT,
            mavutil.mavlink.MAVLINK_MSG_ID_EKF_STATUS_REPORT,
        }


class TestDeduplicateMission:
    def test_removes_duplicate_home_wp1(self):
        """The exact case from nav_plan output: home == WP1."""
        home = (40.30073620, -83.03812000)
        wp2 = (40.30100000, -83.03700000)
        wp3 = (40.30150000, -83.03600000)
        mission = [home, home, wp2, wp3]  # home row + WP1 duplicate
        result = deduplicate_mission(mission)
        assert len(result) == 3
        assert result[0] == home
        assert result[1] == wp2
        assert result[2] == wp3

    def test_keeps_non_duplicates(self):
        mission = [(40.0, -80.0), (40.01, -80.0), (40.02, -80.0)]
        result = deduplicate_mission(mission)
        assert result == mission

    def test_only_consecutive_duplicates(self):
        """Non-consecutive duplicates are kept (loops are valid missions)."""
        a = (40.0, -80.0)
        b = (40.001, -80.0)
        mission = [a, b, a]  # return-to-start pattern
        result = deduplicate_mission(mission)
        assert result == mission

    def test_tolerance_catches_near_duplicates(self):
        """Waypoints within 0.5 m by default count as duplicates."""
        a = (40.30073620, -83.03812000)
        # Shift by ~0.1 m north (well under 0.5 m tolerance).
        b = (a[0] + 0.1 / 111_320.0, a[1])
        mission = [a, b, (40.302, -83.037)]
        result = deduplicate_mission(mission)
        assert len(result) == 2
        assert result[0] == a
        # b was dropped as a near-duplicate.

    def test_tolerance_keeps_above_threshold(self):
        a = (40.30073620, -83.03812000)
        # Shift by ~2 m north (above 0.5 m tolerance).
        b = (a[0] + 2.0 / 111_320.0, a[1])
        mission = [a, b]
        result = deduplicate_mission(mission)
        assert len(result) == 2

    def test_single_item_returned_as_is(self):
        assert deduplicate_mission([(40.0, -80.0)]) == [(40.0, -80.0)]

    def test_empty_returned_as_is(self):
        assert deduplicate_mission([]) == []

    def test_all_duplicates_collapses_to_one(self):
        a = (40.0, -80.0)
        mission = [a, a, a, a]
        result = deduplicate_mission(mission)
        assert result == [a]


class TestSeverityLabel:
    def test_all_standard_severities(self):
        assert severity_label(0) == "EMERGENCY"
        assert severity_label(1) == "ALERT"
        assert severity_label(2) == "CRITICAL"
        assert severity_label(3) == "ERROR"
        assert severity_label(4) == "WARNING"
        assert severity_label(5) == "NOTICE"
        assert severity_label(6) == "INFO"
        assert severity_label(7) == "DEBUG"

    def test_unknown_severity(self):
        assert severity_label(99) == "SEV99"


class TestSetTargetGroundspeed:
    def _conn(self) -> MagicMock:
        conn = MagicMock()
        conn.target_system = 1
        conn.target_component = 1
        conn.mav = MagicMock()
        return conn

    def test_sends_do_change_speed_groundspeed(self):
        """set_target_groundspeed must send MAV_CMD_DO_CHANGE_SPEED with
        param1=1 (groundspeed) and param2=target speed in m/s."""
        conn = self._conn()
        set_target_groundspeed(conn, 0.8941)  # 2 mph in m/s
        conn.mav.command_long_send.assert_called_once()
        args = conn.mav.command_long_send.call_args.args
        assert args[2] == mavutil.mavlink.MAV_CMD_DO_CHANGE_SPEED
        assert args[4] == 1.0            # param1 = 1 (groundspeed)
        assert args[5] == pytest.approx(0.8941)  # param2 = speed
        assert args[6] == -1.0           # param3 = -1 (no throttle change)


class TestWarnOnZeroSpeedParams:
    def test_reports_zero_speed_params(self):
        params = {
            "CRUISE_SPEED": 0,
            "CRUISE_THROTTLE": 40,
            "WP_SPEED": 2.0,
        }
        warnings: list[str] = []
        zeros = warn_on_zero_speed_params(params, warnings.append)
        assert zeros == ["CRUISE_SPEED"]
        assert len(warnings) == 1
        assert "CRUISE_SPEED=0" in warnings[0]

    def test_reports_all_three_zero(self):
        params = {
            "CRUISE_SPEED": 0,
            "CRUISE_THROTTLE": 0,
            "WP_SPEED": 0,
        }
        warnings: list[str] = []
        zeros = warn_on_zero_speed_params(params, warnings.append)
        assert set(zeros) == {"CRUISE_SPEED", "CRUISE_THROTTLE", "WP_SPEED"}
        assert len(warnings) == 3

    def test_no_warnings_when_all_nonzero(self):
        params = {
            "CRUISE_SPEED": 2.0,
            "CRUISE_THROTTLE": 40,
            "WP_SPEED": 2.0,
        }
        warnings: list[str] = []
        zeros = warn_on_zero_speed_params(params, warnings.append)
        assert zeros == []
        assert warnings == []

    def test_missing_params_do_not_warn(self):
        """A param missing from the dict shouldn't be reported as zero —
        it's just not present on this autopilot."""
        params: dict[str, float] = {}
        warnings: list[str] = []
        zeros = warn_on_zero_speed_params(params, warnings.append)
        assert zeros == []
        assert warnings == []


class TestSimParamsFlags:
    def test_mis_restart_zero(self):
        """MIS_RESTART=0 so the autopilot does NOT reset mission pointer
        on arm. A fresh upload already resets the mission state, and
        restart-on-arm fights our MISSION_SET_CURRENT commands."""
        assert SIM_PARAMS["MIS_RESTART"] == 0

    def test_disarm_delay_still_zero(self):
        """Regression: DISARM_DELAY=0 must still be present (prior fix)."""
        assert SIM_PARAMS["DISARM_DELAY"] == 0

    def test_fs_ekf_action_zero(self):
        """Regression: FS_EKF_ACTION=0 (disabled in Rover)."""
        assert SIM_PARAMS["FS_EKF_ACTION"] == 0

    def test_auto_kickstart_zero(self):
        """AUTO_KICKSTART=0 disables the physical-push requirement. If
        non-zero, the bench rover never moves because it never receives
        the acceleration spike ArduRover expects before starting AUTO."""
        assert SIM_PARAMS["AUTO_KICKSTART"] == 0


class TestOffsetSpawnBehindWaypoint:
    def test_offset_magnitude_is_5m_by_default(self):
        """Spawn must be offset ~5 m from the target so wp_dist > 0."""
        # Target at (40.0, -80.0), next WP 10 m north.
        here_lat, here_lon = 40.0, -80.0
        next_lat = here_lat + 10.0 / 111_320.0
        next_lon = -80.0
        spawn_lat, spawn_lon = offset_spawn_behind_waypoint(
            here_lat, here_lon, next_lat, next_lon, distance_m=5.0
        )
        # Spawn must be roughly 5 m from here.
        dy_m = (spawn_lat - here_lat) * 111_320.0
        dx_m = (spawn_lon - here_lon) * 111_320.0 * math.cos(
            math.radians(here_lat)
        )
        dist_m = math.hypot(dx_m, dy_m)
        assert dist_m == pytest.approx(5.0, abs=0.01)

    def test_offset_is_behind_not_ahead(self):
        """Spawn must be opposite the direction of the next waypoint."""
        here_lat, here_lon = 40.0, -80.0
        # Next WP 10 m north.
        next_lat = here_lat + 10.0 / 111_320.0
        next_lon = -80.0
        spawn_lat, spawn_lon = offset_spawn_behind_waypoint(
            here_lat, here_lon, next_lat, next_lon, distance_m=5.0
        )
        # Spawn must be SOUTH of here (i.e., away from next).
        assert spawn_lat < here_lat
        assert spawn_lon == pytest.approx(here_lon, abs=1e-9)

    def test_offset_east_direction(self):
        """Validate east-bound trajectory: spawn lands west of here."""
        here_lat, here_lon = 40.0, -80.0
        # Next WP 10 m east.
        next_lat = 40.0
        next_lon = here_lon + 10.0 / (111_320.0 * math.cos(math.radians(40.0)))
        spawn_lat, spawn_lon = offset_spawn_behind_waypoint(
            here_lat, here_lon, next_lat, next_lon, distance_m=5.0
        )
        assert spawn_lat == pytest.approx(here_lat, abs=1e-9)
        assert spawn_lon < here_lon  # west of here

    def test_wp_dist_is_nonzero_to_here(self):
        """The key property: after offset, the distance from spawn to
        the target waypoint (`here`) is > 0 — the exact condition that
        unblocks ArduRover's waypoint-reached hysteresis."""
        here_lat, here_lon = 40.30073620, -83.03812000
        next_lat, next_lon = 40.30100000, -83.03700000
        spawn_lat, spawn_lon = offset_spawn_behind_waypoint(
            here_lat, here_lon, next_lat, next_lon, distance_m=5.0
        )
        dy_m = (here_lat - spawn_lat) * 111_320.0
        dx_m = (here_lon - spawn_lon) * 111_320.0 * math.cos(
            math.radians(here_lat)
        )
        wp_dist = math.hypot(dx_m, dy_m)
        assert wp_dist > 1.0  # well above WP_RADIUS=2 would be ideal, >1 is fine
        assert wp_dist == pytest.approx(5.0, abs=0.01)

    def test_degenerate_same_location_falls_back_south(self):
        """If here == next (e.g., duplicate waypoint), still produce a
        distinct spawn (not identical to here)."""
        here_lat, here_lon = 40.0, -80.0
        spawn_lat, spawn_lon = offset_spawn_behind_waypoint(
            here_lat, here_lon, here_lat, here_lon, distance_m=5.0
        )
        assert spawn_lat != here_lat or spawn_lon != here_lon
        # Falls back to offsetting due south.
        assert spawn_lat < here_lat
        assert spawn_lon == pytest.approx(here_lon, abs=1e-9)


class TestDetectDriveType:
    def test_skid_steer(self):
        params = {
            "FRAME_CLASS": 2,
            "SERVO1_FUNCTION": 73,
            "SERVO3_FUNCTION": 74,
        }
        assert detect_drive_type(params) == DRIVE_SKID_STEER

    def test_ackermann_frame1(self):
        params = {
            "FRAME_CLASS": 1,
            "SERVO1_FUNCTION": 26,
            "SERVO3_FUNCTION": 70,
        }
        assert detect_drive_type(params) == DRIVE_ACKERMANN

    def test_ackermann_frame2(self):
        params = {
            "FRAME_CLASS": 2,
            "SERVO1_FUNCTION": 26,
            "SERVO3_FUNCTION": 70,
        }
        assert detect_drive_type(params) == DRIVE_ACKERMANN

    def test_unrecognized_raises(self):
        params = {
            "FRAME_CLASS": 2,
            "SERVO1_FUNCTION": 70,
            "SERVO3_FUNCTION": 74,
        }
        with pytest.raises(FrameMismatchError):
            detect_drive_type(params)

    def test_missing_params_raises(self):
        with pytest.raises(FrameMismatchError):
            detect_drive_type({})

    def test_validate_skid_steer_legacy(self):
        validate_skid_steer({
            "FRAME_CLASS": 2,
            "SERVO1_FUNCTION": 73,
            "SERVO3_FUNCTION": 74,
        })  # no raise

    def test_hierarchy(self):
        assert issubclass(FrameMismatchError, MowerProvisionerError)
        assert issubclass(GpsSimError, MowerProvisionerError)


# ==================== resolve_sim_params ====================


class TestResolveSimParams:
    def test_canonical_names(self):
        ap = {"GPS_TYPE": 1, "GPS_TYPE2": 5, "AHRS_EKF_TYPE": 3,
              "EK3_SRC1_POSXY": 1, "EK3_SRC1_VELXY": 1,
              "EK3_SRC1_POSZ": 1, "EK3_SRC1_YAW": 1}
        resolved = resolve_sim_params(ap)
        assert "GPS_TYPE" in resolved
        assert resolved["GPS_TYPE"] == 14
        assert "GPS_TYPE2" in resolved
        assert resolved["GPS_TYPE2"] == 0

    def test_new_firmware_aliases(self):
        ap = {"GPS1_TYPE": 1, "GPS2_TYPE": 5, "AHRS_EKF_TYPE": 3,
              "EK3_SRC1_POSXY": 1, "EK3_SRC1_VELXY": 1,
              "EK3_SRC1_POSZ": 1, "EK3_SRC1_YAW": 1}
        resolved = resolve_sim_params(ap)
        assert "GPS1_TYPE" in resolved
        assert resolved["GPS1_TYPE"] == 14
        assert "GPS2_TYPE" in resolved
        assert resolved["GPS2_TYPE"] == 0
        assert "GPS_TYPE" not in resolved

    def test_missing_both_warns(self, caplog):
        ap = {"AHRS_EKF_TYPE": 3, "EK3_SRC1_POSXY": 1,
              "EK3_SRC1_VELXY": 1, "EK3_SRC1_POSZ": 1,
              "EK3_SRC1_YAW": 1}
        with caplog.at_level("WARNING"):
            resolved = resolve_sim_params(ap)
        assert "GPS_TYPE" not in resolved
        assert "GPS1_TYPE" not in resolved
        assert any("GPS_TYPE" in r.message for r in caplog.records)


# ==================== CLI ====================


class TestNavSimCli:
    def _patch_conn(self, monkeypatch, all_params: dict[str, float]):
        import skynet.cli as cli_mod

        fake_conn = MagicMock()
        fake_conn.target_system = 1
        fake_conn.target_component = 1
        fake_conn.mav = MagicMock()

        class _ConnCtx:
            def __enter__(self_):
                return fake_conn

            def __exit__(self_, *a):
                return False

        monkeypatch.setattr(
            cli_mod, "mavlink_connection", lambda *a, **k: _ConnCtx()
        )
        monkeypatch.setattr(
            "skynet.params.fetch_all_params", lambda conn, **kw: dict(all_params)
        )
        monkeypatch.setattr(
            "skynet.gps_sim.fetch_all_params", lambda conn, **kw: dict(all_params)
        )
        monkeypatch.setattr(
            "skynet.mission_download.download_mission",
            lambda conn, **kw: [(40.0, -80.0), (40.001, -80.0), (40.002, -80.0)],
        )
        return fake_conn

    def _ok_params(self):
        p = {
            "FRAME_CLASS": 2,
            "SERVO1_FUNCTION": 73,
            "SERVO3_FUNCTION": 74,
            "SERVO1_MIN": 1000,
            "SERVO1_TRIM": 1500,
            "SERVO1_MAX": 2000,
            "SERVO3_MIN": 1000,
            "SERVO3_TRIM": 1500,
            "SERVO3_MAX": 2000,
        }
        for name in SIM_PARAMS:
            p[name] = 0.0
        return p

    def test_dry_run_opens_no_writes(self, monkeypatch, tmp_path: Path):
        # Point sidecar dir at tmp_path so we don't touch ~/.config
        monkeypatch.setattr("skynet.gps_sim.SIDECAR_DIR", tmp_path)

        fake_conn = self._patch_conn(monkeypatch, self._ok_params())

        runner = CliRunner()
        result = runner.invoke(app, ["nav", "sim", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "DRY RUN" in result.output
        assert "GPS_TYPE" in result.output
        # No GPS_INPUT sent, no params written during dry run
        fake_conn.mav.gps_input_send.assert_not_called()
        fake_conn.mav.param_set_send.assert_not_called()

    def test_frame_mismatch(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr("skynet.gps_sim.SIDECAR_DIR", tmp_path)

        bad = self._ok_params()
        bad["FRAME_CLASS"] = 1
        self._patch_conn(monkeypatch, bad)

        runner = CliRunner()
        result = runner.invoke(app, ["nav", "sim", "--dry-run"])
        assert result.exit_code != 0

    def test_leftover_sidecar_is_cleared(self, monkeypatch, tmp_path: Path):
        """Leftover sidecar should no longer block startup — the CLI
        announces the recovery intent and proceeds."""
        monkeypatch.setattr("skynet.gps_sim.SIDECAR_DIR", tmp_path)
        self._patch_conn(monkeypatch, self._ok_params())

        leftover = sidecar_path("/dev/ttyACM0", sidecar_dir=tmp_path)
        leftover.parent.mkdir(parents=True, exist_ok=True)
        leftover.write_text("GPS_TYPE,1\n")

        runner = CliRunner()
        result = runner.invoke(app, ["nav", "sim", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Leftover sidecar" in result.output
        assert "cleared" in result.output or "used as the originals" in result.output

    def test_bad_start_seq(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr("skynet.gps_sim.SIDECAR_DIR", tmp_path)
        self._patch_conn(monkeypatch, self._ok_params())

        runner = CliRunner()
        result = runner.invoke(
            app, ["nav", "sim", "--dry-run", "--start-seq", "99"]
        )
        assert result.exit_code != 0
        assert "out of range" in result.output

    def test_ackermann_dry_run(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr("skynet.gps_sim.SIDECAR_DIR", tmp_path)
        ack_params = self._ok_params()
        ack_params["FRAME_CLASS"] = 2
        ack_params["SERVO1_FUNCTION"] = 26
        ack_params["SERVO3_FUNCTION"] = 70
        self._patch_conn(monkeypatch, ack_params)

        runner = CliRunner()
        result = runner.invoke(app, ["nav", "sim", "--dry-run"])
        assert result.exit_code == 0, result.output
        assert "Ackermann" in result.output
        assert "DRY RUN" in result.output
