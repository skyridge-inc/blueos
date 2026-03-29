"""Boustrophedon (back-and-forth) coverage path generation."""

from __future__ import annotations

import math
from shapely.geometry import Polygon, LineString, MultiLineString


def rotate_polygon(
    vertices: list[tuple[float, float]], angle_deg: float
) -> list[tuple[float, float]]:
    """Rotate XY points by angle (degrees, clockwise from +Y) around their centroid.

    The rotation aligns the mowing direction with the X axis so sweep lines
    can be simple horizontal lines.
    """
    n = len(vertices)
    cx = sum(v[0] for v in vertices) / n
    cy = sum(v[1] for v in vertices) / n

    # Convert heading (CW from +Y) to math angle (CCW from +X) for rotation
    # We want to rotate so the heading direction maps to +X
    rot_rad = math.radians(angle_deg - 90.0)

    rotated = []
    for x, y in vertices:
        dx, dy = x - cx, y - cy
        rx = dx * math.cos(rot_rad) + dy * math.sin(rot_rad)
        ry = -dx * math.sin(rot_rad) + dy * math.cos(rot_rad)
        rotated.append((rx + cx, ry + cy))
    return rotated


def _unrotate_points(
    points: list[tuple[float, float]],
    angle_deg: float,
    cx: float,
    cy: float,
) -> list[tuple[float, float]]:
    """Reverse the rotation applied by rotate_polygon."""
    rot_rad = math.radians(angle_deg - 90.0)
    cos_r, sin_r = math.cos(rot_rad), math.sin(rot_rad)

    result = []
    for x, y in points:
        dx, dy = x - cx, y - cy
        # Inverse rotation: transpose of rotation matrix
        ox = dx * cos_r - dy * sin_r
        oy = dx * sin_r + dy * cos_r
        result.append((ox + cx, oy + cy))
    return result


def sweep_lines(
    y_min: float, y_max: float, spacing: float
) -> list[float]:
    """Generate Y coordinates for horizontal sweep lines."""
    lines = []
    y = y_min + spacing / 2.0
    while y < y_max:
        lines.append(y)
        y += spacing
    return lines


def clip_and_zigzag(
    poly: Polygon, y_values: list[float], x_min: float, x_max: float
) -> list[tuple[float, float]]:
    """Intersect sweep lines with polygon and connect in alternating direction.

    Returns an ordered list of (x, y) waypoints.
    """
    margin = (x_max - x_min) * 0.1
    path: list[tuple[float, float]] = []

    for i, y in enumerate(y_values):
        line = LineString([(x_min - margin, y), (x_max + margin, y)])
        intersection = poly.intersection(line)

        if intersection.is_empty:
            continue

        # Collect all segments from this sweep line
        segments: list[tuple[tuple[float, float], tuple[float, float]]] = []
        if isinstance(intersection, LineString):
            coords = list(intersection.coords)
            if len(coords) >= 2:
                segments.append((coords[0], coords[-1]))
        elif isinstance(intersection, MultiLineString):
            for seg in intersection.geoms:
                coords = list(seg.coords)
                if len(coords) >= 2:
                    segments.append((coords[0], coords[-1]))

        if not segments:
            continue

        # Sort segments left-to-right by their leftmost X
        segments.sort(key=lambda s: min(s[0][0], s[1][0]))

        # Alternate direction: even rows left-to-right, odd rows right-to-left
        if i % 2 == 0:
            for start, end in segments:
                if start[0] <= end[0]:
                    path.append(start)
                    path.append(end)
                else:
                    path.append(end)
                    path.append(start)
        else:
            for start, end in reversed(segments):
                if start[0] >= end[0]:
                    path.append(start)
                    path.append(end)
                else:
                    path.append(end)
                    path.append(start)

    return path


def generate_mow_path(
    vertices_xy: list[tuple[float, float]],
    width: float,
    overlap: float = 0.0,
    heading: float | None = None,
) -> list[tuple[float, float]]:
    """Generate a boustrophedon mowing path within the given polygon.

    Args:
        vertices_xy: Polygon vertices in XY meters.
        width: Strip width in meters.
        overlap: Overlap percentage (0-100).
        heading: Mowing heading in degrees (0=north, 90=east). Auto-detected if None.

    Returns:
        Ordered list of (x, y) waypoints in the original coordinate frame.
    """
    from nav_planning.polygon import auto_heading as detect_heading

    if heading is None:
        heading = detect_heading(vertices_xy)

    spacing = width * (1.0 - overlap / 100.0)
    if spacing <= 0:
        raise ValueError(f"Overlap {overlap}% with width {width}m gives non-positive spacing")

    # Centroid for rotation reference
    n = len(vertices_xy)
    cx = sum(v[0] for v in vertices_xy) / n
    cy = sum(v[1] for v in vertices_xy) / n

    # Rotate polygon so mowing direction aligns with X axis
    rotated = rotate_polygon(vertices_xy, heading)
    poly = Polygon(rotated)

    x_min, y_min, x_max, y_max = poly.bounds
    y_vals = sweep_lines(y_min, y_max, spacing)

    path_rotated = clip_and_zigzag(poly, y_vals, x_min, x_max)

    # Unrotate waypoints back to original coordinate frame
    path = _unrotate_points(path_rotated, heading, cx, cy)
    return path
