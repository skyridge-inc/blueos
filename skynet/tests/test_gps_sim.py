"""Tests for the GPS/heading simulator components and nav sim CLI."""

from __future__ import annotations

import math
import signal
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
    MPH_TO_MPS,
    SIM_PARAMS,
    GpsInputEmitter,
    ServoNormalizer,
    SimParamContext,
    SkidSteerModel,
    StopWatcher,
    device_slug,
    sidecar_path,
    validate_skid_steer,
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

    def test_leftover_sidecar_aborts(self, tmp_path: Path):
        conn = MagicMock()
        existing = tmp_path / "sim_restore_foo.param"
        existing.write_text("GPS_TYPE,1\n")
        ctx = SimParamContext(conn, "foo", sidecar_dir=tmp_path)
        ctx.sidecar = existing
        with pytest.raises(GpsSimError, match="Leftover sidecar"):
            ctx.__enter__()
        # No param fetch was attempted
        conn.mav.param_request_list_send.assert_not_called()

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
        # time_usec monotonic, ignore_flags=0, fix_type=3
        assert args[2] == 0  # ignore_flags
        assert args[5] == 3  # fix_type
        # lat/lon int32 scaled
        assert args[6] == int(round(40.0 * 1e7))
        assert args[7] == int(round(-80.0 * 1e7))
        # vn/ve from set_velocity
        assert args[11] == pytest.approx(0.707)
        assert args[12] == pytest.approx(0.707)
        # vd = 0
        assert args[13] == 0.0
        # sats_visible
        assert args[17] == 14
        # yaw in centidegrees
        assert args[18] == 4500  # 45.0 * 100

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
    def test_disarm_after_arm(self):
        w = StopWatcher(last_mission_seq=5)
        armed = mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED
        w.observe_heartbeat(armed)
        assert not w.should_stop
        w.observe_heartbeat(0)  # disarmed
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


class TestValidateSkidSteer:
    def test_ok(self):
        params = {
            "FRAME_CLASS": 2,
            "SERVO1_FUNCTION": 73,
            "SERVO3_FUNCTION": 74,
        }
        validate_skid_steer(params)  # no raise

    def test_wrong_frame_class(self):
        params = {
            "FRAME_CLASS": 1,
            "SERVO1_FUNCTION": 73,
            "SERVO3_FUNCTION": 74,
        }
        with pytest.raises(FrameMismatchError):
            validate_skid_steer(params)

    def test_wrong_servo_function(self):
        params = {
            "FRAME_CLASS": 2,
            "SERVO1_FUNCTION": 70,
            "SERVO3_FUNCTION": 74,
        }
        with pytest.raises(FrameMismatchError):
            validate_skid_steer(params)

    def test_missing_params(self):
        with pytest.raises(FrameMismatchError):
            validate_skid_steer({})

    def test_hierarchy(self):
        assert issubclass(FrameMismatchError, MowerProvisionerError)
        assert issubclass(GpsSimError, MowerProvisionerError)


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

    def test_leftover_sidecar_refuses(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr("skynet.gps_sim.SIDECAR_DIR", tmp_path)

        # Pre-create the sidecar file for the default device
        leftover = sidecar_path("/dev/ttyACM0", sidecar_dir=tmp_path)
        leftover.parent.mkdir(parents=True, exist_ok=True)
        leftover.write_text("GPS_TYPE,14\n")

        runner = CliRunner()
        result = runner.invoke(app, ["nav", "sim", "--dry-run"])
        assert result.exit_code != 0
        assert "Leftover sidecar" in result.output or "sidecar" in result.output
        assert "skynet misc write" in result.output

    def test_bad_start_seq(self, monkeypatch, tmp_path: Path):
        monkeypatch.setattr("skynet.gps_sim.SIDECAR_DIR", tmp_path)
        self._patch_conn(monkeypatch, self._ok_params())

        runner = CliRunner()
        result = runner.invoke(
            app, ["nav", "sim", "--dry-run", "--start-seq", "99"]
        )
        assert result.exit_code != 0
        assert "out of range" in result.output
