"""Configuration extraction and YAML serialization."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

from .blueos_api import BlueOSClient
from .exceptions import ParamFileError
from .host_config import (
    DNSMASQ_HOST_PATH,
    autostart_installed_command,
    parse_dnsmasq_conf,
    parse_wifi_profile,
    wifi_profile_get_command,
)
from .params import EPSILON


# Candidate paths for MediaMTX config via the BlueOS file browser API.
# Paths are relative to the file browser root scope (typically /usr/blueos/userdata/).
# Tried in order; first successful read wins.
MEDIAMTX_CONFIG_CANDIDATES = [
    "extensions/mediamtx/mediamtx.yml",
]


def fetch_mediamtx_config(
    client: BlueOSClient,
    config_path: str | None = None,
) -> dict[str, Any] | None:
    """Fetch and parse the MediaMTX YAML config from a BlueOS device.

    Tries the given config_path first, then falls back to candidate paths.
    Returns a dict with 'config_path' and 'config' keys, or None if not found.
    """
    paths_to_try = [config_path] if config_path else MEDIAMTX_CONFIG_CANDIDATES

    for path in paths_to_try:
        raw = client.get_file(path)
        if raw is not None:
            try:
                parsed = yaml.safe_load(raw)
            except yaml.YAMLError:
                continue
            if isinstance(parsed, dict):
                return {"config_path": path, "config": parsed}
    return None


def push_mediamtx_config(
    client: BlueOSClient,
    mediamtx: dict[str, Any],
) -> bool:
    """Serialize and push MediaMTX config back to the device.

    Expects a dict with 'config_path' (str) and 'config' (dict) keys.
    """
    config_path = mediamtx.get("config_path")
    config = mediamtx.get("config")
    if not config_path or not isinstance(config, dict):
        return False
    content = yaml.dump(config, default_flow_style=False, sort_keys=False, allow_unicode=True)
    return client.put_file(config_path, content)


# mavlink-camera-manager's source string for a stream that relays an RTSP URL
# (the URL is the stream's first endpoint).
REDIRECT_SOURCE = "Redirect"


def _video_source_string(video_source: Any) -> str | None:
    """Recover the POST `source` string from MCM's serialized video_source.

    video_source is an externally tagged enum, e.g.
    {"Redirect": {"name": ..., "source": {"Redirect": "Redirect"}}} or
    {"Local": {"name": ..., "device_path": "/dev/video0", ...}}.
    """
    if not isinstance(video_source, dict) or len(video_source) != 1:
        return None
    kind, inner = next(iter(video_source.items()))
    if kind == REDIRECT_SOURCE:
        return REDIRECT_SOURCE
    if not isinstance(inner, dict):
        return None
    if isinstance(inner.get("device_path"), str):
        return inner["device_path"]
    source = inner.get("source")
    if isinstance(source, dict) and len(source) == 1:
        value = next(iter(source.values()))
        if isinstance(value, str):
            return value
    return None


def fetch_video_streams(client: BlueOSClient) -> list[dict[str, Any]] | None:
    """Fetch mavlink-camera-manager streams as provisionable YAML entries.

    Each entry is {name, source, endpoints} plus, for non-redirect sources,
    the capture configuration. Redirect streams omit it: MCM replaces it
    with what it probes from the URL, so it isn't provisioning data.
    """
    raw = client.get_video_streams()
    if not isinstance(raw, list):
        return None
    streams: list[dict[str, Any]] = []
    for status in raw:
        vs = status.get("video_and_stream") if isinstance(status, dict) else None
        if not isinstance(vs, dict):
            continue
        info = vs.get("stream_information") or {}
        source = _video_source_string(vs.get("video_source"))
        if not vs.get("name") or source is None:
            continue
        entry: dict[str, Any] = {
            "name": vs["name"],
            "source": source,
            "endpoints": list(info.get("endpoints") or []),
        }
        if source != REDIRECT_SOURCE and info.get("configuration"):
            entry["configuration"] = info["configuration"]
        if info.get("extended_configuration"):
            entry["extended_configuration"] = info["extended_configuration"]
        streams.append(entry)
    return streams


def video_stream_post_body(entry: dict[str, Any]) -> dict[str, Any]:
    """Build the mavlink-camera-manager POST /streams body for a YAML entry."""
    configuration = entry.get("configuration")
    if configuration is None and entry.get("source") == REDIRECT_SOURCE:
        configuration = {"type": "redirect"}
    info: dict[str, Any] = {
        "endpoints": list(entry.get("endpoints") or []),
        "configuration": configuration,
    }
    if entry.get("extended_configuration"):
        info["extended_configuration"] = entry["extended_configuration"]
    return {"name": entry["name"], "source": entry["source"], "stream_information": info}


def extract_hostname_from_url(url: str) -> str:
    """Extract domain/host from URL for use as filename."""
    parsed = urlparse(url)
    return parsed.hostname or parsed.path


def output_filename(url: str) -> Path:
    """Derive YAML output filename from the target URL."""
    host = extract_hostname_from_url(url)
    return Path(f"{host}.yaml")


def _clean_ethernet(raw: list[Any] | None) -> list[dict[str, Any]] | None:
    """Strip ephemeral routing/info from ethernet entries, keep addresses.

    DHCP-client leases (``mode: client``, e.g. eth0 behind Starlink) are
    always dynamic, so they are never captured.
    """
    if raw is None:
        return None
    cleaned = []
    for iface in raw:
        if not isinstance(iface, dict):
            continue
        entry: dict[str, Any] = {"name": iface.get("name")}
        if "addresses" in iface:
            entry["addresses"] = [
                a for a in iface["addresses"] or []
                if not (isinstance(a, dict) and a.get("mode") == "client")
            ]
        cleaned.append(entry)
    return cleaned


# Bag keys that are ephemeral / per-session and should not be provisioned.
_BAG_EXCLUDE_KEYS = frozenset({
    "settings",   # BlueOS UI prefs (dark mode, tour state, notification timestamps)
    "wizard",     # setup wizard completion — re-runs on fresh install anyway
    "cockpit",    # per-user Cockpit UI layouts, widget profiles, vehicle-id UUID
})


def _clean_bag(raw: dict[str, Any] | None) -> dict[str, Any] | None:
    """Remove ephemeral / per-session entries from the bag."""
    if raw is None:
        return None
    return {k: v for k, v in raw.items() if k not in _BAG_EXCLUDE_KEYS}


# -- Cockpit stream renames --
#
# Cockpit (v1.17.x) keeps per-user settings in the bag at
# cockpit/settings/<user>/<key>. ``cockpit-streams-correspondency`` maps an
# internal stream name (what video widgets select via
# ``options.internalStreamName``) to a mavlink-camera-manager stream
# (``externalId``). Renaming an internal name alone leaves every widget
# pointing at a name that no longer exists, so the widgets are re-pointed too.

COCKPIT_CORRESPONDENCY_KEY = "cockpit-streams-correspondency"
COCKPIT_CORRESPONDENCY_BAG_KEY = re.compile(
    rf"^cockpit/settings/(?P<user>[^/]+)/{COCKPIT_CORRESPONDENCY_KEY}$"
)


@dataclass
class CockpitStreamRenamePlan:
    """Widget updates needed before a user's stream correspondency is replaced."""

    user: str
    renames: dict[str, str]                                   # old internal name -> new
    updates: dict[str, Any] = field(default_factory=dict)     # bag key -> new setting value
    widget_count: int = 0


