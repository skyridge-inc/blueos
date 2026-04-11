"""Mowing mission planning: KML polygon → contour-following waypoint files.

This subpackage is the in-tree replacement for the previously separate
``nav_planning`` project. It depends only on ``shapely`` for geometric
operations — no MAVLink or HTTP transport. The ``nav-plan`` CLI command
in ``mower_provisioner.cli`` composes these modules.
"""

from .contour import INCHES_TO_METERS, generate_contour_paths
from .kml import generate_kml_track, generate_kml_tour
from .polygon import auto_heading, extract_spine, parse_kml_file, to_latlon, to_xy
from .visualize import generate_visualization_html
from .waypoints import read_waypoints, write_waypoints

__all__ = [
    "INCHES_TO_METERS",
    "auto_heading",
    "extract_spine",
    "generate_contour_paths",
    "generate_kml_track",
    "generate_kml_tour",
    "generate_visualization_html",
    "parse_kml_file",
    "read_waypoints",
    "to_latlon",
    "to_xy",
    "write_waypoints",
]
