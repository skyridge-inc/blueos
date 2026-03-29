"""Tests for polygon parsing and coordinate projection."""

import math
import pytest
from nav_planning.polygon import parse_poly_file, to_xy, to_latlon, auto_heading


@pytest.fixture
def simple_poly(tmp_path):
    """A simple square polygon file."""
    p = tmp_path / "square.poly"
    p.write_text(
        "40.0 -80.0\n"
        "40.0 -79.999\n"
        "40.001 -79.999\n"
        "40.001 -80.0\n"
    )
    return str(p)


@pytest.fixture
def poly_with_comments(tmp_path):
    """Polygon file with comments and blank lines."""
    p = tmp_path / "commented.poly"
    p.write_text(
        "# This is a boundary file\n"
        "\n"
        "40.0 -80.0\n"
        "# Another comment\n"
        "40.0 -79.999\n"
        "\n"
        "40.001 -79.999\n"
        "40.001 -80.0\n"
    )
    return str(p)


class TestParsePolyFile:
    def test_valid_polygon(self, simple_poly):
        vertices = parse_poly_file(simple_poly)
        assert len(vertices) == 4
        assert vertices[0] == (40.0, -80.0)
        assert vertices[3] == (40.001, -80.0)

    def test_comments_and_blanks(self, poly_with_comments):
        vertices = parse_poly_file(poly_with_comments)
        assert len(vertices) == 4

    def test_insufficient_vertices(self, tmp_path):
        p = tmp_path / "short.poly"
        p.write_text("40.0 -80.0\n40.0 -79.999\n")
        with pytest.raises(ValueError, match="at least 3 vertices"):
            parse_poly_file(str(p))

    def test_malformed_line(self, tmp_path):
        p = tmp_path / "bad.poly"
        p.write_text("40.0 -80.0\nbadline\n40.001 -80.0\n")
        with pytest.raises(ValueError, match="Malformed line"):
            parse_poly_file(str(p))


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


class TestAutoHeading:
    def test_east_west_rectangle(self):
        """A rectangle wider than tall should give heading ~90 (east-west)."""
        # 10m wide (X), 5m tall (Y) rectangle
        xy = [(0, 0), (10, 0), (10, 5), (0, 5)]
        heading = auto_heading(xy)
        assert abs(heading - 90.0) < 0.1

    def test_north_south_rectangle(self):
        """A rectangle taller than wide should give heading ~0 (north-south)."""
        xy = [(0, 0), (5, 0), (5, 10), (0, 10)]
        heading = auto_heading(xy)
        assert heading < 1.0 or heading > 179.0  # ~0 or ~180, normalized to [0,180)
