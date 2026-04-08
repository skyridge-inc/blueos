"""Tests for config module — param file I/O and calibration exclusion."""

from pathlib import Path

import pytest

from mower_provisioner.config import (
    CALIBRATION_PARAMS,
    load_param_file,
    save_param_file,
)
from mower_provisioner.exceptions import ParamFileError


class TestLoadParamFile:
    def test_comma_separated(self, tmp_param_file):
        params = load_param_file(tmp_param_file)
        assert params["CRUISE_SPEED"] == 2.5
        assert params["CRUISE_THROTTLE"] == 50.0
        assert params["WP_RADIUS"] == 3.0
        assert params["NAVL1_PERIOD"] == 8.0

    def test_space_separated(self, tmp_path):
        path = tmp_path / "space.param"
        path.write_text("CRUISE_SPEED 2.5\nWP_RADIUS 3\n")
        params = load_param_file(path)
        assert params["CRUISE_SPEED"] == 2.5
        assert params["WP_RADIUS"] == 3.0

    def test_comments_and_blanks_skipped(self, tmp_path):
        path = tmp_path / "comments.param"
        path.write_text("# comment\n\nCRUISE_SPEED,2.5\n# another\n")
        params = load_param_file(path)
        assert len(params) == 1
        assert params["CRUISE_SPEED"] == 2.5

    def test_calibration_excluded_by_default(self, tmp_param_file_with_calibration):
        params = load_param_file(tmp_param_file_with_calibration)
        assert "CRUISE_SPEED" in params
        assert "WP_RADIUS" in params
        assert "INS_ACCOFFS_X" not in params
        assert "SYSID_THISMAV" not in params

    def test_calibration_included(self, tmp_param_file_with_calibration):
        params = load_param_file(
            tmp_param_file_with_calibration, include_calibration=True
        )
        assert "INS_ACCOFFS_X" in params
        assert "SYSID_THISMAV" in params
        assert params["INS_ACCOFFS_X"] == pytest.approx(0.123)

    def test_invalid_format_raises(self, tmp_path):
        path = tmp_path / "bad.param"
        path.write_text("JUST_A_NAME\n")
        with pytest.raises(ParamFileError, match="Invalid format"):
            load_param_file(path)

    def test_invalid_value_raises(self, tmp_path):
        path = tmp_path / "bad_val.param"
        path.write_text("PARAM,notanumber\n")
        with pytest.raises(ParamFileError, match="Invalid value"):
            load_param_file(path)

    def test_missing_file_raises(self, tmp_path):
        path = tmp_path / "missing.param"
        with pytest.raises(ParamFileError, match="Cannot read"):
            load_param_file(path)


class TestSaveParamFile:
    def test_round_trip(self, tmp_path):
        path = tmp_path / "out.param"
        params = {"CRUISE_SPEED": 2.5, "WP_RADIUS": 3.0, "NAVL1_PERIOD": 8.0}
        save_param_file(path, params)
        loaded = load_param_file(path)
        assert loaded == params

    def test_integer_formatting(self, tmp_path):
        path = tmp_path / "int.param"
        save_param_file(path, {"WP_RADIUS": 3.0, "SPEED": 2.5})
        text = path.read_text()
        assert "SPEED,2.5" in text
        assert "WP_RADIUS,3" in text
        # Should NOT have 3.0
        assert "WP_RADIUS,3.0" not in text

    def test_sorted_output(self, tmp_path):
        path = tmp_path / "sorted.param"
        save_param_file(path, {"ZZZ": 1.0, "AAA": 2.0, "MMM": 3.0})
        lines = [l for l in path.read_text().splitlines() if l]
        assert lines[0].startswith("AAA")
        assert lines[1].startswith("MMM")
        assert lines[2].startswith("ZZZ")

    def test_calibration_exclusion(self, tmp_path):
        path = tmp_path / "no_cal.param"
        params = {"CRUISE_SPEED": 2.5, "INS_ACCOFFS_X": 0.1, "SYSID_THISMAV": 1.0}
        save_param_file(path, params, include_calibration=False)
        loaded = load_param_file(path, include_calibration=True)
        assert "CRUISE_SPEED" in loaded
        assert "INS_ACCOFFS_X" not in loaded

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "out.param"
        save_param_file(path, {"A": 1.0})
        assert path.exists()


class TestCalibrationParams:
    def test_is_frozenset(self):
        assert isinstance(CALIBRATION_PARAMS, frozenset)

    def test_contains_expected_params(self):
        assert "INS_ACCOFFS_X" in CALIBRATION_PARAMS
        assert "COMPASS_OFS_X" in CALIBRATION_PARAMS
        assert "SYSID_THISMAV" in CALIBRATION_PARAMS
        assert "RC1_MIN" in CALIBRATION_PARAMS
        assert "BATT_VOLT_MULT" in CALIBRATION_PARAMS

    def test_does_not_contain_regular_params(self):
        assert "CRUISE_SPEED" not in CALIBRATION_PARAMS
        assert "WP_RADIUS" not in CALIBRATION_PARAMS
