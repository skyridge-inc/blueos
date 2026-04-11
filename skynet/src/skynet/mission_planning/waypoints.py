"""QGC WPL 110 waypoint file I/O."""

from __future__ import annotations

HEADER = "QGC WPL 110"


def write_waypoints(
    path: str,
    waypoints: list[tuple[float, float]],
    home: tuple[float, float] | None = None,
) -> None:
    """Write waypoints to a QGC WPL 110 file.

    Args:
        path: Output file path.
        waypoints: List of (lat, lon) waypoints.
        home: Home position (lat, lon). Defaults to first waypoint.
    """
    if not waypoints:
        raise ValueError("No waypoints to write")

    if home is None:
        home = waypoints[0]

    with open(path, "w") as f:
        f.write(f"{HEADER}\n")
        # Home waypoint (index 0, current_wp=1)
        f.write(f"0\t1\t0\t16\t0\t0\t0\t0\t{home[0]:.8f}\t{home[1]:.8f}\t0.000000\t1\n")
        # Mission waypoints
        for i, (lat, lon) in enumerate(waypoints, start=1):
            f.write(f"{i}\t0\t3\t16\t0\t0\t0\t0\t{lat:.8f}\t{lon:.8f}\t0.000000\t1\n")


def read_waypoints(path: str) -> list[tuple[float, float]]:
    """Parse a QGC WPL 110 file, returning waypoints (excluding home) as (lat, lon) tuples."""
    waypoints: list[tuple[float, float]] = []
    with open(path) as f:
        header = f.readline().strip()
        if header != HEADER:
            raise ValueError(f"Expected '{HEADER}' header, got: {header!r}")
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split("\t")
            if len(parts) < 12:
                continue
            index = int(parts[0])
            if index == 0:
                continue  # Skip home
            lat = float(parts[8])
            lon = float(parts[9])
            waypoints.append((lat, lon))
    return waypoints
