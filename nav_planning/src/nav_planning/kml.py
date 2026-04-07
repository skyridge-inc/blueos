"""KML Track and Tour visualization output for Google Earth."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

KML_NS = "http://www.opengis.net/kml/2.2"
GX_NS = "http://www.google.com/kml/ext/2.2"

ET.register_namespace("", KML_NS)
ET.register_namespace("gx", GX_NS)

COLORS = [
    "#e6194b", "#3cb44b", "#4363d8", "#f58231", "#911eb4",
    "#42d4f4", "#f032e6", "#bfef45", "#fabed4", "#469990",
    "#dcbeff", "#9A6324", "#800000", "#aaffc3", "#808000",
    "#000075", "#a9a9a9", "#e6beff", "#fffac8", "#ffd8b1",
]

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def _kml_color(hex_color: str, alpha: int = 0xFF) -> str:
    """Convert #rrggbb to KML aabbggrr format."""
    hex_color = hex_color.lstrip("#")
    r, g, b = hex_color[0:2], hex_color[2:4], hex_color[4:6]
    return f"{alpha:02x}{b}{g}{r}"


def _haversine_distance(
    p1: tuple[float, float], p2: tuple[float, float]
) -> float:
    """Distance in meters between two (lat, lon) points."""
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.asin(math.sqrt(a))


def _compute_heading(
    p1: tuple[float, float], p2: tuple[float, float]
) -> float:
    """Bearing in degrees (0=north, clockwise) from p1 to p2 (lat, lon)."""
    lat1, lon1 = math.radians(p1[0]), math.radians(p1[1])
    lat2, lon2 = math.radians(p2[0]), math.radians(p2[1])
    dlon = lon2 - lon1
    x = math.sin(dlon) * math.cos(lat2)
    y = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    heading = math.degrees(math.atan2(x, y))
    return heading % 360


def _gx(tag: str) -> str:
    """Return a Clark-notation gx: tag."""
    return f"{{{GX_NS}}}{tag}"


def _kml(tag: str) -> str:
    """Return a Clark-notation KML tag."""
    return f"{{{KML_NS}}}{tag}"


def generate_kml_track(
    mower_paths: list[list[tuple[float, float]]],
    output_path: str,
    speed_mps: float = 1.0,
) -> None:
    """Write a KML file with gx:Track elements for Google Earth animated playback.

    Args:
        mower_paths: List of per-mower paths, each a list of (lat, lon) tuples.
        output_path: File path for the KML output.
        speed_mps: Simulated mower speed in m/s for timestamp spacing.
    """
    if not mower_paths:
        raise ValueError("No mower paths to visualize")

    root = ET.Element(_kml("kml"))
    doc = ET.SubElement(root, _kml("Document"))
    name = ET.SubElement(doc, _kml("name"))
    name.text = "Mower Paths"

    for i, path in enumerate(mower_paths):
        color = COLORS[i % len(COLORS)]
        kml_col = _kml_color(color)

        # Style
        style_id = f"mower{i+1}-style"
        style = ET.SubElement(doc, _kml("Style"), id=style_id)
        line_style = ET.SubElement(style, _kml("LineStyle"))
        ET.SubElement(line_style, _kml("color")).text = kml_col
        ET.SubElement(line_style, _kml("width")).text = "3"
        icon_style = ET.SubElement(style, _kml("IconStyle"))
        ET.SubElement(icon_style, _kml("color")).text = kml_col

        # Placemark with gx:Track
        pm = ET.SubElement(doc, _kml("Placemark"))
        ET.SubElement(pm, _kml("name")).text = f"Mower {i+1}"
        ET.SubElement(pm, _kml("styleUrl")).text = f"#{style_id}"

        track = ET.SubElement(pm, _gx("Track"))

        # Compute timestamps
        t = BASE_TIME
        for j, (lat, lon) in enumerate(path):
            ET.SubElement(track, "when").text = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            if j < len(path) - 1:
                dist = _haversine_distance(path[j], path[j + 1])
                dt = dist / speed_mps if speed_mps > 0 else 1.0
                t += timedelta(seconds=dt)

        # Coordinates (lon lat alt, space-separated)
        for lat, lon in path:
            ET.SubElement(track, _gx("coord")).text = f"{lon} {lat} 0"

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_path, xml_declaration=True, encoding="UTF-8")


