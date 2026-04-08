"""Tests for QGC WPL 110 waypoint file I/O."""

import pytest

from mower_provisioner.mission_planning import read_waypoints, write_waypoints


class TestWaypoints:
    def test_round_trip(self, tmp_path):
        wps = [(40.0, -80.0), (40.001, -80.0), (40.001, -79.999)]
        path = str(tmp_path / "mission.waypoints")
        write_waypoints(path, wps)
        result = read_waypoints(path)
        assert len(result) == 3
        for (lat1, lon1), (lat2, lon2) in zip(wps, result):
            assert abs(lat1 - lat2) < 1e-7
            assert abs(lon1 - lon2) < 1e-7

    def test_format_compliance(self, tmp_path):
        wps = [(40.0, -80.0), (40.001, -80.0)]
        path = str(tmp_path / "mission.waypoints")
        write_waypoints(path, wps)
        with open(path) as f:
            lines = f.readlines()
        assert lines[0].strip() == "QGC WPL 110"
        # Home line: index 0, current_wp=1, frame 0, command 16
        parts = lines[1].strip().split("\t")
        assert parts[0] == "0"
        assert parts[1] == "1"
        assert parts[2] == "0"
        assert parts[3] == "16"
        assert len(parts) == 12
        # First mission waypoint: index 1, frame 3, command 16
        parts = lines[2].strip().split("\t")
        assert parts[0] == "1"
        assert parts[2] == "3"
        assert parts[3] == "16"

    def test_custom_home(self, tmp_path):
        wps = [(40.0, -80.0)]
        home = (39.999, -80.001)
        path = str(tmp_path / "mission.waypoints")
        write_waypoints(path, wps, home=home)
        with open(path) as f:
            lines = f.readlines()
        home_parts = lines[1].strip().split("\t")
        assert float(home_parts[8]) == pytest.approx(39.999)

    def test_empty_waypoints(self, tmp_path):
        path = str(tmp_path / "empty.waypoints")
        with pytest.raises(ValueError, match="No waypoints"):
            write_waypoints(path, [])

    def test_invalid_header(self, tmp_path):
        path = str(tmp_path / "bad.waypoints")
        with open(path, "w") as f:
            f.write("NOT A VALID HEADER\n")
        with pytest.raises(ValueError, match="Expected"):
            read_waypoints(path)
