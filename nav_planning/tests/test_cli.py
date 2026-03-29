"""CLI integration tests."""

import pytest
from typer.testing import CliRunner
from nav_planning.cli import app
from nav_planning.waypoints import read_waypoints

runner = CliRunner()


@pytest.fixture
def sample_poly(tmp_path):
    """A simple rectangular polygon file."""
    p = tmp_path / "test.poly"
    p.write_text(
        "40.0000 -80.0000\n"
        "40.0000 -79.9990\n"
        "40.0005 -79.9990\n"
        "40.0005 -80.0000\n"
    )
    return p


class TestMowCommand:
    def test_minimal_invocation(self, sample_poly, tmp_path):
        """nav-plan mow field.poly --width 0.53 should produce a .waypoints file."""
        result = runner.invoke(app, [str(sample_poly), "--width", "0.53"])
        assert result.exit_code == 0
        out_path = str(sample_poly).replace(".poly", ".waypoints")
        wps = read_waypoints(out_path)
        assert len(wps) > 0

    def test_full_options(self, sample_poly, tmp_path):
        out = tmp_path / "mission.waypoints"
        result = runner.invoke(
            app,
            [
                str(sample_poly),
                "--width", "1.0",
                "--overlap", "10",
                "--heading", "45",
                "-o", str(out),
            ],
        )
        assert result.exit_code == 0
        assert out.exists()
        wps = read_waypoints(str(out))
        assert len(wps) > 0

    def test_missing_width(self, sample_poly):
        result = runner.invoke(app, [str(sample_poly)])
        assert result.exit_code != 0

    def test_output_contains_info(self, sample_poly, tmp_path):
        result = runner.invoke(app, [str(sample_poly), "--width", "1.0"])
        assert "vertices" in result.output
        assert "Heading" in result.output
        assert "Waypoints" in result.output