def _internal_names_by_external_id(correspondency: Any) -> dict[str, str]:
    if not isinstance(correspondency, list):
        return {}
    return {
        str(c["externalId"]): str(c["name"])
        for c in correspondency
        if isinstance(c, dict) and c.get("externalId") is not None and c.get("name") is not None
    }


def _repoint_widgets(node: Any, renames: dict[str, str]) -> int:
    """Rewrite ``internalStreamName`` values in place; returns how many changed."""
    count = 0
    if isinstance(node, dict):
        name = node.get("internalStreamName")
        if isinstance(name, str) and name in renames:
            node["internalStreamName"] = renames[name]
            count += 1
        for value in node.values():
            count += _repoint_widgets(value, renames)
    elif isinstance(node, list):
        for item in node:
            count += _repoint_widgets(item, renames)
    return count


def plan_cockpit_stream_renames(
    bag_config: dict[str, Any], device_bag: dict[str, Any] | None,
) -> list[CockpitStreamRenamePlan]:
    """Work out which Cockpit widgets to re-point for the YAML's stream renames.

    For each ``cockpit/settings/<user>/cockpit-streams-correspondency`` key in
    the YAML bag, compares it with the device's current correspondency by
    ``externalId``. Every other setting of that user that holds a renamed
    ``internalStreamName`` is returned as an updated copy, keyed by its bag path.
    Users with no rename get no plan.
    """
    settings_root = (device_bag or {}).get("cockpit", {})
    settings_root = settings_root.get("settings", {}) if isinstance(settings_root, dict) else {}
    if not isinstance(settings_root, dict):
        return []

    plans: list[CockpitStreamRenamePlan] = []
    for key, new_correspondency in bag_config.items():
        match = COCKPIT_CORRESPONDENCY_BAG_KEY.match(str(key))
        if not match:
            continue
        user = match["user"]
        user_settings = settings_root.get(user)
        if not isinstance(user_settings, dict):
            continue

        old_names = _internal_names_by_external_id(user_settings.get(COCKPIT_CORRESPONDENCY_KEY))
        new_names = _internal_names_by_external_id(new_correspondency)
        renames = {
            old: new_names[ext]
            for ext, old in old_names.items()
            if ext in new_names and new_names[ext] != old
        }
        if not renames:
            continue

        plan = CockpitStreamRenamePlan(user=user, renames=renames)
        for setting_key, value in user_settings.items():
            if setting_key == COCKPIT_CORRESPONDENCY_KEY:
                continue
            updated = copy.deepcopy(value)
            changed = _repoint_widgets(updated, renames)
            if changed:
                plan.updates[f"cockpit/settings/{user}/{setting_key}"] = updated
                plan.widget_count += changed
        plans.append(plan)
    return plans


