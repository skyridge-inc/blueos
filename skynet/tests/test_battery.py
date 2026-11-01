"""Tests for the YAML batteries section -> ArduPilot BATT* params."""

from __future__ import annotations

import pytest

from skynet.battery import battery_params, is_port_dependent, sync_scaling_from_device
from skynet.exceptions import ParamFileError

SKY1 = {
    "port": "power1", "sensor": "holybro_pm02_v3", "chemistry": "lifepo4",
    "batteries_in_series": 2, "low_action": "hold", "critical_action": "hold",
}


class TestBatteryParams:
    def test_sky1_power1_lifepo4(self):
        assert battery_params([SKY1]) == {
            "BATT_AMP_PERVLT": 36.364,
            "BATT_CAPACITY": 0.0,
            "BATT_CRT_VOLT": 24.0,
            "BATT_CURR_PIN": 15.0,
            "BATT_FS_CRT_ACT": 2.0,
            "BATT_FS_LOW_ACT": 2.0,
            "BATT_LOW_VOLT": 25.6,
            "BATT_MONITOR": 4.0,
            "BATT_VOLT_MULT": 18.182,
            "BATT_VOLT_PIN": 14.0,
        }

    def test_power2_lead_acid_defaults_and_overrides(self):
        p = battery_params([{
            "port": "POWER2", "sensor": "holybro_pm02_v3", "chemistry": "lead_acid",
            "volt_mult": 18.05, "capacity_mah": 20000,
        }])
        assert p["BATT2_MONITOR"] == 4.0
        assert (p["BATT2_VOLT_PIN"], p["BATT2_CURR_PIN"]) == (13.0, 4.0)
        assert p["BATT2_VOLT_MULT"] == 18.05
        assert (p["BATT2_LOW_VOLT"], p["BATT2_CRT_VOLT"]) == (11.8, 11.5)
        assert (p["BATT2_FS_LOW_ACT"], p["BATT2_FS_CRT_ACT"]) == (0.0, 0.0)
        assert p["BATT2_CAPACITY"] == 20000.0

    def test_none_is_empty(self):
        assert battery_params(None) == {}

    @pytest.mark.parametrize("entry, message", [
        ({**SKY1, "port": "power3"}, "port"),
        ({**SKY1, "sensor": "mystery"}, "sensor"),
        ({**SKY1, "chemistry": "nimh"}, "chemistry"),
        ({**SKY1, "low_action": "explode"}, "low_action"),
        ({**SKY1, "batteries_in_series": 0}, "batteries_in_series"),
        ({**SKY1, "capacity_mah": -1}, "capacity_mah"),
    ])
    def test_rejects_bad_entries(self, entry, message):
        with pytest.raises(ParamFileError, match=message):
            battery_params([entry])

    def test_rejects_duplicate_port(self):
        with pytest.raises(ParamFileError, match="twice"):
            battery_params([SKY1, SKY1])


def test_is_port_dependent():
    assert is_port_dependent("BATT_VOLT_MULT")
    assert is_port_dependent("BATT2_CURR_PIN")
    assert not is_port_dependent("BATT_MONITOR")
    assert not is_port_dependent("BATT_LOW_VOLT")


class TestSyncScaling:
    def test_copies_calibrated_values(self):
        batteries = [dict(SKY1)]
        changed = sync_scaling_from_device(
            batteries, {"BATT_VOLT_MULT": 18.04, "BATT_AMP_PERVLT": 36.364},
        )
        assert changed == 1
        assert batteries[0]["volt_mult"] == 18.04
        assert "amp_per_volt" not in batteries[0]   # still the sensor default

    def test_monitor_not_enabled_yet(self):
        batteries = [dict(SKY1)]
        assert sync_scaling_from_device(batteries, {"BATT_MONITOR": 0.0}) == 0
        assert batteries == [SKY1]
