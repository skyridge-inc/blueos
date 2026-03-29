"""Polygon file parsing and coordinate projection."""

from __future__ import annotations

import math


def parse_poly_file(path: str) -> list[tuple[float, float]]:
    """Parse an ArduPilot .poly file into a list of (lat, lon) tuples.

    Format: one space-separated `lat lon` pair per line.
    Lines starting with # are comments. Blank lines are skipped.
    """
    vertices: list[tuple[float, float]] = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            if len(parts) < 2:
                raise ValueError(f"Malformed line (expected 'lat lon'): {line!r}")
            vertices.append((float(parts[0]), float(parts[1])))

    if len(vertices) < 3:
        raise ValueError(
            f"Polygon requires at least 3 vertices, got {len(vertices)}"
        )
    return vertices


def _centroid(vertices: list[tuple[float, float]]) -> tuple[float, float]:
    """Return the arithmetic centroid of a list of (lat, lon) points."""
    n = len(vertices)
    lat = sum(v[0] for v in vertices) / n
    lon = sum(v[1] for v in vertices) / n
    return lat, lon


def to_xy(
    vertices: list[tuple[float, float]],
    origin: tuple[float, float] | None = None,
) -> tuple[list[tuple[float, float]], tuple[float, float]]:
    """Project lat/lon to local XY meters using equirectangular projection.

    Returns (xy_points, origin) where origin is the (lat, lon) used as reference.
    If origin is None, the centroid of vertices is used.
    """
    if origin is None:
        origin = _centroid(vertices)
    lat0, lon0 = origin
    cos_lat = math.cos(math.radians(lat0))
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * cos_lat

    xy = []
    for lat, lon in vertices:
        x = (lon - lon0) * meters_per_deg_lon
        y = (lat - lat0) * meters_per_deg_lat
        xy.append((x, y))
    return xy, origin


def to_latlon(
    xy_points: list[tuple[float, float]],
    origin: tuple[float, float],
) -> list[tuple[float, float]]:
    """Reverse-project XY meters back to lat/lon."""
    lat0, lon0 = origin
    cos_lat = math.cos(math.radians(lat0))
    meters_per_deg_lat = 111_320.0
    meters_per_deg_lon = 111_320.0 * cos_lat

    result = []
    for x, y in xy_points:
        lat = lat0 + y / meters_per_deg_lat
        lon = lon0 + x / meters_per_deg_lon
        result.append((lat, lon))
    return result


def auto_heading(vertices_xy: list[tuple[float, float]]) -> float:
    """Find the heading angle (degrees, 0=north/+Y, 90=east/+X, clockwise) of the longest polygon edge."""
    max_len = 0.0
    best_angle = 0.0
    n = len(vertices_xy)
    for i in range(n):
        x1, y1 = vertices_xy[i]
        x2, y2 = vertices_xy[(i + 1) % n]
        dx = x2 - x1
        dy = y2 - y1
        length = math.hypot(dx, dy)
        if length > max_len:
            max_len = length
            # atan2 gives angle from +X axis, convert to heading from +Y (north)
            angle_from_x = math.degrees(math.atan2(dy, dx))
            heading = 90.0 - angle_from_x
            # Normalize to [0, 180) since direction doesn't matter for mowing
            heading = heading % 360.0
            if heading >= 180.0:
                heading -= 180.0
            best_angle = heading
    return best_angle