COCKPIT_WIDGET_OPTIONS_KEY = "cockpit_widget_options"


@dataclass
class CockpitWidgetOptionsPlan:
    """Cockpit settings to rewrite so a user's widgets get the YAML's options."""

    user: str
    updates: dict[str, Any] = field(default_factory=dict)     # bag key -> new setting value
    widget_count: int = 0


def _widget_rules(spec: Any) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(match, set) pairs for one component's entry.

    A mapping sets those options on every widget of the component; a list of
    ``{match: {...}, set: {...}}`` rules only touches widgets whose options
    match (a list value in ``match`` means any of those values).
    """
    if isinstance(spec, dict):
        return [({}, spec)] if spec else []
    rules = []
    for rule in spec if isinstance(spec, list) else []:
        if isinstance(rule, dict) and isinstance(rule.get("set"), dict) and rule["set"]:
            match = rule.get("match")
            rules.append((match if isinstance(match, dict) else {}, rule["set"]))
    return rules


def _matches(options: dict[str, Any], match: dict[str, Any]) -> bool:
    return all(
        options.get(k) in v if isinstance(v, list) else options.get(k) == v
        for k, v in match.items()
    )


def _set_widget_options(node: Any, by_component: dict[str, Any]) -> int:
    """Apply options to widgets (dicts with ``component`` + ``options``) in place.

    Returns how many widgets changed.
    """
    count = 0
    if isinstance(node, dict):
        rules = _widget_rules(by_component.get(node.get("component")))  # type: ignore[arg-type]
        options = node.get("options")
        if rules and isinstance(options, dict):
            changed = False
            for match, wanted in rules:
                if _matches(options, match) and any(options.get(k) != v for k, v in wanted.items()):
                    options.update(wanted)
                    changed = True
            count += changed
        for value in node.values():
            count += _set_widget_options(value, by_component)
    elif isinstance(node, list):
        for item in node:
            count += _set_widget_options(item, by_component)
    return count


def plan_cockpit_widget_options(
    widget_options: Any, device_bag: dict[str, Any] | None,
) -> list[CockpitWidgetOptionsPlan]:
    """Work out which Cockpit settings to rewrite for ``cockpit_widget_options``.

    ``widget_options`` maps Cockpit user -> widget component -> options, e.g.
    ``{"sky1": {"VideoPlayer": {"videoFitStyle": "fill"}}}``. Every widget of
    that component in any of the user's settings (all profiles and views) gets
    those options; other options and widgets are untouched. Settings already
    matching are left out, so users with nothing to change get no plan.
    """
    if not isinstance(widget_options, dict):
        return []
    settings_root = (device_bag or {}).get("cockpit", {})
    settings_root = settings_root.get("settings", {}) if isinstance(settings_root, dict) else {}
    if not isinstance(settings_root, dict):
        return []

    plans: list[CockpitWidgetOptionsPlan] = []
    for user, by_component in widget_options.items():
        user_settings = settings_root.get(user)
        if not isinstance(user_settings, dict) or not isinstance(by_component, dict):
            continue
        plan = CockpitWidgetOptionsPlan(user=str(user))
        for setting_key, value in user_settings.items():
            updated = copy.deepcopy(value)
            changed = _set_widget_options(updated, by_component)
            if changed:
                plan.updates[f"cockpit/settings/{user}/{setting_key}"] = updated
                plan.widget_count += changed
        if plan.updates:
            plans.append(plan)
    return plans


def fetch_dhcp_reservations(client: BlueOSClient) -> list[dict[str, Any]] | None:
    """Read static DHCP reservations from the host dnsmasq config.

    Returns [] when the file does not exist, None if the host is unreachable.
    """
    result = client.run_host_command(f"cat {DNSMASQ_HOST_PATH}")
    if not isinstance(result, dict):
        return None
    if result.get("return_code") != 0:
        return []
    return parse_dnsmasq_conf(result.get("stdout") or "")


def fetch_wifi_saved(client: BlueOSClient) -> list[Any] | None:
    """Saved WiFi networks, each with the interface/band its host profile is pinned to.

    BlueOS only reports SSIDs; ``interface`` and ``band`` come from the
    NetworkManager profile on the host and are omitted when unset.
    """
    saved = client.get_wifi_saved()
    if not isinstance(saved, list):
        return saved
    for entry in saved:
        if not isinstance(entry, dict) or not entry.get("ssid"):
            continue
        result = client.run_host_command(wifi_profile_get_command(str(entry["ssid"])))
        if isinstance(result, dict) and result.get("return_code") == 0:
            entry.update(parse_wifi_profile(result.get("stdout") or ""))
    return saved


def fetch_autopilot_autostart(client: BlueOSClient) -> bool | None:
    """Whether the skynet autopilot hot-plug start is installed; None if unknown."""
    result = client.run_host_command(autostart_installed_command())
    if not isinstance(result, dict) or result.get("return_code") is None:
        return None
    return result["return_code"] == 0


def extract_config(client: BlueOSClient) -> dict[str, Any]:
    """Fetch provisionable configuration from a BlueOS device.

    Only captures fields that are meaningful for fleet provisioning
    (identity, extensions, network addresses, bag settings for extensions).
    Runtime state (version, board, firmware, services, routes) is excluded.
    """
    config: dict[str, Any] = {}

    # Identity
    config["hostname"] = client.get_hostname()
    config["vehicle_name"] = client.get_vehicle_name()

    # Extensions (which are installed and their versions)
    config["extensions"] = client.get_extensions()

    # Config store — extension settings, minus ephemeral UI state
    config["bag"] = _clean_bag(client.get_bag())

    # Networking — static IP addresses only, no ephemeral routes
    config["network"] = {
        "ethernet": _clean_ethernet(client.get_ethernet()),
        "wifi_saved": fetch_wifi_saved(client),
        "hotspot": client.get_hotspot(),
        "dhcp_reservations": fetch_dhcp_reservations(client),
    }

    # Camera-manager streams — what Cockpit's video widget can play over WebRTC
    config["video_streams"] = fetch_video_streams(client)

    # Host udev/systemd hook that starts the autopilot when a board is plugged in
    config["autopilot_autostart"] = fetch_autopilot_autostart(client)

    return config


def load_yaml(path: Path) -> dict[str, Any]:
    """Read and parse a YAML config file.

    Raises:
        ParamFileError: If the file cannot be read or parsed.
    """
    try:
        text = path.read_text()
    except OSError as e:
        raise ParamFileError(f"Cannot read {path}: {e}") from e
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise ParamFileError(f"Invalid YAML in {path}: {e}") from e
    if not isinstance(data, dict):
        raise ParamFileError(f"Expected a YAML mapping in {path}, got {type(data).__name__}")
    return data


# Fleet-wide autopilot params shared by every rover YAML in the same directory.
AUTOPILOT_BASE_FILENAME = "autopilot_base.yaml"


def default_base_path(rover_yaml: Path) -> Path:
    """The autopilot base file that sits next to a rover YAML."""
    return rover_yaml.parent / AUTOPILOT_BASE_FILENAME


def load_autopilot_base(path: Path) -> dict[str, float]:
    """Read the ``autopilot_params`` mapping from an autopilot base YAML.

    Raises:
        ParamFileError: If the file is unreadable or the section is not a mapping.
    """
    params = load_yaml(path).get("autopilot_params")
    if params is None:
        return {}
    if not isinstance(params, dict):
        raise ParamFileError(f"autopilot_params in {path} must be a mapping")
    return params


def merge_autopilot_params(
    base: dict[str, float], overrides: dict[str, float] | None,
) -> dict[str, float]:
    """Base params with a rover's own params applied on top (rover wins)."""
    return dict(sorted({**base, **(overrides or {})}.items()))


def params_diff_from_base(
    params: dict[str, float], base: dict[str, float], epsilon: float = EPSILON,
) -> dict[str, float]:
    """Params that are missing from the base or differ from it by more than epsilon."""
    return {
        k: v for k, v in sorted(params.items())
        if k not in base or abs(float(v) - float(base[k])) > epsilon
    }


def save_yaml(config: dict[str, Any], path: Path) -> None:
    """Write config dict to YAML file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        yaml.dump(
            config,
            f,
            default_flow_style=False,
            sort_keys=False,
            allow_unicode=True,
        )
