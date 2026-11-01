"""Tests for extract module — URL parsing, config assembly, YAML I/O."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from skynet.exceptions import ParamFileError
from skynet.extract import (
    MEDIAMTX_CONFIG_CANDIDATES,
    _BAG_EXCLUDE_KEYS,
    extract_config,
    extract_hostname_from_url,
    fetch_mediamtx_config,
    fetch_video_streams,
    load_yaml,
    plan_cockpit_stream_renames,
    output_filename,
    push_mediamtx_config,
    save_yaml,
    video_stream_post_body,
)


class TestExtractHostnameFromUrl:
    def test_http_with_domain(self):
        assert extract_hostname_from_url("http://blueos.local") == "blueos.local"

    def test_http_with_ip(self):
        assert extract_hostname_from_url("http://192.168.2.2") == "192.168.2.2"

    def test_http_with_port(self):
        assert extract_hostname_from_url("http://192.168.2.2:80") == "192.168.2.2"

    def test_https(self):
        assert extract_hostname_from_url("https://blueos.local") == "blueos.local"

    def test_with_path(self):
        assert extract_hostname_from_url("http://blueos.local/foo") == "blueos.local"


class TestOutputFilename:
    def test_domain(self):
        assert output_filename("http://blueos.local") == Path("blueos.local.yaml")

    def test_ip(self):
        assert output_filename("http://192.168.2.2") == Path("192.168.2.2.yaml")


class TestExtractConfig:
    def _make_client(self, **overrides):
        """Create a mock BlueOSClient with configurable return values."""
        client = MagicMock()
        defaults = {
            "get_hostname": "blueos",
            "get_vehicle_name": "Mower-01",
            "get_extensions": [
                {"identifier": "ext.example", "tag": "1.0.0", "enabled": True}
            ],
            "get_bag": {"major_tom": {"token": "abc"}, "settings": {"is_dark_theme": True}},
            "get_ethernet": [
                {"name": "eth0", "addresses": [{"ip": "192.168.1.100"}],
                 "routes": [{"destination": "0.0.0.0/0"}], "info": {"connected": True}},
            ],
            "get_wifi_saved": [],
            "get_hotspot": {"enabled": False},
        }
        defaults.update(overrides)
        for method, value in defaults.items():
            getattr(client, method).return_value = value
        return client

    def test_all_sections_populated(self):
        client = self._make_client()
        config = extract_config(client)

        assert config["hostname"] == "blueos"
        assert config["vehicle_name"] == "Mower-01"
        assert len(config["extensions"]) == 1
        assert config["extensions"][0]["identifier"] == "ext.example"
        # bag should have major_tom but not settings (ephemeral)
        assert "major_tom" in config["bag"]
        assert "settings" not in config["bag"]
        # ethernet should have addresses but no routes
        assert config["network"]["ethernet"][0]["name"] == "eth0"
        assert "addresses" in config["network"]["ethernet"][0]
        assert "routes" not in config["network"]["ethernet"][0]
        assert "info" not in config["network"]["ethernet"][0]

    def test_excludes_runtime_state(self):
        """Config should not contain runtime-state fields."""
        client = self._make_client()
        config = extract_config(client)

        for key in ("blueos_version", "board", "firmware", "serials", "services", "_extracted_at"):
            assert key not in config

    def test_partial_failure(self):
        client = self._make_client(
            get_wifi_saved=None,
        )
        config = extract_config(client)

        assert config["hostname"] == "blueos"
        assert config["extensions"] is not None
        assert config["network"]["wifi_saved"] is None

    def test_all_fail(self):
        client = self._make_client(
            **{m: None for m in [
                "get_hostname", "get_vehicle_name",
                "get_extensions", "get_bag", "get_ethernet",
                "get_wifi_saved", "get_hotspot",
            ]}
        )
        config = extract_config(client)
        assert config["hostname"] is None
        assert config["extensions"] is None

    def test_bag_filtering(self):
        client = self._make_client(
            get_bag={
                "settings": {"is_dark_theme": True},
                "wizard": {"version": 4},
                "cockpit": {"cockpit-vehicle-id": "uuid"},
                "major_tom": {"token": "abc"},
                "vehicle.image_path": {"url": None},
            }
        )
        config = extract_config(client)
        bag = config["bag"]
        # Excluded keys
        for k in _BAG_EXCLUDE_KEYS:
            assert k not in bag
        # Kept keys
        assert "major_tom" in bag
        assert "vehicle.image_path" in bag


class TestSaveYaml:
    def test_writes_valid_yaml(self, tmp_path):
        path = tmp_path / "out.yaml"
        config = {"hostname": "blueos", "extensions": [{"id": "test"}]}
        save_yaml(config, path)

        loaded = yaml.safe_load(path.read_text())
        assert loaded["hostname"] == "blueos"
        assert loaded["extensions"][0]["id"] == "test"

    def test_preserves_key_order(self, tmp_path):
        path = tmp_path / "order.yaml"
        config = {"zzz": 1, "aaa": 2, "mmm": 3}
        save_yaml(config, path)

        keys = list(yaml.safe_load(path.read_text()).keys())
        assert keys == ["zzz", "aaa", "mmm"]

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "out.yaml"
        save_yaml({"a": 1}, path)
        assert path.exists()

    def test_round_trip_with_none_values(self, tmp_path):
        path = tmp_path / "nulls.yaml"
        config = {"hostname": "blueos", "board": None, "extensions": None}
        save_yaml(config, path)

        loaded = yaml.safe_load(path.read_text())
        assert loaded["board"] is None
        assert loaded["extensions"] is None


class TestLoadYaml:
    def test_valid_yaml(self, tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("hostname: blueos\nautopilot_params:\n  CRUISE_SPEED: 2.0\n")
        data = load_yaml(path)
        assert data["hostname"] == "blueos"
        assert data["autopilot_params"]["CRUISE_SPEED"] == 2.0

    def test_missing_file(self, tmp_path):
        path = tmp_path / "nope.yaml"
        with pytest.raises(ParamFileError, match="Cannot read"):
            load_yaml(path)

    def test_invalid_yaml(self, tmp_path):
        path = tmp_path / "bad.yaml"
        path.write_text(":\n  - :\n  invalid: [unterminated")
        with pytest.raises(ParamFileError, match="Invalid YAML"):
            load_yaml(path)

    def test_non_dict_yaml(self, tmp_path):
        path = tmp_path / "list.yaml"
        path.write_text("- item1\n- item2\n")
        with pytest.raises(ParamFileError, match="Expected a YAML mapping"):
            load_yaml(path)

    def test_round_trip_with_save_yaml(self, tmp_path):
        path = tmp_path / "rt.yaml"
        config = {"hostname": "blueos", "autopilot_params": {"WP_RADIUS": 3.0}}
        save_yaml(config, path)
        loaded = load_yaml(path)
        assert loaded == config


class TestFetchMediamtxConfig:
    def test_found_at_first_candidate(self):
        client = MagicMock()
        yaml_text = "logLevel: info\nrtspAddress: :8555\n"
        client.get_file.side_effect = lambda p: yaml_text if p == MEDIAMTX_CONFIG_CANDIDATES[0] else None

        result = fetch_mediamtx_config(client)
        assert result is not None
        assert result["config_path"] == MEDIAMTX_CONFIG_CANDIDATES[0]
        assert result["config"]["logLevel"] == "info"

    def test_explicit_path_overrides_candidates(self):
        client = MagicMock()
        client.get_file.return_value = "logLevel: debug\n"

        result = fetch_mediamtx_config(client, config_path="/custom/path.yml")
        assert result is not None
        assert result["config_path"] == "/custom/path.yml"
        # Should only try the explicit path, not candidates
        client.get_file.assert_called_once_with("/custom/path.yml")

    def test_not_found(self):
        client = MagicMock()
        client.get_file.return_value = None
        assert fetch_mediamtx_config(client) is None

    def test_explicit_path(self):
        client = MagicMock()
        client.get_file.return_value = "rtspAddress: :9999\n"
        result = fetch_mediamtx_config(client, config_path="/custom/mediamtx.yml")
        assert result is not None
        assert result["config_path"] == "/custom/mediamtx.yml"
        client.get_file.assert_called_once_with("/custom/mediamtx.yml")

    def test_invalid_yaml_skipped(self):
        client = MagicMock()
        # Use explicit paths: first is invalid YAML, second is valid
        def side_effect(path):
            if path == "/bad/mediamtx.yml":
                return ":\n  bad: [unterminated"
            if path == "/good/mediamtx.yml":
                return "logLevel: info\n"
            return None
        client.get_file.side_effect = side_effect

        # Neither candidate path will match, so test with explicit paths
        result = fetch_mediamtx_config(client, config_path="/bad/mediamtx.yml")
        assert result is None  # invalid YAML at explicit path returns None

        # Now test that valid path works
        result = fetch_mediamtx_config(client, config_path="/good/mediamtx.yml")
        assert result is not None
        assert result["config"]["logLevel"] == "info"

    def test_non_dict_yaml_skipped(self):
        client = MagicMock()
        # First path returns a list (not a dict), rest return None
        def side_effect(path):
            if path == MEDIAMTX_CONFIG_CANDIDATES[0]:
                return "- item1\n- item2\n"
            return None
        client.get_file.side_effect = side_effect

        assert fetch_mediamtx_config(client) is None


class TestPushMediamtxConfig:
    def test_push_success(self):
        client = MagicMock()
        client.put_file.return_value = True
        mediamtx = {
            "config_path": "/etc/mediamtx/mediamtx.yml",
            "config": {"logLevel": "info", "rtspAddress": ":8555"},
        }
        assert push_mediamtx_config(client, mediamtx) is True
        client.put_file.assert_called_once()
        call_path, call_content = client.put_file.call_args[0]
        assert call_path == "/etc/mediamtx/mediamtx.yml"
        assert "logLevel: info" in call_content

    def test_push_failure(self):
        client = MagicMock()
        client.put_file.return_value = False
        mediamtx = {
            "config_path": "/etc/mediamtx/mediamtx.yml",
            "config": {"logLevel": "info"},
        }
        assert push_mediamtx_config(client, mediamtx) is False

    def test_push_missing_path(self):
        client = MagicMock()
        assert push_mediamtx_config(client, {"config": {"a": 1}}) is False
        client.put_file.assert_not_called()

    def test_push_missing_config(self):
        client = MagicMock()
        assert push_mediamtx_config(client, {"config_path": "/foo"}) is False
        client.put_file.assert_not_called()


def _mcm_status(name, video_source, endpoints, configuration=None):
    return {
        "id": "00000000-0000-0000-0000-000000000000",
        "video_and_stream": {
            "name": name,
            "stream_information": {
                "endpoints": endpoints,
                "configuration": configuration or {"type": "video", "encode": "H265"},
                "extended_configuration": None,
            },
            "video_source": video_source,
        },
    }


class TestFetchVideoStreams:
    def test_redirect_stream(self):
        client = MagicMock()
        client.get_video_streams.return_value = [_mcm_status(
            "front",
            {"Redirect": {"name": "Redirect source", "source": {"Redirect": "Redirect"}}},
            ["rtsp://127.0.0.1:8555/front"],
        )]
        assert fetch_video_streams(client) == [
            {"name": "front", "source": "Redirect", "endpoints": ["rtsp://127.0.0.1:8555/front"]}
        ]

    def test_local_stream_keeps_configuration(self):
        config = {"type": "video", "encode": "H264", "height": 720, "width": 1280}
        client = MagicMock()
        client.get_video_streams.return_value = [_mcm_status(
            "usb",
            {"Local": {"name": "UVC", "device_path": "/dev/video0"}},
            ["udp://192.168.2.1:5600"],
            config,
        )]
        [entry] = fetch_video_streams(client)
        assert entry["source"] == "/dev/video0"
        assert entry["configuration"] == config

    def test_unreachable_returns_none(self):
        client = MagicMock()
        client.get_video_streams.return_value = None
        assert fetch_video_streams(client) is None


class TestVideoStreamPostBody:
    def test_redirect_gets_redirect_configuration(self):
        body = video_stream_post_body(
            {"name": "front", "source": "Redirect", "endpoints": ["rtsp://127.0.0.1:8555/front"]}
        )
        assert body == {
            "name": "front",
            "source": "Redirect",
            "stream_information": {
                "endpoints": ["rtsp://127.0.0.1:8555/front"],
                "configuration": {"type": "redirect"},
            },
        }

    def test_explicit_configuration_wins(self):
        config = {"type": "video", "encode": "H264"}
        body = video_stream_post_body(
            {"name": "usb", "source": "/dev/video0", "endpoints": [], "configuration": config}
        )
        assert body["stream_information"]["configuration"] == config


class TestFetchDhcpReservations:
    def test_missing_file_is_empty(self):
        from skynet.extract import fetch_dhcp_reservations

        client = MagicMock()
        client.run_host_command.return_value = {"stdout": "", "stderr": "nope", "return_code": 1}
        assert fetch_dhcp_reservations(client) == []

    def test_unreachable_is_none(self):
        from skynet.extract import fetch_dhcp_reservations

        client = MagicMock()
        client.run_host_command.return_value = None
        assert fetch_dhcp_reservations(client) is None


class TestAutopilotBase:
    def test_default_base_path_is_sibling(self, tmp_path):
        from skynet.extract import default_base_path

        assert default_base_path(tmp_path / "sky1.yaml") == tmp_path / "autopilot_base.yaml"

    def test_load_base(self, tmp_path):
        from skynet.extract import load_autopilot_base

        path = tmp_path / "autopilot_base.yaml"
        path.write_text("autopilot_params:\n  CRUISE_SPEED: 2.0\n")
        assert load_autopilot_base(path) == {"CRUISE_SPEED": 2.0}

    def test_load_base_null_section(self, tmp_path):
        from skynet.extract import load_autopilot_base

        path = tmp_path / "autopilot_base.yaml"
        path.write_text("autopilot_params:\n")
        assert load_autopilot_base(path) == {}

    def test_load_base_bad_shape_raises(self, tmp_path):
        from skynet.extract import load_autopilot_base

        path = tmp_path / "autopilot_base.yaml"
        path.write_text("autopilot_params:\n  - CRUISE_SPEED\n")
        with pytest.raises(ParamFileError):
            load_autopilot_base(path)

    def test_merge_rover_overrides_and_adds(self):
        from skynet.extract import merge_autopilot_params

        merged = merge_autopilot_params(
            {"CRUISE_SPEED": 2.0, "WP_RADIUS": 3.0},
            {"WP_RADIUS": 1.5, "GPS1_TYPE": 26.0},
        )
        assert merged == {"CRUISE_SPEED": 2.0, "GPS1_TYPE": 26.0, "WP_RADIUS": 1.5}
        assert list(merged) == sorted(merged)

    def test_merge_null_rover_section(self):
        from skynet.extract import merge_autopilot_params

        assert merge_autopilot_params({"CRUISE_SPEED": 2.0}, None) == {"CRUISE_SPEED": 2.0}

    def test_diff_from_base(self):
        from skynet.extract import params_diff_from_base

        base = {"CRUISE_SPEED": 2.0, "WP_RADIUS": 3.0, "TURN_RADIUS": 0.9}
        params = {
            "CRUISE_SPEED": 2.0,               # same
            "TURN_RADIUS": 0.8999999761581421,  # float32 round-trip, within epsilon
            "WP_RADIUS": 1.5,                  # changed
            "GPS1_TYPE": 26.0,                 # not in base
        }
        assert params_diff_from_base(params, base) == {"GPS1_TYPE": 26.0, "WP_RADIUS": 1.5}


def _video_widget(stream: str) -> dict:
    return {"component": "VideoPlayer", "options": {"internalStreamName": stream}}


class TestPlanCockpitStreamRenames:
    KEY = "cockpit/settings/sky1/cockpit-streams-correspondency"

    def _device_bag(self, correspondency, **settings):
        return {"cockpit": {"settings": {"sky1": {
            "cockpit-streams-correspondency": correspondency, **settings,
        }}}}

    def test_repoints_widgets_in_every_setting(self):
        profiles = [{"views": [
            {"widgets": [_video_widget("Stream 1"), {"options": {}}]},
            {"miniWidgetContainers": [{"widgets": [_video_widget("Stream 1")]}]},
        ]}]
        minis = {"containers": [_video_widget("Stream 1")]}
        device = self._device_bag(
            [{"name": "Stream 1", "externalId": "front"}],
            **{"cockpit-saved-profiles-v8": profiles, "cockpit-mini-widgets-profile-v4": minis},
        )
        bag = {self.KEY: [{"name": "front", "externalId": "front"}]}

        plans = plan_cockpit_stream_renames(bag, device)

        assert len(plans) == 1
        plan = plans[0]
        assert plan.user == "sky1"
        assert plan.renames == {"Stream 1": "front"}
        assert plan.widget_count == 3
        assert set(plan.updates) == {
            "cockpit/settings/sky1/cockpit-saved-profiles-v8",
            "cockpit/settings/sky1/cockpit-mini-widgets-profile-v4",
        }
        new_profiles = plan.updates["cockpit/settings/sky1/cockpit-saved-profiles-v8"]
        assert new_profiles[0]["views"][0]["widgets"][0]["options"]["internalStreamName"] == "front"
        # the device copy is left untouched
        assert profiles[0]["views"][0]["widgets"][0]["options"]["internalStreamName"] == "Stream 1"

    def test_only_renamed_streams_are_repointed(self):
        profiles = [{"views": [{"widgets": [_video_widget("Stream 1"), _video_widget("Rear")]}]}]
        device = self._device_bag(
            [{"name": "Stream 1", "externalId": "front"}, {"name": "Rear", "externalId": "rear"}],
            **{"cockpit-saved-profiles-v8": profiles},
        )
        bag = {self.KEY: [
            {"name": "front", "externalId": "front"}, {"name": "Rear", "externalId": "rear"},
        ]}

        (plan,) = plan_cockpit_stream_renames(bag, device)
        widgets = plan.updates["cockpit/settings/sky1/cockpit-saved-profiles-v8"][0]["views"][0]["widgets"]
        assert [w["options"]["internalStreamName"] for w in widgets] == ["front", "Rear"]
        assert plan.widget_count == 1

    def test_no_plan_when_names_unchanged(self):
        device = self._device_bag(
            [{"name": "front", "externalId": "front"}],
            **{"cockpit-saved-profiles-v8": [{"views": [{"widgets": [_video_widget("front")]}]}]},
        )
        bag = {self.KEY: [{"name": "front", "externalId": "front"}]}
        assert plan_cockpit_stream_renames(bag, device) == []

    def test_rename_without_widgets_has_no_updates(self):
        device = self._device_bag([{"name": "Stream 1", "externalId": "front"}])
        bag = {self.KEY: [{"name": "front", "externalId": "front"}]}
        (plan,) = plan_cockpit_stream_renames(bag, device)
        assert plan.renames == {"Stream 1": "front"}
        assert plan.updates == {}
        assert plan.widget_count == 0

    @pytest.mark.parametrize("device", [
        None,
        {},
        {"cockpit": {"settings": {"other-user": {}}}},
        {"cockpit": {"settings": {"sky1": {"cockpit-streams-correspondency": "garbage"}}}},
    ])
    def test_nothing_known_on_device(self, device):
        bag = {self.KEY: [{"name": "front", "externalId": "front"}]}
        assert plan_cockpit_stream_renames(bag, device) == []

    def test_ignores_unrelated_bag_keys(self):
        device = self._device_bag([{"name": "Stream 1", "externalId": "front"}])
        bag = {"major_tom": {"token": "x"}, "cockpit/settings/sky1/cockpit-custom-rtc-config": {}}
        assert plan_cockpit_stream_renames(bag, device) == []


class TestPlanCockpitWidgetOptions:
    @staticmethod
    def _bag(widgets):
        return {"cockpit": {"settings": {"sky1": {
            "cockpit-saved-profiles-v8": [{"views": [{"widgets": widgets}]}],
            "cockpit-alert-volume": 1,
        }}}}

    @staticmethod
    def _video(fit, **extra):
        return {"component": "VideoPlayer",
                "options": {"videoFitStyle": fit, "internalStreamName": "front", **extra}}

    def test_sets_option_on_every_matching_widget(self):
        from skynet.extract import plan_cockpit_widget_options
        bag = self._bag([self._video("cover"), self._video("fill"),
                         {"component": "Map", "options": {"zoom": 3}}])
        plans = plan_cockpit_widget_options({"sky1": {"VideoPlayer": {"videoFitStyle": "fill"}}}, bag)
        assert len(plans) == 1
        assert plans[0].widget_count == 1
        updated = plans[0].updates["cockpit/settings/sky1/cockpit-saved-profiles-v8"]
        widgets = updated[0]["views"][0]["widgets"]
        assert [w["options"].get("videoFitStyle") for w in widgets[:2]] == ["fill", "fill"]
        assert widgets[0]["options"]["internalStreamName"] == "front"   # other options kept
        assert widgets[2] == {"component": "Map", "options": {"zoom": 3}}
        # the device bag itself is not modified
        assert bag["cockpit"]["settings"]["sky1"]["cockpit-saved-profiles-v8"][0]["views"][0]["widgets"][0]["options"]["videoFitStyle"] == "cover"

    def test_no_plan_when_already_set(self):
        from skynet.extract import plan_cockpit_widget_options
        bag = self._bag([self._video("fill")])
        assert plan_cockpit_widget_options({"sky1": {"VideoPlayer": {"videoFitStyle": "fill"}}}, bag) == []

    def test_unknown_user_or_bad_input(self):
        from skynet.extract import plan_cockpit_widget_options
        bag = self._bag([self._video("cover")])
        assert plan_cockpit_widget_options({"other": {"VideoPlayer": {"videoFitStyle": "fill"}}}, bag) == []
        assert plan_cockpit_widget_options(None, bag) == []
        assert plan_cockpit_widget_options({"sky1": {"VideoPlayer": {"videoFitStyle": "fill"}}}, None) == []



class TestWidgetOptionRules:
    RULE = {"VeryGenericIndicator": [{
        "match": {"variableName": ["SCALED_PRESSURE2/temperature", "CubeTempF"]},
        "set": {"displayName": "Cube Temp", "variableName": "CubeTempF",
                "variableUnit": "°F", "variableMultiplier": 1},
    }]}

    @staticmethod
    def _bag(widgets):
        return {"cockpit": {"settings": {"sky1": {"profiles": [{"widgets": widgets}]}}}}

    @staticmethod
    def _generic(name, unit="%"):
        return {"component": "VeryGenericIndicator",
                "options": {"displayName": name, "variableName": name, "variableUnit": unit}}

    def test_rule_changes_only_matching_widget(self):
        from skynet.extract import plan_cockpit_widget_options
        temp = {"component": "VeryGenericIndicator", "options": {
            "displayName": "Water Temp", "variableName": "SCALED_PRESSURE2/temperature",
            "variableUnit": "°C", "variableMultiplier": ".01", "iconName": "mdi-thermometer"}}
        bag = self._bag([temp, self._generic("PilotGain")])
        plans = plan_cockpit_widget_options({"sky1": self.RULE}, bag)
        assert plans[0].widget_count == 1
        widgets = plans[0].updates["cockpit/settings/sky1/profiles"][0]["widgets"]
        assert widgets[0]["options"] == {
            "displayName": "Cube Temp", "variableName": "CubeTempF", "variableUnit": "°F",
            "variableMultiplier": 1, "iconName": "mdi-thermometer"}
        assert widgets[1] == self._generic("PilotGain")

    def test_rule_is_idempotent(self):
        from skynet.extract import plan_cockpit_widget_options
        done = {"component": "VeryGenericIndicator", "options": {
            "displayName": "Cube Temp", "variableName": "CubeTempF",
            "variableUnit": "°F", "variableMultiplier": 1}}
        assert plan_cockpit_widget_options({"sky1": self.RULE}, self._bag([done])) == []
