"""CLI entry point for nav-plan."""

from __future__ import annotations

import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from nav_planning.polygon import parse_poly_file, to_xy, to_latlon, auto_heading
from nav_planning.boustrophedon import generate_mow_path
from nav_planning.waypoints import write_waypoints

app = typer.Typer(help="Waypoint mission planning for Skyridge autonomous mower fleet.")
console = Console()


@app.command()
def mow(
    poly_file: str = typer.Argument(help="Path to ArduPilot .poly boundary file"),
    width: float = typer.Option(..., "--width", "-w", help="Strip width in meters"),
    overlap: float = typer.Option(0.0, "--overlap", help="Overlap percentage (0-100)"),
    heading: Optional[float] = typer.Option(
        None, "--heading", help="Mowing heading in degrees (auto-detected if omitted)"
    ),
    output: Optional[str] = typer.Option(
        None, "-o", "--output", help="Output .waypoints file path"
    ),
) -> None:
    """Generate a boustrophedon mowing mission from a polygon boundary."""
    # Parse polygon
    vertices = parse_poly_file(poly_file)
    console.print(f"[bold]Polygon:[/bold] {len(vertices)} vertices from {poly_file}")

    # Project to XY
    xy, origin = to_xy(vertices)

    # Detect or use provided heading
    if heading is None:
        heading = auto_heading(xy)
        console.print(f"[bold]Heading:[/bold] {heading:.1f}° (auto-detected from longest edge)")
    else:
        console.print(f"[bold]Heading:[/bold] {heading:.1f}° (user-specified)")

    spacing = width * (1.0 - overlap / 100.0)
    console.print(f"[bold]Strip width:[/bold] {width}m, overlap: {overlap}%, spacing: {spacing:.2f}m")

    # Generate path
    path_xy = generate_mow_path(xy, width=width, overlap=overlap, heading=heading)
    path_latlon = to_latlon(path_xy, origin)

    console.print(f"[bold]Waypoints:[/bold] {len(path_latlon)}")

    # Determine output path
    if output is None:
        base = os.path.splitext(poly_file)[0]
        output = f"{base}.waypoints"

    write_waypoints(output, path_latlon, home=vertices[0])
    console.print(Panel(f"[green]Written to {output}[/green]", title="Done"))
