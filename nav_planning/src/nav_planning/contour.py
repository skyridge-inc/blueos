"""Contour-following parallel offset path generation."""

from __future__ import annotations

from shapely.geometry import LineString, Polygon, MultiLineString


INCHES_TO_METERS = 0.0254


def _determine_offset_sign(
    spine: LineString, polygon: Polygon
) -> float:
    """Determine offset sign that moves toward the polygon interior.

    Returns +1.0 (left offset) or -1.0 (right offset).
    """
    centroid = polygon.centroid
    try:
        left = spine.offset_curve(0.01)
        right = spine.offset_curve(-0.01)
    except Exception:
        return 1.0

    if left.is_empty and right.is_empty:
        return 1.0
    if left.is_empty:
        return -1.0
    if right.is_empty:
        return 1.0

    left_dist = left.distance(centroid)
    right_dist = right.distance(centroid)
    return 1.0 if left_dist < right_dist else -1.0


def generate_contour_paths(
    vertices_xy: list[tuple[float, float]],
    spine_xy: list[tuple[float, float]],
    width_inches: float,
) -> list[list[tuple[float, float]]]:
    """Generate contour-following mower paths as parallel offsets of the spine.

    Args:
        vertices_xy: Full polygon vertices in XY meters.
        spine_xy: Spine polyline in XY meters (from extract_spine).
        width_inches: Mower width in inches.

    Returns:
        List of paths, one per mower. Each path is a list of (x, y) waypoints.
    """
    width_m = width_inches * INCHES_TO_METERS
    if width_m <= 0:
        raise ValueError(f"Width must be positive, got {width_inches} inches")

    polygon = Polygon(vertices_xy)
    spine_line = LineString(spine_xy)
    sign = _determine_offset_sign(spine_line, polygon)

    paths: list[list[tuple[float, float]]] = []

    # Path 1: the spine itself, clipped to polygon
    clipped = polygon.intersection(spine_line)
    if not clipped.is_empty:
        paths.append(_extract_coords(clipped))

    # Subsequent paths: parallel offsets
    offset_num = 1
    while True:
        distance = offset_num * width_m * sign
        offset_line = spine_line.offset_curve(distance)

        if offset_line.is_empty:
            break

        # Clip to polygon boundary
        clipped = polygon.intersection(offset_line)
        if clipped.is_empty:
            break

        coords = _extract_coords(clipped)
        if len(coords) < 2:
            break

        paths.append(coords)
        offset_num += 1

    return paths


def _extract_coords(
    geom: LineString | MultiLineString,
) -> list[tuple[float, float]]:
    """Extract coordinate tuples from a Shapely line geometry."""
    if isinstance(geom, LineString):
        return [(x, y) for x, y in geom.coords]
    elif isinstance(geom, MultiLineString):
        coords: list[tuple[float, float]] = []
        for line in geom.geoms:
            coords.extend((x, y) for x, y in line.coords)
        return coords
    return []
