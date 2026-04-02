"""Tests for KML Track and Tour visualization."""

import xml.etree.ElementTree as ET
import pytest
from nav_planning.kml import generate_kml_track, generate_kml_tour, KML_NS, GX_NS

SINGLE_PATH = [(40.0, -80.0), (40.001, -80.0), (40.001, -79.999)]

MULTI_PATHS = [
    [(40.0, -80.0), (40.001, -80.0)],
    [(40.0001, -80.0), (40.0011, -80.0)],
]


def _parse(path):
    return ET.parse(path).getroot()


class TestGenerateKmlTrack:
    def test_creates_file(self, tmp_path):
        out = tmp_path / "track.kml"
        generate_kml_track([SINGLE_PATH], str(out))
        assert out.exists()

    def test_valid_xml(self, tmp_path):
        out = tmp_path / "track.kml"
        generate_kml_track([SINGLE_PATH], str(out))
        root = _parse(str(out))
        assert root.tag == f"{{{KML_NS}}}kml"

    def test_contains_gx_track(self, tmp_path):
        out = tmp_path / "track.kml"
        generate_kml_track([SINGLE_PATH], str(out))
        root = _parse(str(out))
        tracks = root.findall(f".//{{{GX_NS}}}Track")
        assert len(tracks) == 1

    def test_contains_when_elements(self, tmp_path):
        out = tmp_path / "track.kml"
        generate_kml_track([SINGLE_PATH], str(out))
        content = out.read_text()
        when_count = content.count("<when>")
        assert when_count == len(SINGLE_PATH)

    def test_contains_gx_coord(self, tmp_path):
        out = tmp_path / "track.kml"
        generate_kml_track([SINGLE_PATH], str(out))
        root = _parse(str(out))
        coords = root.findall(f".//{{{GX_NS}}}coord")
        assert len(coords) == len(SINGLE_PATH)

    def test_coord_lon_lat_order(self, tmp_path):
        """gx:coord should be 'lon lat alt' — lon comes first."""
        path = [(40.123, -80.456)]
        out = tmp_path / "track.kml"
        generate_kml_track([path], str(out))
        root = _parse(str(out))
        coord = root.find(f".//{{{GX_NS}}}coord")
        parts = coord.text.strip().split()
        assert parts[0] == "-80.456"  # lon first
        assert parts[1] == "40.123"   # lat second

    def test_multi_mower_placemarks(self, tmp_path):
        out = tmp_path / "track.kml"
        generate_kml_track(MULTI_PATHS, str(out))
        root = _parse(str(out))
        tracks = root.findall(f".//{{{GX_NS}}}Track")
        assert len(tracks) == 2

    def test_distinct_styles(self, tmp_path):
        out = tmp_path / "track.kml"
        generate_kml_track(MULTI_PATHS, str(out))
        root = _parse(str(out))
        styles = root.findall(f".//{{{KML_NS}}}Style")
        style_ids = [s.get("id") for s in styles]
        assert len(set(style_ids)) == 2

    def test_timestamps_increase(self, tmp_path):
        out = tmp_path / "track.kml"
        generate_kml_track([SINGLE_PATH], str(out))
        content = out.read_text()
        import re
        whens = re.findall(r"<when>(.*?)</when>", content)
        # Timestamps should be chronologically ordered
        assert whens == sorted(whens)
        # Non-trivial path should have distinct timestamps
        assert len(set(whens)) == len(whens)

    def test_empty_paths_raises(self):
        with pytest.raises(ValueError, match="No mower paths"):
            generate_kml_track([], "/dev/null")


class TestGenerateKmlTour:
    def test_creates_file(self, tmp_path):
        out = tmp_path / "tour.kml"
        generate_kml_tour([SINGLE_PATH], str(out))
        assert out.exists()

    def test_valid_xml(self, tmp_path):
        out = tmp_path / "tour.kml"
        generate_kml_tour([SINGLE_PATH], str(out))
        root = _parse(str(out))
        assert root.tag == f"{{{KML_NS}}}kml"

    def test_contains_gx_tour(self, tmp_path):
        out = tmp_path / "tour.kml"
        generate_kml_tour([SINGLE_PATH], str(out))
        root = _parse(str(out))
        tours = root.findall(f".//{{{GX_NS}}}Tour")
        assert len(tours) == 1

    def test_contains_flyto(self, tmp_path):
        out = tmp_path / "tour.kml"
        generate_kml_tour([SINGLE_PATH], str(out))
        root = _parse(str(out))
        flytos = root.findall(f".//{{{GX_NS}}}FlyTo")
        assert len(flytos) == len(SINGLE_PATH)

    def test_contains_lookat(self, tmp_path):
        out = tmp_path / "tour.kml"
        generate_kml_tour([SINGLE_PATH], str(out), altitude_m=30.0, tilt_deg=60.0)
        root = _parse(str(out))
        look_at = root.find(f".//{{{KML_NS}}}LookAt")
        assert look_at is not None
        assert look_at.find(f"{{{KML_NS}}}altitude").text == "30.0"
        assert look_at.find(f"{{{KML_NS}}}tilt").text == "60.0"

    def test_static_linestrings(self, tmp_path):
        out = tmp_path / "tour.kml"
        generate_kml_tour(MULTI_PATHS, str(out))
        root = _parse(str(out))
        lines = root.findall(f".//{{{KML_NS}}}LineString")
        assert len(lines) == 2

    def test_flyto_smooth_mode(self, tmp_path):
        out = tmp_path / "tour.kml"
        generate_kml_tour([SINGLE_PATH], str(out))
        root = _parse(str(out))
        mode = root.find(f".//{{{GX_NS}}}flyToMode")
        assert mode.text == "smooth"

    def test_empty_paths_raises(self):
        with pytest.raises(ValueError, match="No mower paths"):
            generate_kml_tour([], "/dev/null")
