"""CLI integration tests."""

import glob
import os
import pytest
from typer.testing import CliRunner
from nav_planning.cli import app

runner = CliRunner()


def _make_kml(coords_text: str) -> str:
    """Build a minimal valid KML string."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
        "  <Document><Placemark><Polygon><outerBoundaryIs><LinearRing>\n"
        f"    <coordinates>{coords_text}</coordinates>\n"
        "  </LinearRing></outerBoundaryIs></Polygon></Placemark></Document>\n"
        "</kml>\n"
    )


# Closed rectangle ~83m x 55m
RECT_COORDS = (
    "-80.0000,40.0000,0 -79.9990,40.0000,0 "
    "-79.9990,40.0005,0 -80.0000,40.0005,0 "
    "-80.0000,40.0000,0"
)


@pytest.fixture
def sample_kml(tmp_path):
    """A rectangular KML polygon file."""
    p = tmp_path / "test.kml"
    p.write_text(_make_kml(RECT_COORDS))
    return p


class TestMowCommand:
    def test_minimal_invocation(self, sample_kml):
        """nav-plan field.kml --width 21 should produce waypoint files."""
        result = runner.invoke(app, [str(sample_kml), "--width", "21"])
        assert result.exit_code == 0

    def test_width_in_inches(self, sample_kml):
        """Width should be interpreted as inches and displayed."""
        result = runner.invoke(app, [str(sample_kml), "--width", "42"])
        assert result.exit_code == 0
        assert '42.0"' in result.output

    def test_missing_width(self, sample_kml):
        result = runner.invoke(app, [str(sample_kml)])
        assert result.exit_code != 0

    def test_output_contains_info(self, sample_kml):
        result = runner.invoke(app, [str(sample_kml), "--width", "21"])
        assert "vertices" in result.output
        assert "Spine" in result.output
        assert "Mowers required" in result.output

    def test_multi_mower_output(self, sample_kml):
        """Multiple offset paths should produce multiple _mowerN.waypoints files."""
        result = runner.invoke(app, [str(sample_kml), "--width", "21"])
        assert result.exit_code == 0
        stem = str(sample_kml).replace(".kml", "")
        mower_files = glob.glob(f"{stem}_mower*.waypoints")
        assert len(mower_files) >= 2

    def test_custom_output_path(self, sample_kml, tmp_path):
        out = tmp_path / "mission.waypoints"
        result = runner.invoke(
            app, [str(sample_kml), "--width", "21", "-o", str(out)]
        )
        assert result.exit_code == 0

    def test_visualize_flag_produces_html(self, sample_kml):
        """--visualize should produce an HTML file alongside waypoints."""
        result = runner.invoke(app, [str(sample_kml), "--width", "21", "--visualize"])
        assert result.exit_code == 0
        stem = str(sample_kml).replace(".kml", "")
        assert os.path.exists(f"{stem}.html")
        assert "Visualization" in result.output

    def test_no_visualize_no_html(self, sample_kml):
        """Without --visualize, no HTML file should be produced."""
        result = runner.invoke(app, [str(sample_kml), "--width", "21"])
        assert result.exit_code == 0
        stem = str(sample_kml).replace(".kml", "")
        assert not os.path.exists(f"{stem}.html")

    def test_kml_track_flag_produces_kml(self, sample_kml):
        """--kml-track should produce a _track.kml file."""
        result = runner.invoke(app, [str(sample_kml), "--width", "21", "--kml-track"])
        assert result.exit_code == 0
        stem = str(sample_kml).replace(".kml", "")
        assert os.path.exists(f"{stem}_track.kml")
        assert "KML Track" in result.output

    def test_no_kml_track_no_file(self, sample_kml):
        """Without --kml-track, no _track.kml file should be produced."""
        result = runner.invoke(app, [str(sample_kml), "--width", "21"])
        assert result.exit_code == 0
        stem = str(sample_kml).replace(".kml", "")
        assert not os.path.exists(f"{stem}_track.kml")

    def test_kml_tour_flag_produces_kml(self, sample_kml):
        """--kml-tour should produce a _tour.kml file."""
        result = runner.invoke(app, [str(sample_kml), "--width", "21", "--kml-tour"])
        assert result.exit_code == 0
        stem = str(sample_kml).replace(".kml", "")
        assert os.path.exists(f"{stem}_tour.kml")
        assert "KML Tour" in result.output

    def test_no_kml_tour_no_file(self, sample_kml):
        """Without --kml-tour, no _tour.kml file should be produced."""
        result = runner.invoke(app, [str(sample_kml), "--width", "21"])
        assert result.exit_code == 0
        stem = str(sample_kml).replace(".kml", "")
        assert not os.path.exists(f"{stem}_tour.kml")

    def test_unclosed_polygon_error(self, tmp_path):
        """An unclosed KML polygon should produce an error."""
        unclosed = (
            "-80.0,40.0,0 -79.999,40.0,0 "
            "-79.999,40.001,0 -80.0,40.001,0"
        )
        p = tmp_path / "unclosed.kml"
        p.write_text(_make_kml(unclosed))
        result = runner.invoke(app, [str(p), "--width", "21"])
        assert result.exit_code != 0
