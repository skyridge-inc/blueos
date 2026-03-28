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
from .config import CALIBRATION_PARAMS, load_param_file, save_param_file
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


@app.command("extract-config")
def extract_config_cmd(
    url: Annotated[
        str,
        typer.Argument(help="BlueOS device URL (e.g., http://blueos.local or 192.168.2.2)."),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Output YAML file path. Default: <hostname>.yaml"),
    ] = None,
    timeout: Annotated[
        float,
        typer.Option("--timeout", "-t", help="HTTP request timeout in seconds."),
    ] = 10.0,
) -> None:
    """Extract full configuration from a BlueOS device to YAML."""
    import httpx as _httpx

    from .blueos_api import BlueOSClient
    from .exceptions import BlueOSConnectionError
    from .extract import extract_config, output_filename, save_yaml

    # Normalize URL
    if not url.startswith("http"):
        url = f"http://{url}"

    out_path = output or output_filename(url)

    with console.status(f"Connecting to {url}..."):
        client = BlueOSClient(url, timeout=_httpx.Timeout(timeout, read=timeout * 3))

    with client:
        try:
            with console.status("Extracting configuration..."):
                config = extract_config(client)
        except BlueOSConnectionError as e:
            err_console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    save_yaml(config, out_path)

    # Summary
    ext_count = len(config.get("extensions") or [])
    console.print(f"[green]Configuration saved to {out_path}[/green]")
    console.print(f"  Extensions: {ext_count}")
    nulls = [k for k, v in config.items() if v is None and not k.startswith("_")]
    if nulls:
        err_console.print(f"[yellow]Warning: Could not reach: {', '.join(nulls)}[/yellow]")


MAVLINK_PORT = 5760


@app.command()
def download(
    host: Annotated[
        str,
        typer.Argument(help="BlueOS IP or hostname (e.g., 192.168.2.2 or blueos.local)."),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Output YAML file path. Default: <host>.yaml"),
    ] = None,
    include_calibration: CalibrationOption = False,
    timeout: Annotated[
        float,
        typer.Option("--timeout", "-t", help="HTTP request timeout in seconds."),
    ] = 10.0,
) -> None:
    """Download BlueOS configuration and autopilot parameters to YAML."""
    import httpx as _httpx

    from .blueos_api import BlueOSClient
    from .exceptions import BlueOSConnectionError
    from .extract import extract_config, save_yaml

    url = f"http://{host}" if not host.startswith("http") else host
    out_path = output or Path(f"{host}.yaml")

    # 1. Fetch BlueOS configuration over HTTP
    with BlueOSClient(url, timeout=_httpx.Timeout(timeout, read=timeout * 3)) as client:
        try:
            with console.status("Downloading BlueOS configuration..."):
                config = extract_config(client)
        except BlueOSConnectionError as e:
            err_console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    # 2. Fetch autopilot parameters over MAVLink TCP
    mavlink_device = f"tcp:{host}:{MAVLINK_PORT}"
    with mavlink_connection(mavlink_device) as conn:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Downloading autopilot parameters...", total=None)

            def on_progress(received: int, total: int) -> None:
                progress.update(task, completed=received, total=total)

            params = fetch_all_params(conn, progress_callback=on_progress)

    # 3. Filter calibration params and add to config
    if not include_calibration:
        params = {k: v for k, v in params.items() if k not in CALIBRATION_PARAMS}
    config["autopilot_params"] = dict(sorted(params.items()))

    # 4. Save
    save_yaml(config, out_path)

    ext_count = len(config.get("extensions") or [])
    console.print(f"[green]Downloaded to {out_path}[/green]")
    console.print(f"  BlueOS extensions: {ext_count}")
    console.print(f"  Autopilot parameters: {len(params)}")
    nulls = [k for k, v in config.items()
             if v is None and not k.startswith("_") and k != "autopilot_params"]
    if nulls:
        err_console.print(f"[yellow]Warning: Could not reach: {', '.join(nulls)}[/yellow]")


