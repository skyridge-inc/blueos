"""Typer CLI commands for mower provisioning."""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import typer
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn
from rich.table import Table

from . import __version__
from .config import load_param_file, save_param_file
from .connection import get_vehicle_type_name, mavlink_connection
from .params import diff_params, fetch_all_params, write_params

app = typer.Typer(
    name="mower-provision",
    help="MAVLink fleet provisioning CLI for ArduPilot Rover/Mower vehicles.",
    no_args_is_help=True,
)
console = Console()
err_console = Console(stderr=True)

# Shared options
DeviceOption = Annotated[
    str,
    typer.Option(
        "--device", "-d",
        envvar="MOWER_DEVICE",
        help="MAVLink device connection string.",
    ),
]
BaudOption = Annotated[
    int,
    typer.Option("--baud", "-b", help="Serial baud rate."),
]
CalibrationOption = Annotated[
    bool,
    typer.Option("--include-calibration", help="Include calibration parameters."),
]

DEFAULT_DEVICE = "/dev/ttyACM0"
DEFAULT_BAUD = 115200


def version_callback(value: bool) -> None:
    if value:
        console.print(f"mower-provision {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-V", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    """MAVLink fleet provisioning for ArduPilot mowers."""


@app.command()
def connect(
    device: DeviceOption = DEFAULT_DEVICE,
    baud: BaudOption = DEFAULT_BAUD,
) -> None:
    """Test connection and display heartbeat info."""
    with console.status(f"Connecting to {device}..."):
        with mavlink_connection(device, baud=baud) as conn:
            pass

    msg = conn.messages.get("HEARTBEAT")
    table = Table(title="Connection Info")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    table.add_row("Device", device)
    table.add_row("System ID", str(conn.target_system))
    table.add_row("Component ID", str(conn.target_component))
    if msg:
        table.add_row("Vehicle Type", get_vehicle_type_name(msg.type))
        table.add_row("Autopilot", str(msg.autopilot))
        table.add_row("Base Mode", str(msg.base_mode))
    console.print(table)
    console.print("[green]Connection successful![/green]")


@app.command()
def read(
    device: DeviceOption = DEFAULT_DEVICE,
    baud: BaudOption = DEFAULT_BAUD,
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Save params to file."),
    ] = None,
    include_calibration: CalibrationOption = False,
) -> None:
    """Fetch all parameters from device."""
    with mavlink_connection(device, baud=baud) as conn:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Reading params...", total=None)

            def on_progress(received: int, total: int) -> None:
                progress.update(task, completed=received, total=total)

            params = fetch_all_params(conn, progress_callback=on_progress)

    console.print(f"Received [bold]{len(params)}[/bold] parameters.")

    if output:
        save_param_file(output, params, include_calibration=include_calibration)
        console.print(f"Saved to [bold]{output}[/bold]")
    else:
        table = Table(title="Device Parameters")
        table.add_column("Parameter", style="bold")
        table.add_column("Value", justify="right")
        for name in sorted(params):
            table.add_row(name, str(params[name]))
        console.print(table)


