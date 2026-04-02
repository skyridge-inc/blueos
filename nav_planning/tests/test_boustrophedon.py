"""Tests for boustrophedon coverage path generation."""

import pytest
from nav_planning.boustrophedon import (
    rotate_polygon,
    sweep_lines,
    clip_and_zigzag,
    generate_mow_path,
)
from shapely.geometry import Polygon


class TestRotatePolygon:
    def test_identity_rotation(self):
        """90-degree heading should map +X to +X (heading=90 means east)."""
        verts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        rotated = rotate_polygon(verts, 90.0)
        # With heading=90, the sweep direction is already aligned with X
        # Points should remain roughly in the same positions
        xs = [p[0] for p in rotated]
        ys = [p[1] for p in rotated]
        assert max(xs) - min(xs) == pytest.approx(10.0, abs=0.01)
        assert max(ys) - min(ys) == pytest.approx(5.0, abs=0.01)


class TestSweepLines:
    def test_basic_sweep(self):
        lines = sweep_lines(0.0, 10.0, 2.0)
        assert lines == pytest.approx([1.0, 3.0, 5.0, 7.0, 9.0])

    def test_single_strip(self):
        lines = sweep_lines(0.0, 1.0, 2.0)
        assert len(lines) == 0  # spacing/2 = 1.0, not < 1.0


class TestClipAndZigzag:
    def test_simple_rectangle(self):
        poly = Polygon([(0, 0), (10, 0), (10, 5), (0, 5)])
        y_vals = [1.0, 2.0, 3.0, 4.0]
        path = clip_and_zigzag(poly, y_vals, 0.0, 10.0)
        # Should have 2 points per sweep line = 8 waypoints
        assert len(path) == 8
        # First line goes left-to-right
        assert path[0][0] < path[1][0]
        # Second line goes right-to-left
        assert path[2][0] > path[3][0]


class TestGenerateMowPath:
    def test_simple_rectangle(self):
        """10m x 5m rectangle with 1m strips should give 5 strips."""
        # Rectangle aligned east-west (longest edge along X)
        verts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        path = generate_mow_path(verts, width=1.0, overlap=0.0, heading=90.0)
        # 5 strips, 2 waypoints each = 10 waypoints
        assert len(path) == 10

    def test_overlap_increases_strips(self):
        """10% overlap should produce more strips than 0%."""
        verts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        path_no_overlap = generate_mow_path(verts, width=1.0, overlap=0.0, heading=90.0)
        path_with_overlap = generate_mow_path(verts, width=1.0, overlap=10.0, heading=90.0)
        assert len(path_with_overlap) > len(path_no_overlap)

    def test_concave_l_shape(self):
        """An L-shaped polygon should produce multiple segments on some sweep lines."""
        # L-shape: wider at bottom, narrow at top
        verts = [
            (0, 0), (10, 0), (10, 3),
            (5, 3), (5, 6), (0, 6),
        ]
        path = generate_mow_path(verts, width=1.0, overlap=0.0, heading=90.0)
        # Should have waypoints — exact count depends on geometry
        assert len(path) >= 8

    def test_auto_heading(self):
        """With no heading specified, auto-detect from longest edge."""
        verts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        path = generate_mow_path(verts, width=1.0, overlap=0.0)
        # Should still produce valid waypoints
        assert len(path) >= 8

    def test_invalid_overlap(self):
        verts = [(0, 0), (10, 0), (10, 5), (0, 5)]
        with pytest.raises(ValueError, match="non-positive spacing"):
            generate_mow_path(verts, width=1.0, overlap=100.0, heading=90.0)


class TestSplitPathForMowers:
    def test_one_strip_per_mower(self):
        """5-strip path should split into 5 mower segments of 2 points each."""
        from nav_planning.boustrophedon import split_path_for_mowers

        # Simulate 5 strips: 10 waypoints (2 per strip)
        path = [(i, 0) for i in range(10)]
        segments = split_path_for_mowers(path)
        assert len(segments) == 5
        for seg in segments:
            assert len(seg) == 2

    def test_single_strip(self):
        """A single strip should produce one mower segment."""
        from nav_planning.boustrophedon import split_path_for_mowers

        path = [(0, 0), (10, 0)]
        segments = split_path_for_mowers(path)
        assert len(segments) == 1
        assert segments[0] == [(0, 0), (10, 0)]

    def test_empty_path(self):
        from nav_planning.boustrophedon import split_path_for_mowers

        assert split_path_for_mowers([]) == []
