"""Tests for KML parsing, coordinate projection, and spine extraction."""

import math
import pytest
from nav_planning.polygon import parse_kml_file, to_xy, to_latlon, extract_spine


def _make_kml(coords_text: str) -> str:
    """Build a minimal valid KML string with the given coordinates text."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "  <Document><Placemark><Polygon><outerBoundaryIs><LinearRing>\n"
        f"    <coordinates>{coords_text}</coordinates>\n"
        "  </LinearRing></outerBoundaryIs></Polygon></Placemark></Document>\n"
        "</kml>\n"
    )


# Closed rectangle: lon,lat,alt — note KML is lon-first
RECT_COORDS = (
    "-80.0,40.0,0 -79.999,40.0,0 -79.999,40.001,0 -80.0,40.001,0 -80.0,40.0,0"
)


@pytest.fixture
def valid_kml(tmp_path):
    p = tmp_path / "rect.kml"
    p.write_text(_make_kml(RECT_COORDS))
    return str(p)


class TestParseKmlFile:
    def test_valid_kml(self, valid_kml):
        vertices = parse_kml_file(valid_kml)
        assert len(vertices) == 4
        # First vertex: lat=40.0, lon=-80.0 (swapped from KML lon,lat)
        assert vertices[0] == pytest.approx((40.0, -80.0))
        assert vertices[3] == pytest.approx((40.001, -80.0))

    def test_closed_polygon_validation(self, tmp_path):
        """Unclosed polygon must raise ValueError."""
        unclosed = (
            "-80.0,40.0,0 -79.999,40.0,0 -79.999,40.001,0 -80.0,40.001,0"
        )
        p = tmp_path / "unclosed.kml"
        p.write_text(_make_kml(unclosed))
        with pytest.raises(ValueError, match="not closed"):
            parse_kml_file(str(p))

    def test_strips_closing_coordinate(self, valid_kml):
        """Returned list should NOT include the closing duplicate."""
        vertices = parse_kml_file(valid_kml)
        # 5 coords in KML (closed ring), returned as 4 unique vertices
        assert len(vertices) == 4
        assert vertices[0] != vertices[-1] or len(vertices) == 4

    def test_no_polygon_in_kml(self, tmp_path):
        kml = (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
            "  <Document><Placemark><Point>"
            "<coordinates>-80.0,40.0,0</coordinates>"
            "</Point></Placemark></Document>\n"
            "</kml>\n"
        )
        p = tmp_path / "nopoint.kml"
        p.write_text(kml)
        with pytest.raises(ValueError, match="No <Polygon>"):
            parse_kml_file(str(p))

    def test_insufficient_vertices(self, tmp_path):
        """A polygon with only 2 unique vertices + close should fail."""
        coords = "-80.0,40.0,0 -79.999,40.0,0 -80.0,40.0,0"
        p = tmp_path / "short.kml"
        p.write_text(_make_kml(coords))
        with pytest.raises(ValueError, match="at least 3"):
            parse_kml_file(str(p))


class TestProjection:
    def test_round_trip(self):
        """Project to XY and back — should match within 0.001m at lawn scale."""
        vertices = [
            (40.0, -80.0),
            (40.0, -79.999),
            (40.001, -79.999),
            (40.001, -80.0),
        ]
        xy, origin = to_xy(vertices)
        result = to_latlon(xy, origin)
        for (lat1, lon1), (lat2, lon2) in zip(vertices, result):
            assert abs(lat1 - lat2) < 1e-9
            assert abs(lon1 - lon2) < 1e-9

    def test_xy_distances_reasonable(self):
        """0.001 degrees lat should be roughly 111 meters."""
        vertices = [(40.0, -80.0), (40.001, -80.0), (40.001, -80.001)]
        xy, _ = to_xy(vertices)
        dy = xy[1][1] - xy[0][1]
        assert 110 < dy < 113  # ~111.32m per 0.001 deg lat


class TestExtractSpine:
    def test_rectangle_stops_at_first_corner(self):
        """Rectangle: spine follows first edge, stops at 90-degree corner."""
        # 10m wide, 5m tall rectangle
        xy = [(0, 0), (10, 0), (10, 5), (0, 5)]
        spine = extract_spine(xy)
        # Turn at vertex 1 (10,0) is 90° → spine = [(0,0), (10,0)]
        assert len(spine) == 2
        assert spine[0] == (0, 0)
        assert spine[1] == (10, 0)

    def test_corridor_follows_gentle_curves(self):
        """Multi-vertex corridor with < 90° turns — spine follows all."""
        # A gentle zigzag corridor (all turns < 90°)
        xy = [(0, 0), (10, 1), (20, -1), (30, 0.5), (30, 10)]
        spine = extract_spine(xy)
        # Turn at (30, 0.5) to (30, 10) is ~90° — check we got at least 4 vertices
        assert len(spine) >= 4
        assert spine[0] == (0, 0)

    def test_all_sharp_turns(self):
        """If very first turn is >= 90°, spine is just the first edge."""
        # Triangle with sharp angles
        xy = [(0, 0), (10, 0), (5, 10)]
        spine = extract_spine(xy)
        # Turn at (10, 0) is ~117° → spine = first edge only
        assert len(spine) == 2

    def test_minimum_two_vertices(self):
        """Spine always has at least 2 vertices (the first edge)."""
        xy = [(0, 0), (5, 0), (5, 5)]
        spine = extract_spine(xy)
        assert len(spine) >= 2