@app.command()
def write(
    param_file: Annotated[Path, typer.Argument(help="Path to .param file.")],
    device: DeviceOption = DEFAULT_DEVICE,
    baud: BaudOption = DEFAULT_BAUD,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be written.")] = False,
    include_calibration: CalibrationOption = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Write all parameters from file to device."""
    params = load_param_file(param_file, include_calibration=include_calibration)
    console.print(f"Loaded [bold]{len(params)}[/bold] parameters from {param_file}")

    if dry_run:
        console.print("[yellow]DRY RUN — no parameters will be written.[/yellow]")
        for name in sorted(params):
            console.print(f"  {name} = {params[name]}")
        return

    if not yes:
        typer.confirm(
            f"Write {len(params)} parameters to {device}?", abort=True
        )

    with mavlink_connection(device, baud=baud) as conn:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Writing params...", total=len(params))

            def on_progress(written: int, total: int) -> None:
                progress.update(task, completed=written)

            written = write_params(
                conn,
                params,
                include_calibration=include_calibration,
                progress_callback=on_progress,
            )

    console.print(f"[green]Wrote {len(written)} parameters to {device}.[/green]")


@app.command()
def diff(
    param_file: Annotated[Path, typer.Argument(help="Path to .param file.")],
    device: DeviceOption = DEFAULT_DEVICE,
    baud: BaudOption = DEFAULT_BAUD,
    include_calibration: CalibrationOption = False,
) -> None:
    """Show differences between file and device parameters."""
    file_params = load_param_file(param_file, include_calibration=include_calibration)

    with mavlink_connection(device, baud=baud) as conn:
        with console.status("Reading device params..."):
            device_params = fetch_all_params(conn)

    result = diff_params(
        file_params, device_params, include_calibration=include_calibration
    )

    if not result.has_differences:
        console.print("[green]No differences found.[/green]")
        return

    table = Table(title=f"Diff: {param_file} vs {device}")
    table.add_column("Status", style="bold")
    table.add_column("Parameter")
    table.add_column("File Value", justify="right")
    table.add_column("Device Value", justify="right")

    for name, value in sorted(result.added.items()):
        table.add_row("[green]ADD[/green]", name, str(value), "—")

    for name, (fval, dval) in sorted(result.changed.items()):
        table.add_row("[yellow]CHG[/yellow]", name, str(fval), str(dval))

    for name, value in sorted(result.removed.items()):
        table.add_row("[red]DEL[/red]", name, "—", str(value))

    console.print(table)
    console.print(
        f"\n[bold]{result.total_changes}[/bold] differences: "
        f"[green]{len(result.added)} added[/green], "
        f"[yellow]{len(result.changed)} changed[/yellow], "
        f"[red]{len(result.removed)} removed[/red]"
    )


@app.command()
def sync(
    param_file: Annotated[Path, typer.Argument(help="Path to .param file.")],
    device: DeviceOption = DEFAULT_DEVICE,
    baud: BaudOption = DEFAULT_BAUD,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be synced.")] = False,
    yes: Annotated[bool, typer.Option("--yes", "-y", help="Skip confirmation.")] = False,
) -> None:
    """Smart sync — write only changed/added parameters to device."""
    file_params = load_param_file(param_file)

    with mavlink_connection(device, baud=baud) as conn:
        with console.status("Reading device params..."):
            device_params = fetch_all_params(conn)

        result = diff_params(file_params, device_params)

        if not result.has_differences:
            console.print("[green]Device is in sync. Nothing to do.[/green]")
            return

        # Build the set of params to write (added + changed)
        to_sync: dict[str, float] = {}
        to_sync.update(result.added)
        for name, (fval, _dval) in result.changed.items():
            to_sync[name] = fval

        console.print(
            f"[bold]{len(to_sync)}[/bold] parameters to sync "
            f"([green]{len(result.added)} new[/green], "
            f"[yellow]{len(result.changed)} changed[/yellow])"
        )

        if dry_run:
            console.print("[yellow]DRY RUN — no parameters will be written.[/yellow]")
            for name in sorted(to_sync):
                console.print(f"  {name} = {to_sync[name]}")
            return

        if not yes:
            typer.confirm(
                f"Sync {len(to_sync)} parameters to {device}?", abort=True
            )

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Syncing params...", total=len(to_sync))

            def on_progress(written: int, total: int) -> None:
                progress.update(task, completed=written)

            written = write_params(
                conn,
                to_sync,
                include_calibration=True,  # already filtered by diff
                progress_callback=on_progress,
            )

    console.print(f"[green]Synced {len(written)} parameters to {device}.[/green]")


@app.command()
def backup(
    device: DeviceOption = DEFAULT_DEVICE,
    baud: BaudOption = DEFAULT_BAUD,
    output_dir: Annotated[
        Path,
        typer.Option("--output-dir", "-o", help="Directory for backup file."),
    ] = Path("."),
) -> None:
    """Full backup of device parameters to timestamped file."""
    with mavlink_connection(device, baud=baud) as conn:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Backing up params...", total=None)

            def on_progress(received: int, total: int) -> None:
                progress.update(task, completed=received, total=total)

            params = fetch_all_params(conn, progress_callback=on_progress)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"backup_{timestamp}.param"
    output_path = output_dir / filename

    save_param_file(output_path, params, include_calibration=True)
    console.print(
        f"[green]Backed up {len(params)} parameters to {output_path}[/green]"
    )
