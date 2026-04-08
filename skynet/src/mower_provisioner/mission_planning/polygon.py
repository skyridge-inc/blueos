"""Polygon file parsing and coordinate projection."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

KML_NS = "http://www.opengis.net/kml/2.2"


def parse_kml_file(path: str) -> list[tuple[float, float]]:
    """Parse a KML file and extract the first polygon as (lat, lon) tuples.

    Validates that the polygon is completely closed (first coordinate equals
    last coordinate). The closing duplicate is stripped from the returned list
    since the rest of the codebase treats polygons as implicitly closed.

    KML coordinates are lon,lat,alt — this function swaps to lat,lon.
    """
    tree = ET.parse(path)
    root = tree.getroot()

    # Handle KML namespace — try with namespace first, then without
    coords_text = None
    for ns in [f"{{{KML_NS}}}", ""]:
        polygon = root.find(f".//{ns}Polygon")
        if polygon is not None:
            coords_el = polygon.find(
                f"{ns}outerBoundaryIs/{ns}LinearRing/{ns}coordinates"
            )
            if coords_el is not None and coords_el.text:
                coords_text = coords_el.text.strip()
                break

    if coords_text is None:
        raise ValueError("No <Polygon> with coordinates found in KML file")

    # Parse lon,lat,alt triples → (lat, lon) tuples
    vertices: list[tuple[float, float]] = []
    for token in coords_text.split():
        parts = token.split(",")
        if len(parts) < 2:
            raise ValueError(f"Malformed KML coordinate: {token!r}")
        lon, lat = float(parts[0]), float(parts[1])
        vertices.append((lat, lon))

    if len(vertices) < 4:
        raise ValueError(
            f"KML polygon requires at least 3 vertices plus closing point, "
            f"got {len(vertices)}"
        )

    # Validate closed polygon
    first, last = vertices[0], vertices[-1]
    if abs(first[0] - last[0]) > 1e-9 or abs(first[1] - last[1]) > 1e-9:
        raise ValueError(
            "KML polygon is not closed: first and last coordinates must match"
        )

    # Strip closing duplicate — codebase treats polygons as implicitly closed
    vertices = vertices[:-1]

    if len(vertices) < 3:
        raise ValueError(
            f"Polygon requires at least 3 unique vertices, got {len(vertices)}"
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


def extract_spine(vertices_xy: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Extract a spine polyline by walking vertices until a turn of >= 90 degrees.

    Starts at vertex 0 and follows subsequent vertices. At each vertex, the
    absolute turn angle between the incoming and outgoing edges is computed.
    The spine ends at the first vertex where the turn is >= 90 degrees.

    Returns at least the first two vertices (the first edge).
    """
    n = len(vertices_xy)
    if n < 2:
        raise ValueError("Need at least 2 vertices to extract a spine")

    spine = [vertices_xy[0], vertices_xy[1]]

    for i in range(1, n - 1):
        prev = vertices_xy[i - 1]
        curr = vertices_xy[i]
        nxt = vertices_xy[i + 1]

        dx1 = curr[0] - prev[0]
        dy1 = curr[1] - prev[1]
        dx2 = nxt[0] - curr[0]
        dy2 = nxt[1] - curr[1]

        angle1 = math.atan2(dy1, dx1)
        angle2 = math.atan2(dy2, dx2)
        turn = math.degrees(angle2 - angle1)
        # Normalize to [-180, 180]
        turn = (turn + 180) % 360 - 180

        if abs(turn) >= 90.0:
            break
        spine.append(nxt)

    return spine


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
