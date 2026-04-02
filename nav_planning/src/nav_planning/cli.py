"""CLI entry point for nav-plan."""

from __future__ import annotations

import os
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel

from nav_planning.polygon import parse_kml_file, to_xy, to_latlon, extract_spine
from nav_planning.contour import generate_contour_paths, INCHES_TO_METERS
from nav_planning.waypoints import write_waypoints
from nav_planning.visualize import generate_visualization_html

app = typer.Typer(help="Waypoint mission planning for Skyridge autonomous mower fleet.")
console = Console()


@app.command()
def mow(
    kml_file: str = typer.Argument(help="Path to KML boundary file"),
    width: float = typer.Option(..., "--width", "-w", help="Mower cutting width in inches"),
    output: Optional[str] = typer.Option(
        None, "-o", "--output", help="Output base path for .waypoints files"
    ),
    visualize: bool = typer.Option(
        False, "--visualize", help="Generate an interactive HTML map visualization"
    ),
) -> None:
    """Generate contour-following mowing missions from a KML polygon boundary."""
    # Parse KML polygon (validates closure)
    vertices = parse_kml_file(kml_file)
    console.print(f"[bold]Polygon:[/bold] {len(vertices)} vertices from {kml_file}")

    # Project to XY
    xy, origin = to_xy(vertices)

    # Extract spine (follows vertices until >= 90 degree turn)
    spine_xy = extract_spine(xy)
    console.print(f"[bold]Spine:[/bold] {len(spine_xy)} vertices (until \u226590\u00b0 turn)")

    width_m = width * INCHES_TO_METERS
    console.print(f"[bold]Mower width:[/bold] {width}\" ({width_m:.4f}m)")

    # Generate contour-following paths
    mower_paths_xy = generate_contour_paths(xy, spine_xy, width_inches=width)
    num_mowers = len(mower_paths_xy)
    console.print(f"[bold]Mowers required:[/bold] {num_mowers}")

    # Convert all paths back to lat/lon
    mower_paths = [to_latlon(path, origin) for path in mower_paths_xy]

    # Determine output base path
    if output is None:
        base = os.path.splitext(kml_file)[0]
    else:
        base = os.path.splitext(output)[0]

    # Write per-mower waypoint files
    if num_mowers == 0:
        console.print("[red]No paths generated — polygon may be too narrow for the mower width[/red]")
        raise typer.Exit(code=1)
    elif num_mowers == 1:
        out_path = f"{base}.waypoints"
        write_waypoints(out_path, mower_paths[0], home=vertices[0])
        console.print(Panel(f"[green]Written to {out_path}[/green]", title="Done"))
    else:
        written = []
        for i, segment in enumerate(mower_paths, start=1):
            out_path = f"{base}_mower{i}.waypoints"
            write_waypoints(out_path, segment, home=vertices[0])
            written.append(out_path)
        file_list = "\n".join(f"  [green]{p}[/green]" for p in written)
        console.print(Panel(
            f"[green]{num_mowers} mower files written:[/green]\n{file_list}",
            title="Done",
        ))

    if visualize:
        viz_path = f"{base}.html"
        generate_visualization_html(mower_paths, viz_path)
        console.print(f"[bold]Visualization:[/bold] [cyan]{viz_path}[/cyan]")
