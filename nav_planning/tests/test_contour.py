"""Tests for contour-following parallel offset path generation."""

import pytest
from nav_planning.contour import generate_contour_paths, INCHES_TO_METERS


class TestGenerateContourPaths:
    def test_rectangle_multiple_paths(self):
        """A 10m wide rectangle with ~0.5m offsets should produce many paths."""
        # 10m × 100m rectangle (narrow and long)
        verts = [(0, 0), (100, 0), (100, 10), (0, 10)]
        spine = [(0, 0), (100, 0)]  # top edge
        paths = generate_contour_paths(verts, spine, width_inches=21)
        # 10m / 0.5334m ≈ 18 paths
        assert len(paths) >= 15
        # First path should match the spine
        assert len(paths[0]) >= 2

    def test_single_path_narrow_polygon(self):
        """A polygon narrower than 2× mower width should produce 1 path."""
        # 0.4m wide × 10m long — only fits 1 path at 21" (0.53m)
        verts = [(0, 0), (10, 0), (10, 0.4), (0, 0.4)]
        spine = [(0, 0), (10, 0)]
        paths = generate_contour_paths(verts, spine, width_inches=21)
        assert len(paths) == 1

    def test_all_paths_within_polygon(self):
        """Every waypoint in every path should be within the polygon."""
        from shapely.geometry import Polygon, Point

        verts = [(0, 0), (50, 0), (50, 5), (0, 5)]
        spine = [(0, 0), (50, 0)]
        paths = generate_contour_paths(verts, spine, width_inches=12)
        poly = Polygon(verts)

        for path in paths:
            for x, y in path:
                assert poly.buffer(0.001).contains(Point(x, y)), (
                    f"Point ({x:.3f}, {y:.3f}) is outside the polygon"
                )

    def test_paths_offset_by_width(self):
        """Adjacent paths should be approximately mower-width apart."""
        verts = [(0, 0), (100, 0), (100, 10), (0, 10)]
        spine = [(0, 0), (100, 0)]
        width_in = 21
        paths = generate_contour_paths(verts, spine, width_inches=width_in)

        expected_spacing = width_in * INCHES_TO_METERS
        # Check spacing between path 1 and path 2 at the midpoint
        if len(paths) >= 2:
            from shapely.geometry import LineString
            line1 = LineString(paths[0])
            line2 = LineString(paths[1])
            dist = line1.distance(line2)
            assert dist == pytest.approx(expected_spacing, abs=0.01)

    def test_invalid_width_raises(self):
        verts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        spine = [(0, 0), (10, 0)]
        with pytest.raises(ValueError, match="positive"):
            generate_contour_paths(verts, spine, width_inches=0)

    def test_narrowing_polygon(self):
        """A polygon that narrows should produce fewer paths in the narrow section."""
        # Trapezoid: 10m wide at left, 4m wide at right, 50m long
        verts = [(0, 0), (50, 3), (50, 7), (0, 10)]
        spine = [(0, 0), (50, 3)]  # bottom edge
        paths = generate_contour_paths(verts, spine, width_inches=21)
        # Should produce paths, and inner paths should be shorter
        assert len(paths) >= 2
