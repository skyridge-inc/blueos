"""End-to-end tests for the `nav plan` CLI command.

These exercise the full pipeline (KML → contour → waypoint files +
optional HTML/KML visualizations) without opening any MAVLink or HTTP
connection. The polygon used here is a 10m × 100m rectangle in lat/lon
near (40, -80), which fits roughly 18 paths at 21" mower width.
"""

import xml.etree.ElementTree as ET

import pytest
from typer.testing import CliRunner

from skynet.cli import app

runner = CliRunner()


# 10m × 100m rectangle, closed: bottom-left → bottom-right → top-right → top-left → close
# 0.0009 degrees lon @ 40N ≈ 76.9m, 0.00009 degrees lat ≈ 10m
RECT_KML = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<kml xmlns="http://www.opengis.net/kml/2.2">\n'
    "<Document><Placemark><Polygon><outerBoundaryIs><LinearRing>\n"
    "<coordinates>"
    "-80.0,40.0,0 -79.999,40.0,0 -79.999,40.00009,0 -80.0,40.00009,0 -80.0,40.0,0"
    "</coordinates>\n"
    "</LinearRing></outerBoundaryIs></Polygon></Placemark></Document>\n"
    "</kml>\n"
)


@pytest.fixture
def field_kml(tmp_path):
    p = tmp_path / "field.kml"
    p.write_text(RECT_KML)
    return p


class TestNavPlanCommand:
    def test_minimal_invocation_writes_waypoints(self, field_kml):
        result = runner.invoke(app, ["nav", "plan", str(field_kml), "--width", "21"])
        assert result.exit_code == 0, result.stdout + (result.stderr or "")
        # Either single .waypoints file or per-mower files exist
        base = field_kml.with_suffix("")
        single = base.with_suffix(".waypoints")
        per_mower = list(field_kml.parent.glob("field_mower*.waypoints"))
        assert single.exists() or per_mower
        # Spec requires the command to print mower count
        assert "Mowers required" in result.stdout

    def test_multi_mower_output_naming(self, field_kml):
        # 10m wide, 21" (~0.53m) → ~18 paths
        result = runner.invoke(app, ["nav", "plan", str(field_kml), "--width", "21"])
        assert result.exit_code == 0
        per_mower = sorted(field_kml.parent.glob("field_mower*.waypoints"))
        assert len(per_mower) >= 2
        names = [p.name for p in per_mower]
        assert "field_mower1.waypoints" in names

    def test_custom_output_strips_extension(self, field_kml, tmp_path):
        custom = tmp_path / "mission.waypoints"
        result = runner.invoke(
            app,
            ["nav", "plan", str(field_kml), "--width", "21", "-o", str(custom)],
        )
        assert result.exit_code == 0
        # Files should be written under "mission" base, not "mission.waypoints"
        produced = list(tmp_path.glob("mission*.waypoints"))
        assert produced
        # No file should be literally named with double extension
        assert not (tmp_path / "mission.waypoints.waypoints").exists()

    def test_missing_width_errors(self, field_kml):
        result = runner.invoke(app, ["nav", "plan", str(field_kml)])
        assert result.exit_code != 0

    def test_visualize_flag_writes_html(self, field_kml):
        result = runner.invoke(
            app, ["nav", "plan", str(field_kml), "--width", "21", "--visualize"]
        )
        assert result.exit_code == 0
        viz = field_kml.parent / "field.html"
        assert viz.exists()
        assert "leaflet" in viz.read_text().lower()

    def test_kml_track_flag_writes_track_file(self, field_kml):
        result = runner.invoke(
            app, ["nav", "plan", str(field_kml), "--width", "21", "--kml-track"]
        )
        assert result.exit_code == 0
        track = field_kml.parent / "field_track.kml"
        assert track.exists()
        # Quick sanity check: file is parseable XML containing gx:Track
        root = ET.parse(track).getroot()
        gx_ns = "http://www.google.com/kml/ext/2.2"
        assert root.findall(f".//{{{gx_ns}}}Track")

    def test_kml_tour_flag_writes_tour_file(self, field_kml):
        result = runner.invoke(
            app, ["nav", "plan", str(field_kml), "--width", "21", "--kml-tour"]
        )
        assert result.exit_code == 0
        tour = field_kml.parent / "field_tour.kml"
        assert tour.exists()
        gx_ns = "http://www.google.com/kml/ext/2.2"
        root = ET.parse(tour).getroot()
        assert root.findall(f".//{{{gx_ns}}}Tour")

    def test_all_visualization_flags_together(self, field_kml):
        result = runner.invoke(
            app,
            [
                "nav",
                "plan",
                str(field_kml),
                "--width",
                "21",
                "--visualize",
                "--kml-track",
                "--kml-tour",
            ],
        )
        assert result.exit_code == 0
        d = field_kml.parent
        assert (d / "field.html").exists()
        assert (d / "field_track.kml").exists()
        assert (d / "field_tour.kml").exists()