@app.command()
def upload(
    host: Annotated[
        str,
        typer.Argument(help="BlueOS IP or hostname (e.g., 192.168.2.2 or blueos.local)."),
    ],
    config_file: Annotated[
        Path,
        typer.Argument(help="Path to YAML configuration file."),
    ],
    include_calibration: CalibrationOption = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Show what would be uploaded without making changes."),
    ] = False,
    yes: Annotated[
        bool,
        typer.Option("--yes", "-y", help="Skip confirmation prompt."),
    ] = False,
    timeout: Annotated[
        float,
        typer.Option("--timeout", "-t", help="HTTP request timeout in seconds."),
    ] = 10.0,
) -> None:
    """Upload configuration and autopilot parameters from YAML to BlueOS device."""
    import httpx as _httpx

    from .blueos_api import BlueOSClient
    from .exceptions import BlueOSConnectionError
    from .extract import load_yaml

    config = load_yaml(config_file)

    # Summarize what will be uploaded
    changes: list[str] = []
    if config.get("hostname") is not None:
        changes.append(f"  Hostname: {config['hostname']}")
    if config.get("vehicle_name") is not None:
        changes.append(f"  Vehicle name: {config['vehicle_name']}")
    bag = config.get("bag")
    if bag and isinstance(bag, dict):
        changes.append(f"  Bag entries: {len(bag)}")
    params = config.get("autopilot_params")
    if params and isinstance(params, dict):
        if not include_calibration:
            params = {k: v for k, v in params.items() if k not in CALIBRATION_PARAMS}
        changes.append(f"  Autopilot parameters: {len(params)}")

    if not changes:
        console.print("[yellow]Nothing to upload — YAML has no writable sections.[/yellow]")
        return

    console.print(f"[bold]Upload to {host}:[/bold]")
    for line in changes:
        console.print(line)

    if dry_run:
        console.print("[yellow]DRY RUN — no changes will be made.[/yellow]")
        if params:
            console.print("\n[bold]Parameters:[/bold]")
            for name in sorted(params):
                console.print(f"  {name} = {params[name]}")
        return

    if not yes:
        typer.confirm(f"Upload to {host}?", abort=True)

    url = f"http://{host}" if not host.startswith("http") else host
    uploaded: list[str] = []

    # 1. Push BlueOS config over HTTP
    with BlueOSClient(url, timeout=_httpx.Timeout(timeout, read=timeout * 3)) as client:
        try:
            with console.status("Uploading BlueOS configuration..."):
                if config.get("hostname") is not None:
                    if client.set_hostname(config["hostname"]):
                        uploaded.append("hostname")
                    else:
                        err_console.print("[yellow]Warning: Failed to set hostname[/yellow]")

                if config.get("vehicle_name") is not None:
                    if client.set_vehicle_name(config["vehicle_name"]):
                        uploaded.append("vehicle_name")
                    else:
                        err_console.print("[yellow]Warning: Failed to set vehicle name[/yellow]")

                if bag and isinstance(bag, dict):
                    bag_ok = 0
                    for key, value in bag.items():
                        if client.set_bag(key, value):
                            bag_ok += 1
                        else:
                            err_console.print(f"[yellow]Warning: Failed to set bag/{key}[/yellow]")
                    if bag_ok:
                        uploaded.append(f"bag ({bag_ok} entries)")
        except BlueOSConnectionError as e:
            err_console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    # 2. Write autopilot parameters over MAVLink TCP
    if params:
        mavlink_device = f"tcp:{host}:{MAVLINK_PORT}"
        with mavlink_connection(mavlink_device) as conn:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task("Uploading autopilot parameters...", total=len(params))

                def on_progress(written: int, total: int) -> None:
                    progress.update(task, completed=written)

                written = write_params(
                    conn,
                    params,
                    include_calibration=True,  # already filtered above
                    progress_callback=on_progress,
                )
        uploaded.append(f"autopilot params ({len(written)})")

    console.print(f"[green]Upload complete: {', '.join(uploaded)}[/green]")
