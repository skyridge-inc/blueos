"""Tests for mow path visualization."""

import pytest

from mower_provisioner.mission_planning import generate_visualization_html


SINGLE_PATH = [(40.0, -80.0), (40.001, -80.0), (40.001, -79.999)]

MULTI_PATHS = [
    [(40.0, -80.0), (40.001, -80.0)],
    [(40.0001, -80.0), (40.0011, -80.0)],
]


class TestGenerateVisualizationHtml:
    def test_creates_html_file(self, tmp_path):
        out = tmp_path / "viz.html"
        generate_visualization_html([SINGLE_PATH], str(out))
        assert out.exists()

    def test_html_contains_leaflet(self, tmp_path):
        out = tmp_path / "viz.html"
        generate_visualization_html([SINGLE_PATH], str(out))
        content = out.read_text()
        assert "leaflet" in content.lower()
        assert "L.map" in content

    def test_html_contains_coordinates(self, tmp_path):
        out = tmp_path / "viz.html"
        generate_visualization_html([SINGLE_PATH], str(out))
        content = out.read_text()
        assert "40.0" in content
        assert "-80.0" in content

    def test_multi_mower_paths(self, tmp_path):
        out = tmp_path / "viz.html"
        generate_visualization_html(MULTI_PATHS, str(out))
        content = out.read_text()
        assert "var numMowers = 2" in content

    def test_correct_number_of_path_arrays(self, tmp_path):
        paths = [SINGLE_PATH, SINGLE_PATH, SINGLE_PATH]
        out = tmp_path / "viz.html"
        generate_visualization_html(paths, str(out))
        content = out.read_text()
        assert "var numMowers = 3" in content

    def test_empty_paths_raises(self, tmp_path):
        with pytest.raises(ValueError, match="No mower paths"):
            generate_visualization_html([], str(tmp_path / "x.html"))

    def test_has_play_pause_controls(self, tmp_path):
        out = tmp_path / "viz.html"
        generate_visualization_html([SINGLE_PATH], str(out))
        content = out.read_text()
        assert "playBtn" in content
        assert "togglePlay" in content

    def test_has_speed_control(self, tmp_path):
        out = tmp_path / "viz.html"
        generate_visualization_html([SINGLE_PATH], str(out))
        content = out.read_text()
        assert "speedSlider" in content

    def test_has_mower_toggles(self, tmp_path):
        out = tmp_path / "viz.html"
        generate_visualization_html(MULTI_PATHS, str(out))
        content = out.read_text()
        assert "Mower 1" in content or "mower-toggle" in content