def generate_kml_tour(
    mower_paths: list[list[tuple[float, float]]],
    output_path: str,
    speed_mps: float = 1.0,
    altitude_m: float = 30.0,
    tilt_deg: float = 60.0,
) -> None:
    """Write a KML file with a gx:Tour cinematic flyover following mower paths.

    Args:
        mower_paths: List of per-mower paths, each a list of (lat, lon) tuples.
        output_path: File path for the KML output.
        speed_mps: Simulated camera speed in m/s.
        altitude_m: Camera altitude above ground in meters.
        tilt_deg: Camera tilt angle in degrees (0=straight down, 90=horizon).
    """
    if not mower_paths:
        raise ValueError("No mower paths to visualize")

    root = ET.Element(_kml("kml"))
    doc = ET.SubElement(root, _kml("Document"))
    name = ET.SubElement(doc, _kml("name"))
    name.text = "Mower Tour"

    # Static polylines for all paths
    for i, path in enumerate(mower_paths):
        color = COLORS[i % len(COLORS)]
        pm = ET.SubElement(doc, _kml("Placemark"))
        ET.SubElement(pm, _kml("name")).text = f"Mower {i+1} Path"

        style = ET.SubElement(pm, _kml("Style"))
        ls = ET.SubElement(style, _kml("LineStyle"))
        ET.SubElement(ls, _kml("color")).text = _kml_color(color)
        ET.SubElement(ls, _kml("width")).text = "3"

        line = ET.SubElement(pm, _kml("LineString"))
        ET.SubElement(line, _kml("altitudeMode")).text = "clampToGround"
        coords_text = " ".join(f"{lon},{lat},0" for lat, lon in path)
        ET.SubElement(line, _kml("coordinates")).text = coords_text

    # Animated gx:Track placemarks for all mowers
    # Pre-compute timestamps for mower 1 (used to sync the tour camera)
    guide_timestamps: list[datetime] = []
    for i, path in enumerate(mower_paths):
        color = COLORS[i % len(COLORS)]
        kml_col = _kml_color(color)

        style_id = f"tour-mower{i+1}-style"
        style = ET.SubElement(doc, _kml("Style"), id=style_id)
        icon_style = ET.SubElement(style, _kml("IconStyle"))
        ET.SubElement(icon_style, _kml("color")).text = kml_col

        pm = ET.SubElement(doc, _kml("Placemark"))
        ET.SubElement(pm, _kml("name")).text = f"Mower {i+1}"
        ET.SubElement(pm, _kml("styleUrl")).text = f"#{style_id}"

        track = ET.SubElement(pm, _gx("Track"))
        t = BASE_TIME
        timestamps: list[datetime] = []
        for j, (lat, lon) in enumerate(path):
            timestamps.append(t)
            ET.SubElement(track, "when").text = t.strftime("%Y-%m-%dT%H:%M:%SZ")
            if j < len(path) - 1:
                dist = _haversine_distance(path[j], path[j + 1])
                dt = dist / speed_mps if speed_mps > 0 else 1.0
                t += timedelta(seconds=dt)
        for lat, lon in path:
            ET.SubElement(track, _gx("coord")).text = f"{lon} {lat} 0"

        if i == 0:
            guide_timestamps = timestamps

    # Tour camera following mower 1
    guide_path = mower_paths[0]
    tour = ET.SubElement(doc, _gx("Tour"))
    ET.SubElement(tour, _kml("name")).text = "Mower Flyover"
    playlist = ET.SubElement(tour, _gx("Playlist"))

    heading = 0.0
    for j, (lat, lon) in enumerate(guide_path):
        if j < len(guide_path) - 1:
            heading = _compute_heading(guide_path[j], guide_path[j + 1])

        # Duration synced to track timestamps
        if j < len(guide_timestamps) - 1:
            dt = (guide_timestamps[j + 1] - guide_timestamps[j]).total_seconds()
            duration = max(0.5, min(5.0, dt))
        else:
            duration = 1.0

        fly_to = ET.SubElement(playlist, _gx("FlyTo"))
        ET.SubElement(fly_to, _gx("duration")).text = f"{duration:.1f}"
        ET.SubElement(fly_to, _gx("flyToMode")).text = "smooth"

        look_at = ET.SubElement(fly_to, _kml("LookAt"))
        ET.SubElement(look_at, _kml("longitude")).text = f"{lon:.8f}"
        ET.SubElement(look_at, _kml("latitude")).text = f"{lat:.8f}"
        ET.SubElement(look_at, _kml("altitude")).text = f"{altitude_m}"
        ET.SubElement(look_at, _kml("heading")).text = f"{heading:.1f}"
        ET.SubElement(look_at, _kml("tilt")).text = f"{tilt_deg}"
        ET.SubElement(look_at, _kml("range")).text = "50"
        ET.SubElement(look_at, _kml("altitudeMode")).text = "relativeToGround"

    tree = ET.ElementTree(root)
    ET.indent(tree, space="  ")
    tree.write(output_path, xml_declaration=True, encoding="UTF-8")
