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
    name="skynet",
    help="MAVLink fleet provisioning CLI for ArduPilot Rover/Mower vehicles.",
    no_args_is_help=True,
)
config_app = typer.Typer(
    help="BlueOS device configuration download and upload.",
    no_args_is_help=True,
)
misc_app = typer.Typer(
    help="Low-level MAVLink parameter utilities and config extraction.",
    no_args_is_help=True,
)
nav_app = typer.Typer(
    help="Navigation and mission planning.",
    no_args_is_help=True,
)
app.add_typer(config_app, name="config")
app.add_typer(misc_app, name="misc")
app.add_typer(nav_app, name="nav")

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
        console.print(f"skynet {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        Optional[bool],
        typer.Option("--version", "-V", callback=version_callback, is_eager=True),
    ] = None,
) -> None:
    """MAVLink fleet provisioning for ArduPilot mowers."""


@misc_app.command()
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


@misc_app.command()
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


@misc_app.command()
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


@misc_app.command()
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


@misc_app.command()
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


@misc_app.command()
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


@misc_app.command("extract-config")
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


@config_app.command()
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
    from .exceptions import BlueOSConnectionError, MowerProvisionerError
    from .extract import extract_config, fetch_mediamtx_config, save_yaml

    url = f"http://{host}" if not host.startswith("http") else host
    out_path = output or Path(f"{host}.yaml")

    # 1. Fetch BlueOS configuration + MediaMTX config over HTTP
    with BlueOSClient(url, timeout=_httpx.Timeout(timeout, read=timeout * 3)) as client:
        try:
            with console.status("Downloading BlueOS configuration..."):
                config = extract_config(client)
            with console.status("Downloading MediaMTX configuration..."):
                config["mediamtx"] = fetch_mediamtx_config(client)
        except BlueOSConnectionError as e:
            err_console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    # 2. Fetch autopilot parameters over MAVLink TCP
    params: dict[str, float] = {}
    mavlink_device = f"tcp:{host}:{MAVLINK_PORT}"
    try:
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
    except MowerProvisionerError as e:
        err_console.print(f"[yellow]Warning: Could not fetch autopilot params: {e}[/yellow]")

    # 3. Filter calibration params and add to config
    if params:
        if not include_calibration:
            params = {k: v for k, v in params.items() if k not in CALIBRATION_PARAMS}
        config["autopilot_params"] = dict(sorted(params.items()))
    else:
        config["autopilot_params"] = None

    # 4. Save
    save_yaml(config, out_path)

    ext_count = len(config.get("extensions") or [])
    mediamtx = config.get("mediamtx")
    console.print(f"[green]Downloaded to {out_path}[/green]")
    console.print(f"  BlueOS extensions: {ext_count}")
    if params:
        console.print(f"  Autopilot parameters: {len(params)}")
    else:
        err_console.print("  Autopilot parameters: [yellow]unavailable[/yellow]")
    if mediamtx:
        console.print(f"  MediaMTX config: {mediamtx['config_path']}")
    else:
        err_console.print("  MediaMTX config: [yellow]not found[/yellow]")
    nulls = [k for k, v in config.items()
             if v is None and k not in ("autopilot_params", "mediamtx")]
    if nulls:
        err_console.print(f"[yellow]Warning: Could not reach: {', '.join(nulls)}[/yellow]")


@config_app.command()
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
    from .exceptions import BlueOSConnectionError, MowerProvisionerError
    from .extract import load_yaml, push_mediamtx_config

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
    mediamtx = config.get("mediamtx")
    if mediamtx and isinstance(mediamtx, dict) and mediamtx.get("config"):
        changes.append(f"  MediaMTX config: {mediamtx.get('config_path', 'unknown path')}")
    network = config.get("network")
    if network and isinstance(network, dict) and network.get("ethernet"):
        unmanaged_count = sum(
            1 for iface in network["ethernet"]
            for addr in (iface.get("addresses") or [])
            if addr.get("mode") == "unmanaged"
        )
        if unmanaged_count:
            changes.append(f"  Static IPs (unmanaged): {unmanaged_count}")
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

                if mediamtx and isinstance(mediamtx, dict) and mediamtx.get("config"):
                    if push_mediamtx_config(client, mediamtx):
                        uploaded.append("mediamtx config")
                    else:
                        err_console.print("[yellow]Warning: Failed to push MediaMTX config[/yellow]")

                # Add unmanaged (static) IPs that are missing from the device
                if network and isinstance(network, dict) and network.get("ethernet"):
                    current = client.get_ethernet() or []
                    current_ips: dict[str, set[str]] = {}
                    for iface in current:
                        name = iface.get("name", "")
                        current_ips[name] = {
                            a.get("ip") for a in (iface.get("addresses") or [])
                        }

                    ip_ok = 0
                    for iface in network["ethernet"]:
                        iface_name = iface.get("name", "")
                        for addr in (iface.get("addresses") or []):
                            if addr.get("mode") != "unmanaged":
                                continue
                            ip = addr.get("ip", "")
                            if ip in current_ips.get(iface_name, set()):
                                ip_ok += 1
                                continue
                            if client.add_ip(iface_name, ip):
                                ip_ok += 1
                            else:
                                err_console.print(
                                    f"[yellow]Warning: Failed to add {ip} to {iface_name}[/yellow]"
                                )
                    if ip_ok:
                        uploaded.append(f"static IPs ({ip_ok})")
        except BlueOSConnectionError as e:
            err_console.print(f"[red]{e}[/red]")
            raise typer.Exit(1)

    # 2. Write autopilot parameters over MAVLink TCP
    if params:
        mavlink_device = f"tcp:{host}:{MAVLINK_PORT}"
        try:
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
        except MowerProvisionerError as e:
            err_console.print(f"[yellow]Warning: Could not write autopilot params: {e}[/yellow]")

    console.print(f"[green]Upload complete: {', '.join(uploaded)}[/green]")


@nav_app.command("sim")
def nav_sim(
    device: DeviceOption = DEFAULT_DEVICE,
    baud: BaudOption = DEFAULT_BAUD,
    ground_speed: Annotated[
        float,
        typer.Option(
            "--ground-speed",
            help="Max ground speed at full throttle (mph).",
        ),
    ] = 2.0,
    rate: Annotated[
        int,
        typer.Option(
            "--rate",
            help=(
                "GPS_INPUT emit rate in Hz (1-20). Default 15 Hz to keep "
                "the autopilot's AHRS origin-relative position getter "
                "fresh; rates as low as 5 Hz were observed to suppress "
                "LOCAL_POSITION_NED ≥90% of the time and freeze AUTO."
            ),
        ),
    ] = 15,
    track_width: Annotated[
        float,
        typer.Option(
            "--track-width", help="Track width (skid-steer) or wheelbase (Ackermann) in meters."
        ),
    ] = 0.5,
    max_steer_angle: Annotated[
        float,
        typer.Option(
            "--max-steer-angle", help="Max steering angle in degrees (Ackermann only)."
        ),
    ] = 30.0,
    duration: Annotated[
        Optional[float],
        typer.Option("--duration", help="Wall-clock safety timeout (s)."),
    ] = None,
    start_seq: Annotated[
        int,
        typer.Option(
            "--start-seq",
            help=(
                "Mission seq to spawn the rover at. The first waypoint "
                "driven toward will be start_seq + 1 so the rover has "
                "a non-zero distance to travel."
            ),
        ),
    ] = 1,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print plan and exit.")
    ] = False,
    verbose: Annotated[
        bool, typer.Option("--verbose", "-v", help="Print per-tick telemetry.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation.")
    ] = False,
    drive_mode: Annotated[
        str,
        typer.Option(
            "--drive-mode",
            help=(
                "How to command navigation once the EKF is healthy: "
                "'auto' (default) runs the mission through ModeAuto "
                "+ AR_WPNav; 'guided' bypasses the mission state "
                "machine and sends SET_POSITION_TARGET_GLOBAL_INT "
                "directly to the target waypoint in GUIDED mode. "
                "Use 'guided' to isolate whether the no-motion "
                "symptom is AUTO-specific."
            ),
        ),
    ] = "auto",
) -> None:
    """Run a HW-in-the-loop GPS/heading simulator against a real autopilot.

    Downloads the current mission, spawns a skid-steer rover at the first
    waypoint, and feeds GPS_INPUT back to the autopilot so it flies the
    mission in AUTO mode against simulated sensor data. Pixhawk Cube Orange+
    attitude loop, motor outputs, and EKF are all real — only the GPS and
    heading are simulated.

    Uses the same connection machinery as `misc connect`, so pointing at the
    BlueOS MAVLink proxy is just `-d tcp:<host>:5760`.
    """
    import select as _select
    import sys as _sys
    import time as _time

    from .exceptions import (
        FrameMismatchError,
        GpsSimError,
        MissionDownloadError,
        MissionUploadError,
        MowerProvisionerError,
    )
    from .gps_sim import (
        DRIVE_ACKERMANN,
        DRIVE_SKID_STEER,
        MPH_TO_MPS,
        SIM_PARAMS,
        AckermannModel,
        GpsInputEmitter,
        ServoNormalizer,
        SimParamContext,
        SkidSteerModel,
        StopWatcher,
        detect_drive_type,
        STATUSTEXT_SEVERITY_WARNING,
        SYS_STATUS_SENSOR_AHRS,
        SYS_STATUS_SENSOR_GPS,
        VisionPositionEmitter,
        deduplicate_mission,
        gps_fix_label,
        log_nav_tuning_params,
        arm_autopilot,
        offset_spawn_behind_waypoint,
        offset_spawn_perpendicular,
        send_rc_override,
        read_autopilot_yaw,
        reboot_autopilot,
        request_diagnostic_streams,
        request_servo_output_stream,
        resolve_sim_params,
        rover_mode_name,
        set_current_mission_seq,
        set_position_target_global,
        set_rover_mode,
        set_target_groundspeed,
        severity_label,
        sidecar_path,
        start_mission,
        wait_for_servo_output,
        warn_on_zero_speed_params,
    )

    ROVER_MODE_AUTO = 10
    ROVER_MODE_HOLD = 4
    ROVER_MODE_GUIDED = 15
    from .mission_download import download_mission
    from .mission_upload import (
        query_mission_count,
        upload_and_verify,
        upload_mission,
    )
    from .params import fetch_all_params

    REBOOT_WAIT = 8  # seconds to wait for autopilot reboot

    max_speed_mps = ground_speed * MPH_TO_MPS

    sidecar = sidecar_path(device)
    if sidecar.exists():
        console.print(
            f"[yellow]Leftover sidecar found at {sidecar} — "
            f"its contents will be used as the originals and the file "
            f"will be cleared before starting.[/yellow]"
        )

    try:
        # ── Phase 1: validate frame, download mission, write sim params, reboot ──
        with mavlink_connection(device, baud=baud) as conn:
            with console.status("Reading frame and servo params..."):
                all_params = fetch_all_params(conn)
            drive_type = detect_drive_type(all_params)
            if drive_type == DRIVE_SKID_STEER:
                console.print(
                    "[green]Frame OK:[/green] skid-steer "
                    "(SERVO1=ThrottleLeft, SERVO3=ThrottleRight)"
                )
            else:
                console.print(
                    "[green]Frame OK:[/green] Ackermann "
                    "(SERVO1=GroundSteering, SERVO3=Throttle)"
                )

            # Log autopilot speed params so we can see if any are zero
            # (which would silently prevent any throttle command).
            def _speed_warn(line: str) -> None:
                err_console.print(f"[yellow]Warning: {line}[/yellow]")

            speed_zeros = warn_on_zero_speed_params(all_params, _speed_warn)
            for name in ("CRUISE_SPEED", "CRUISE_THROTTLE", "WP_SPEED"):
                if name in all_params:
                    console.print(
                        f"  {name} = {all_params[name]}"
                    )

            # Navigation-tuning params. Useful when AUTO visibly refuses
            # to drive: WP_PIVOT_ANGLE=0 (default) means pivot is
            # disabled and all turns go through the scurve non-pivot
            # branch — which never writes nav_bearing, so telemetry
            # showing nav_bearing=0° is not by itself proof of a stuck
            # nav controller. See docs/SIM_AUTOPILOT_ISSUE_V3.md.
            console.print("[bold]Nav tuning params:[/bold]")
            log_nav_tuning_params(all_params, console.print)

            with console.status("Downloading mission from autopilot..."):
                raw_mission = download_mission(conn)
            console.print(
                f"Downloaded [bold]{len(raw_mission) - 1}[/bold] waypoints "
                f"(+ home) from autopilot"
            )

            # Remove consecutive duplicate waypoints. `nav_plan` sets
            # home = first path vertex, which usually equals mission[1].
            # That zero-length segment jams ArduRover's L1 nav controller
            # and prevents the rover from ever driving.
            mission = deduplicate_mission(raw_mission)
            if len(mission) < len(raw_mission):
                dropped = len(raw_mission) - len(mission)
                console.print(
                    f"[yellow]Deduplicated mission: removed {dropped} "
                    f"consecutive duplicate waypoint(s). "
                    f"{len(mission) - 1} unique waypoints remain.[/yellow]"
                )

            if start_seq < 1 or start_seq >= len(mission):
                err_console.print(
                    f"[red]--start-seq {start_seq} out of range "
                    f"(mission has {len(mission)} items, valid 1..{len(mission) - 1})[/red]"
                )
                raise typer.Exit(1)

            # Spawn 10 m behind WP1 along the WP1→WP2 back-projection,
            # with heading 90° CW from the track bearing. The 10 m
            # distance (vs 3–5 m in V4–V9) gives the L1 controller a
            # meaningful track segment to follow, and the perpendicular
            # heading creates a yaw error that forces the nav controller
            # to compute both a turning correction AND forward throttle.
            # See docs/SIM_AUTOPILOT_ISSUE_V10.md for the analysis of
            # why the V9 perpendicular spawn was degenerate.
            last_seq = len(mission) - 1
            target_lat, target_lon = mission[start_seq]
            if start_seq + 1 <= last_seq:
                next_lat, next_lon = mission[start_seq + 1]
            else:
                next_lat, next_lon = target_lat, target_lon
            start_lat, start_lon = offset_spawn_behind_waypoint(
                target_lat, target_lon, next_lat, next_lon, distance_m=10.0
            )
            # Compute heading: 90° CW from the bearing toward WP1.
            import math as _math
            _cos = _math.cos(_math.radians(start_lat))
            _dy = (target_lat - start_lat) * 111_320.0
            _dx = (target_lon - start_lon) * 111_320.0 * _cos
            _bearing_to_wp1 = _math.degrees(_math.atan2(_dx, _dy)) % 360.0
            spawn_heading = (_bearing_to_wp1 + 90.0) % 360.0

            table = Table(title="Sim config")
            table.add_column("Setting", style="bold")
            table.add_column("Value")
            table.add_row("Device", device)
            table.add_row("Drive type", drive_type)
            table.add_row("Ground speed", f"{ground_speed} mph ({max_speed_mps:.4f} m/s)")
            table.add_row("Rate", f"{rate} Hz")
            if drive_type == DRIVE_SKID_STEER:
                table.add_row("Track width", f"{track_width} m")
            else:
                table.add_row("Wheelbase", f"{track_width} m")
                table.add_row("Max steer angle", f"{max_steer_angle}°")
            table.add_row("Start seq", str(start_seq))
            table.add_row("Start lat/lon", f"{start_lat:.8f}, {start_lon:.8f}")
            table.add_row("Last mission seq", str(last_seq))
            table.add_row("Duration", f"{duration}s" if duration else "none")
            table.add_row("Drive mode", drive_mode)
            console.print(table)

            drive_mode_normalised = drive_mode.strip().lower()
            if drive_mode_normalised not in ("auto", "guided"):
                err_console.print(
                    f"[red]--drive-mode must be 'auto' or 'guided', "
                    f"got {drive_mode!r}[/red]"
                )
                raise typer.Exit(2)

            if dry_run:
                resolved = resolve_sim_params(all_params)
                console.print("[yellow]DRY RUN — param diff that would be applied:[/yellow]")
                for name, sim_val in sorted(resolved.items()):
                    current = all_params.get(name, "—")
                    console.print(f"  {name}: {current} → {sim_val}")
                console.print("[yellow]DRY RUN — no GPS_INPUT sent, no params written.[/yellow]")
                return

            if not yes:
                typer.confirm(
                    f"Apply sim param overrides to {device}, reboot autopilot, and start?",
                    abort=True,
                )

            servo1_norm = ServoNormalizer(1, all_params)
            servo3_norm = ServoNormalizer(3, all_params)

            # Write sim params + sidecar (SimParamContext.__enter__).
            # We enter the context here but don't exit until phase 2.
            sim_ctx = SimParamContext(conn, device)
            sim_ctx.__enter__()

            # GPS_TYPE requires a reboot to take effect.
            console.print("[bold]Rebooting autopilot for GPS_TYPE change...[/bold]")
            reboot_autopilot(conn)

        # Connection is dead after reboot — wait for autopilot to come back.
        with console.status(
            f"Waiting {REBOOT_WAIT}s for autopilot reboot..."
        ):
            _time.sleep(REBOOT_WAIT)

        # ── Phase 2: reconnect and run the sim loop ──
        with mavlink_connection(device, baud=baud, timeout=30.0) as conn:
            console.print("[green]Reconnected after reboot.[/green]")

            # Update the SimParamContext's conn so __exit__ restores via
            # the live connection.
            sim_ctx.conn = conn

            # Re-upload the mission. QGC (if connected) will sync its
            # own mission state to the autopilot after the reboot,
            # potentially wiping our 6-WP mission with its own. By
            # re-uploading we ensure the autopilot has the correct
            # mission when AUTO starts.
            #
            # Use upload_and_verify: on BlueOS+NetBird the first upload
            # after a reboot can race the MAVLink re-handshake and be
            # rejected mid-protocol with MAV_MISSION_RESULT=13
            # (INVALID_SEQUENCE), leaving a 1-WP stub that makes AUTO
            # refuse to drive. The verify step reads MISSION_COUNT back
            # and retries on mismatch. Failure here is fatal — the
            # previous "yellow warn and continue" path silently produced
            # the V4 bug. See docs/SIM_AUTOPILOT_ISSUE_V4.md §Issue 1.
            with console.status("Restoring mission after reboot..."):
                try:
                    stored = upload_and_verify(
                        conn, mission, max_attempts=3, timeout=15.0
                    )
                    console.print(
                        f"[green]Mission restored & verified:[/green] "
                        f"{len(mission) - 1} waypoints + home "
                        f"(autopilot reports {stored} items)"
                    )
                except MissionUploadError as e:
                    err_console.print(
                        f"[red]Mission re-upload failed: {e}[/red]\n"
                        f"[red]Refusing to run the sim with an "
                        f"unverified mission — AUTO would not drive "
                        f"against a stale/partial mission. Aborting so "
                        f"the operator can investigate.[/red]"
                    )
                    raise typer.Exit(3) from e

            # Second-pass param write for params that only exist *after*
            # VISO_TYPE=1 has been persisted across a reboot. The
            # AP_VisualOdom_MAV backend (VISO_TYPE=1) instantiates
            # VISO_DELAY_MS / VISO_POS_M_NSE / VISO_YAW_M_NSE only once
            # its backend is live — on the first pre-reboot param fetch
            # these names don't exist, so resolve_sim_params drops them
            # with a WARNING and they never get written. DISARM_DELAY
            # occasionally also misses the initial gap-detected fetch.
            # Re-fetch + re-apply now that the firmware has fully
            # initialised. See docs/SIM_AUTOPILOT_ISSUE_V4.md §Issue 3.
            try:
                with console.status(
                    "Re-checking VISO / DISARM_DELAY params after reboot..."
                ):
                    post_boot_params = fetch_all_params(conn)
                late_names = (
                    "VISO_DELAY_MS",
                    "VISO_POS_M_NSE",
                    "VISO_YAW_M_NSE",
                    "DISARM_DELAY",
                )
                late_writes: dict[str, float] = {}
                for name in late_names:
                    if name in post_boot_params and name in SIM_PARAMS:
                        current = post_boot_params[name]
                        target = SIM_PARAMS[name]
                        if abs(current - target) > 1e-6:
                            late_writes[name] = target
                if late_writes:
                    from .params import write_params as _wp
                    _wp(conn, late_writes, include_calibration=True)
                    # Record originals in the sidecar so restore on exit
                    # covers them too. Without this, a second-pass write
                    # would leak sim overrides past the sim context.
                    sim_ctx.record_late_originals(
                        {
                            name: post_boot_params[name]
                            for name in late_writes
                        }
                    )
                    console.print(
                        f"[green]Applied late sim params:[/green] "
                        f"{', '.join(sorted(late_writes))}"
                    )
            except Exception as e:
                err_console.print(
                    f"[yellow]Warning: late param re-check failed: "
                    f"{e}. Continuing — sim may be missing some "
                    f"nice-to-have overrides but not blockers.[/yellow]"
                )

            try:
                # Use the geometry-derived heading (90° CW from bearing
                # to WP1) rather than reading the autopilot's ATTITUDE.
                # The ATTITUDE read (V5 fix) returned DCM-fallback 0°
                # before EKF yaw alignment — using geometry avoids that
                # race entirely and gives the sim authoritative heading
                # via GPS_INPUT.yaw + VISION_POSITION_ESTIMATE.yaw.
                start_heading = spawn_heading
                console.print(
                    f"[green]Start heading:[/green] {start_heading:.1f}° "
                    "(from spawn geometry — 90° CW from bearing to WP1)"
                )

                if drive_type == DRIVE_SKID_STEER:
                    model = SkidSteerModel(
                        start_lat=start_lat,
                        start_lon=start_lon,
                        start_heading_deg=start_heading,
                        max_speed_mps=max_speed_mps,
                        track_width_m=track_width,
                    )
                else:
                    model = AckermannModel(
                        start_lat=start_lat,
                        start_lon=start_lon,
                        start_heading_deg=start_heading,
                        max_speed_mps=max_speed_mps,
                        wheelbase_m=track_width,
                        max_steer_angle_deg=max_steer_angle,
                    )

                request_servo_output_stream(conn, rate_hz=10.0)
                request_diagnostic_streams(conn)
                with console.status("Waiting for SERVO_OUTPUT_RAW..."):
                    first = wait_for_servo_output(conn, timeout=5.0)

                emitter = GpsInputEmitter(conn, model, rate_hz=float(rate))
                vision = VisionPositionEmitter(conn, model)
                watcher_cm = StopWatcher(
                    last_mission_seq=last_seq, duration_seconds=duration
                )

                dt = 1.0 / float(rate)
                last_servo1 = float(first.servo1_raw)
                last_servo3 = float(first.servo3_raw)
                armed_banner_printed = False
                # "holding" = we have arm-forced the autopilot into HOLD
                # mode and are waiting for the EKF to reach flags=831
                # before switching to AUTO/GUIDED. Rationale: when AUTO
                # is entered before HORIZ_POS_ABS is set,
                # ModeAuto::_enter/update calls mission.start_or_resume
                # the instant ahrs.get_origin() returns true — which can
                # precede HORIZ_POS_ABS by several seconds. The first
                # do_nav_wp → set_desired_location can then silently
                # fail in set_origin_and_destination_to_stopping_point,
                # leaving stale scurve/pos-control state that the
                # retry/mode-cycle does not always clear. See
                # docs/SIM_AUTOPILOT_ISSUE_V3.md §"What the new
                # autopilot-side log adds".
                holding = False
                nav_engaged = False  # AUTO or GUIDED is running
                last_guided_target_ms = 0.0
                ekf_healthy_banner_printed = False
                last_custom_mode: int | None = None
                last_mission_seq: int | None = None
                last_nav_log_monotonic = 0.0
                loop_start = _time.monotonic()
                tick_count = 0

                auto_engaged_at: float | None = None
                ever_saw_throttle = False
                auto_arm_sent = False
                guided_fallback_active = False
                motor_test_done = False
                motor_test_started_at: float | None = None

                # Rolling counters for the periodic stats line. We track
                # GPS_INPUT emits (what the sim *sent*) vs LOCAL_POSITION_NED
                # arrivals (what the autopilot *chose to emit back*). The
                # ratio is the diagnostic: a healthy autopilot with a fresh
                # EKF origin getter should produce LOCAL_POSITION_NED at the
                # 1 Hz we subscribed to. Missing lpos → AHRS origin-relative
                # getter is stale → AR_PosControl early-returns → no motion.
                # See docs/SIM_AUTOPILOT_ISSUE_V2.md for the full chain.
                last_stats_monotonic = _time.monotonic()
                last_stats_emit_count = 0
                lpos_rx_since_stats = 0
                gps_raw_rx_since_stats = 0
                STATS_INTERVAL_S = 5.0

                # EKF_STATUS_REPORT.flags bits we care about.
                EKF_POS_HORIZ_ABS = 16
                EKF_CONST_POS_MODE = 128

                # V4–V6 tracked SYS_STATUS AHRS health bit as a
                # secondary gate alongside EKF_STATUS_REPORT.flags.
                # V7 proved this was a permanent blocker on rovers
                # with compasses disabled: the AHRS *enabled* bit is
                # never set, so the gate can never fire. The AHRS
                # SYS_STATUS bit reflects compass subsystem status,
                # not EKF navigability — EKF flags=831 is sufficient.
                # See docs/SIM_AUTOPILOT_ISSUE_V7.md for the full
                # history and evidence.

                with watcher_cm as watcher:
                    console.print(
                        "[green]Sim running. Will auto-arm once EKF is healthy.[/green]"
                    )
                    console.print(
                        "[dim]After arming, wait for the [bold]EKF healthy[/bold] "
                        "banner. Allow up to 30 seconds for the EKF to fully "
                        "align (yaw align → origin set → variance settle → "
                        "using GPS → failsafe cleared). Throttle will not "
                        "command until the EKF reports POS_HORIZ_ABS set "
                        "and CONST_POS_MODE clear.[/dim]"
                    )
                    console.print(
                        "[dim]Type [bold]q[/bold] or [bold]:q[/bold] + Enter "
                        "to quit, or press Ctrl+C.[/dim]"
                    )

                    def _check_quit_key() -> bool:
                        """Return True if the user typed q/:q on stdin."""
                        try:
                            if not _sys.stdin.isatty():
                                return False
                            ready, _, _ = _select.select([_sys.stdin], [], [], 0)
                            if not ready:
                                return False
                            line = _sys.stdin.readline().strip()
                            return line.lower() in ("q", ":q", "quit", ":quit")
                        except (OSError, ValueError):
                            return False

                    try:
                        while not watcher.should_stop:
                            tick_start = _time.monotonic()

                            if _check_quit_key():
                                watcher.trip("user quit (q)")
                                break

                            while True:
                                msg = conn.recv_match(blocking=False)
                                if msg is None:
                                    break
                                t = msg.get_type()
                                src_sys = msg.get_srcSystem()
                                src_comp = msg.get_srcComponent()
                                from_autopilot = (
                                    src_sys == conn.target_system
                                    and src_comp == conn.target_component
                                )
                                if t == "SERVO_OUTPUT_RAW" and from_autopilot:
                                    last_servo1 = float(msg.servo1_raw)
                                    last_servo3 = float(msg.servo3_raw)
                                elif t == "HEARTBEAT":
                                    # Only the autopilot's heartbeat counts.
                                    # BlueOS services and QGC also broadcast
                                    # heartbeats through this proxy with
                                    # autopilot=MAV_AUTOPILOT_INVALID (8).
                                    from pymavlink import mavutil as _mavutil
                                    is_autopilot_hb = (
                                        from_autopilot
                                        and msg.autopilot
                                        != _mavutil.mavlink.MAV_AUTOPILOT_INVALID
                                    )
                                    if is_autopilot_hb:
                                        watcher.observe_heartbeat(msg.base_mode)
                                        if msg.custom_mode != last_custom_mode:
                                            last_custom_mode = msg.custom_mode
                                            console.print(
                                                f"[cyan]Flight mode: "
                                                f"{rover_mode_name(msg.custom_mode)}[/cyan]"
                                            )
                                elif t == "POSITION_TARGET_GLOBAL_INT" and from_autopilot:
                                    # Diagnostic for V6 §Issue 4. If
                                    # this message flows but (lat,lon)
                                    # stay at our current position,
                                    # AR_WPNav is running but its
                                    # scurve state is corrupted.
                                    now_m = _time.monotonic()
                                    if now_m - last_nav_log_monotonic > 2.0:
                                        console.print(
                                            f"[dim]pos_target: "
                                            f"lat={msg.lat_int / 1e7:.7f} "
                                            f"lon={msg.lon_int / 1e7:.7f} "
                                            f"alt={msg.alt:.2f}m "
                                            f"mask=0x{msg.type_mask:04X}[/dim]"
                                        )
                                elif t == "MISSION_ITEM_REACHED" and from_autopilot:
                                    console.print(
                                        f"[cyan]Reached waypoint {msg.seq}[/cyan]"
                                    )
                                    watcher.observe_mission_reached(msg.seq)
                                elif t == "MISSION_CURRENT" and from_autopilot:
                                    if msg.seq != last_mission_seq:
                                        last_mission_seq = msg.seq
                                        console.print(
                                            f"[cyan]Mission current seq: "
                                            f"{msg.seq}[/cyan]"
                                        )
                                elif t == "NAV_CONTROLLER_OUTPUT" and from_autopilot:
                                    # Rate-limit to once per 2 seconds so
                                    # verbose output stays readable.
                                    now_m = _time.monotonic()
                                    if now_m - last_nav_log_monotonic > 2.0:
                                        last_nav_log_monotonic = now_m
                                        console.print(
                                            f"[dim]nav: wp_dist={msg.wp_dist}m "
                                            f"target_bearing={msg.target_bearing}° "
                                            f"xtrack_err={msg.xtrack_error:.2f}m "
                                            f"nav_bearing={msg.nav_bearing}°[/dim]"
                                        )
                                elif t == "VFR_HUD" and from_autopilot:
                                    if msg.throttle > 0:
                                        ever_saw_throttle = True
                                    now_m = _time.monotonic()
                                    if now_m - last_nav_log_monotonic > 2.0:
                                        console.print(
                                            f"[dim]vfr: groundspeed={msg.groundspeed:.2f}m/s "
                                            f"throttle={msg.throttle}% "
                                            f"airspeed={msg.airspeed:.2f}m/s[/dim]"
                                        )
                                elif t == "GLOBAL_POSITION_INT" and from_autopilot:
                                    now_m = _time.monotonic()
                                    if now_m - last_nav_log_monotonic > 2.0:
                                        ap_lat = msg.lat / 1e7
                                        ap_lon = msg.lon / 1e7
                                        console.print(
                                            f"[dim]ap_pos: lat={ap_lat:.8f} "
                                            f"lon={ap_lon:.8f} "
                                            f"hdg={msg.hdg / 100.0:.1f}°[/dim]"
                                        )
                                elif t == "GPS_RAW_INT" and from_autopilot:
                                    gps_raw_rx_since_stats += 1
                                    # Reveals AP_GPS_MAV's reported fix_type.
                                    # AR_AttitudeControl::get_forward_speed
                                    # falls back to AP::gps().status() >= FIX_3D
                                    # when ahrs.get_velocity_NED() fails. If
                                    # fix_type is NO_FIX/2D here, the fallback
                                    # is unavailable and AR_WPNav::update() will
                                    # early-return — rover stays frozen.
                                    now_m = _time.monotonic()
                                    if now_m - last_nav_log_monotonic > 2.0:
                                        console.print(
                                            f"[dim]gps_raw: fix="
                                            f"{gps_fix_label(msg.fix_type)} "
                                            f"sats={msg.satellites_visible} "
                                            f"hdop={msg.eph / 100.0:.2f}[/dim]"
                                        )
                                elif t == "LOCAL_POSITION_NED" and from_autopilot:
                                    lpos_rx_since_stats += 1
                                    # EKF velocity (vx, vy) and NED position.
                                    # If this message is flowing with non-zero
                                    # magnitudes or changing values, the EKF is
                                    # publishing a velocity state and
                                    # ahrs.get_velocity_NED() is returning true.
                                    # Persistent zeros or missing message is a
                                    # strong signal AR_WPNav guard #4 is failing.
                                    now_m = _time.monotonic()
                                    if now_m - last_nav_log_monotonic > 2.0:
                                        console.print(
                                            f"[dim]lpos: "
                                            f"x={msg.x:+.2f}m y={msg.y:+.2f}m "
                                            f"vx={msg.vx:+.3f} vy={msg.vy:+.3f} "
                                            f"vz={msg.vz:+.3f}m/s[/dim]"
                                        )
                                elif t == "SYS_STATUS" and from_autopilot:
                                    # sensors_health bits reveal whether the
                                    # autopilot considers GPS and AHRS healthy
                                    # from its own perspective (these can be
                                    # unhealthy even when EKF_STATUS_REPORT.flags
                                    # looks fine, e.g. stale sensor data).
                                    h = msg.onboard_control_sensors_health
                                    e = msg.onboard_control_sensors_enabled
                                    now_m = _time.monotonic()
                                    if now_m - last_nav_log_monotonic > 2.0:
                                        gps_h = bool(h & SYS_STATUS_SENSOR_GPS)
                                        ahrs_h = bool(h & SYS_STATUS_SENSOR_AHRS)
                                        gps_e = bool(e & SYS_STATUS_SENSOR_GPS)
                                        ahrs_e = bool(e & SYS_STATUS_SENSOR_AHRS)
                                        console.print(
                                            f"[dim]sys: "
                                            f"gps={'OK' if gps_h else 'BAD'}"
                                            f"{'' if gps_e else '(disabled)'} "
                                            f"ahrs={'OK' if ahrs_h else 'BAD'}"
                                            f"{'' if ahrs_e else '(disabled)'}"
                                            f"[/dim]"
                                        )
                                elif t == "STATUSTEXT":
                                    # Always show warnings+ from anything
                                    # on the bus. ArduPilot uses these to
                                    # surface EKF rejections, arming
                                    # inhibits, etc. Strip trailing NUL.
                                    text = msg.text
                                    if isinstance(text, bytes):
                                        text = text.decode("utf-8", errors="replace")
                                    text = text.rstrip("\x00").strip()
                                    sev = msg.severity
                                    if sev <= STATUSTEXT_SEVERITY_WARNING:
                                        console.print(
                                            f"[red]autopilot "
                                            f"[{severity_label(sev)}]: "
                                            f"{text}[/red]"
                                        )
                                elif t == "EKF_STATUS_REPORT" and from_autopilot:
                                    # Headline event: detect the moment
                                    # the EKF exits CONST_POS_MODE and has
                                    # absolute horizontal position. AUTO
                                    # mode cannot command throttle until
                                    # this happens.
                                    # V7: EKF flags alone are
                                    # sufficient — the SYS_STATUS AHRS
                                    # bit reflects compass subsystem
                                    # health, which is permanently
                                    # disabled on this rover. See
                                    # docs/SIM_AUTOPILOT_ISSUE_V7.md.
                                    healthy = bool(
                                        msg.flags & EKF_POS_HORIZ_ABS
                                        and not (msg.flags & EKF_CONST_POS_MODE)
                                    )
                                    # One-shot banner (informational).
                                    if healthy and not ekf_healthy_banner_printed:
                                        sim_t = _time.monotonic() - loop_start
                                        console.print(
                                            f"[bold green]EKF healthy "
                                            f"(t={sim_t:.1f}s, flags={msg.flags}). "
                                            f"AUTO mode can now drive — wait "
                                            f"~5 s for throttle to ramp.[/bold green]"
                                        )
                                        ekf_healthy_banner_printed = True

                                    # Auto-arm once EKF is healthy.
                                    # Sends MAV_CMD_COMPONENT_ARM_DISARM
                                    # so the operator doesn't need to
                                    # arm via QGC. ARMING_CHECK=0 is
                                    # set by sim params, so this
                                    # succeeds immediately. The arm
                                    # triggers the HOLD→wait→AUTO flow
                                    # below.
                                    if (
                                        healthy
                                        and not auto_arm_sent
                                        and not watcher.armed_latch
                                    ):
                                        arm_autopilot(conn)
                                        auto_arm_sent = True
                                        console.print(
                                            "[cyan]Auto-arm command sent.[/cyan]"
                                        )

                                    # V8: decouple the HOLD→AUTO
                                    # transition from the one-shot
                                    # banner. Run on EVERY healthy
                                    # tick when holding+not-engaged.
                                    # The V8 log showed EKF going
                                    # healthy BEFORE arm was detected
                                    # (MANUAL mode on this run), so
                                    # the one-shot gate consumed the
                                    # banner while holding=False and
                                    # the transition never fired. See
                                    # docs/SIM_AUTOPILOT_ISSUE_V8.md.
                                    if (
                                        healthy
                                        and holding
                                        and not nav_engaged
                                    ):
                                        # Pre-AUTO mission-count gate.
                                        if drive_mode_normalised == "auto":
                                            try:
                                                stored = query_mission_count(
                                                    conn, timeout=3.0
                                                )
                                            except MissionUploadError as e:
                                                err_console.print(
                                                    f"[red]Pre-AUTO "
                                                    f"MISSION_COUNT query "
                                                    f"failed: {e}. Refusing "
                                                    f"to engage AUTO.[/red]"
                                                )
                                                raise
                                            if stored < last_seq + 1:
                                                err_console.print(
                                                    f"[red]Pre-AUTO check: "
                                                    f"autopilot stores "
                                                    f"{stored} mission items "
                                                    f"but sim expects at "
                                                    f"least {last_seq + 1} "
                                                    f"(through seq "
                                                    f"{last_seq}). Refusing "
                                                    f"to engage AUTO — "
                                                    f"re-upload the mission "
                                                    f"and retry.[/red]"
                                                )
                                                raise typer.Exit(4)

                                        from .mission_upload import (
                                            _drain_mission_traffic,
                                        )
                                        _drain_mission_traffic(conn, window=0.5)
                                        set_rover_mode(conn, ROVER_MODE_HOLD)
                                        _time.sleep(0.3)
                                        if drive_mode_normalised == "guided":
                                            set_rover_mode(
                                                conn, ROVER_MODE_GUIDED
                                            )
                                            _time.sleep(0.2)
                                            set_position_target_global(
                                                conn, target_lat, target_lon
                                            )
                                            last_guided_target_ms = (
                                                _time.monotonic()
                                            )
                                            set_target_groundspeed(
                                                conn, max_speed_mps
                                            )
                                            console.print(
                                                "[cyan]Engaged "
                                                "HOLD→GUIDED → "
                                                f"target=({target_lat:.7f}, "
                                                f"{target_lon:.7f}). "
                                                "Bypassing mission "
                                                "state machine.[/cyan]"
                                            )
                                        else:
                                            set_rover_mode(
                                                conn, ROVER_MODE_AUTO
                                            )
                                            _time.sleep(0.2)
                                            set_current_mission_seq(
                                                conn, start_seq
                                            )
                                            start_mission(conn)
                                            set_target_groundspeed(
                                                conn, max_speed_mps
                                            )
                                            console.print(
                                                "[cyan]Engaged "
                                                "HOLD→AUTO → "
                                                "MISSION_START "
                                                f"@ seq={start_seq}. "
                                                "Watch for nav_bearing "
                                                "to track target_bearing "
                                                "and servos to leave "
                                                "1500 PWM.[/cyan]"
                                            )
                                        nav_engaged = True
                                        holding = False
                                        auto_engaged_at = _time.monotonic()
                                        ever_saw_throttle = False

                                        # Post-engagement param probe:
                                        # read speed/accel params to
                                        # see if the scurve has sane
                                        # inputs. If any are zero the
                                        # scurve can't produce motion.
                                        _PROBE_PARAMS = [
                                            "CRUISE_SPEED",
                                            "CRUISE_THROTTLE",
                                            "WP_SPEED",
                                            "ATC_ACCEL_MAX",
                                            "ATC_DECEL_MAX",
                                            "ATC_SPEED_P",
                                            "ATC_SPEED_I",
                                            "ATC_SPEED_FF",
                                            "MOT_THR_MIN",
                                            "MOT_THR_MAX",
                                            "BRD_SAFETY_DEFLT",
                                            "BRD_SAFETYENABLE",
                                        ]
                                        for _pname in _PROBE_PARAMS:
                                            conn.mav.param_request_read_send(
                                                conn.target_system,
                                                conn.target_component,
                                                _pname.encode("utf-8"),
                                                -1,
                                            )
                                        _probe_deadline = (
                                            _time.monotonic() + 3.0
                                        )
                                        _probed: dict[str, float] = {}
                                        while (
                                            _time.monotonic() < _probe_deadline
                                            and len(_probed) < len(_PROBE_PARAMS)
                                        ):
                                            _pm = conn.recv_match(
                                                type="PARAM_VALUE",
                                                blocking=True,
                                                timeout=0.5,
                                            )
                                            if _pm is None:
                                                continue
                                            _pid = _pm.param_id
                                            if isinstance(_pid, bytes):
                                                _pid = _pid.decode(
                                                    "utf-8"
                                                ).rstrip("\x00")
                                            if _pid in _PROBE_PARAMS:
                                                _probed[_pid] = _pm.param_value
                                        _probe_lines = []
                                        for _pname in _PROBE_PARAMS:
                                            _val = _probed.get(_pname)
                                            _flag = ""
                                            if _val is not None and _val == 0:
                                                _flag = " [ZERO!]"
                                            _probe_lines.append(
                                                f"  {_pname}="
                                                f"{_val if _val is not None else '?'}"
                                                f"{_flag}"
                                            )
                                        console.print(
                                            "[dim]Post-engage param probe:\n"
                                            + "\n".join(_probe_lines)
                                            + "[/dim]"
                                        )
                                    elif (
                                        not healthy
                                        and ekf_healthy_banner_printed
                                    ):
                                        # EKF degraded after being healthy
                                        # — could be a variance spike.
                                        console.print(
                                            f"[yellow]EKF degraded "
                                            f"(flags={msg.flags}). May "
                                            f"recover.[/yellow]"
                                        )
                                        ekf_healthy_banner_printed = False

                                    now_m = _time.monotonic()
                                    if now_m - last_nav_log_monotonic > 2.0:
                                        console.print(
                                            f"[dim]ekf: vel_var={msg.velocity_variance:.2f} "
                                            f"pos_horiz_var={msg.pos_horiz_variance:.2f} "
                                            f"pos_vert_var={msg.pos_vert_variance:.2f} "
                                            f"compass_var={msg.compass_variance:.2f} "
                                            f"flags={msg.flags}[/dim]"
                                        )

                            s1 = servo1_norm.normalize(last_servo1)
                            s3 = servo3_norm.normalize(last_servo3)
                            _lat, _lon, _hdg, vn, ve = model.step(dt, s1, s3)
                            spd = (vn**2 + ve**2) ** 0.5
                            emitter.set_velocity(vn, ve)
                            emitter.emit()
                            vision.emit()
                            tick_count += 1

                            # Every STATS_INTERVAL_S seconds, print achieved
                            # GPS_INPUT send rate and received LOCAL_POSITION_NED
                            # count. The expected lpos_rx at 1 Hz subscription
                            # is ~STATS_INTERVAL_S; anything substantially
                            # below that means the autopilot's AHRS origin-
                            # relative position getter is returning false most
                            # ticks (gating AR_PosControl::update).
                            now_m = _time.monotonic()
                            dt_stats = now_m - last_stats_monotonic
                            if dt_stats >= STATS_INTERVAL_S:
                                sent = emitter.emit_count - last_stats_emit_count
                                actual_rate = sent / dt_stats if dt_stats > 0 else 0.0
                                expected_lpos = int(round(dt_stats))  # 1 Hz sub
                                lpos_pct = (
                                    100.0 * lpos_rx_since_stats / expected_lpos
                                    if expected_lpos > 0 else 0.0
                                )
                                console.print(
                                    f"[dim]stats: gps_out={actual_rate:.1f}Hz "
                                    f"(target={rate}Hz, sent={sent}/"
                                    f"{dt_stats:.1f}s)  "
                                    f"gps_raw_in={gps_raw_rx_since_stats}  "
                                    f"lpos_in={lpos_rx_since_stats}/"
                                    f"{expected_lpos} "
                                    f"({lpos_pct:.0f}% of 1Hz sub)[/dim]"
                                )
                                last_stats_monotonic = now_m
                                last_stats_emit_count = emitter.emit_count
                                lpos_rx_since_stats = 0
                                gps_raw_rx_since_stats = 0

                            if watcher.armed_latch and not armed_banner_printed:
                                console.print(
                                    "[green]GPS lock established. Autopilot is armed.[/green]"
                                )
                                armed_banner_printed = True

                            # ── MANUAL-mode motor test ──
                            # After arming, briefly switch to MANUAL
                            # and inject RC override to test whether
                            # the autopilot passes throttle to servos.
                            # This tests the most fundamental path:
                            #   RC input → MANUAL mixer → SERVO_OUTPUT
                            # If servos stay at 1500, the motor/RC/IOMCU
                            # config is broken — not just the nav
                            # controller. Runs once, then resumes
                            # the normal HOLD→AUTO flow.
                            if (
                                watcher.armed_latch
                                and armed_banner_printed
                                and not motor_test_done
                                and not holding
                                and not nav_engaged
                            ):
                                ROVER_MODE_MANUAL = 0
                                console.print(
                                    "[bold cyan]── Motor test: "
                                    "MANUAL + RC override ──[/bold cyan]"
                                )
                                set_rover_mode(conn, ROVER_MODE_MANUAL)
                                _time.sleep(0.5)

                                # Phase 1: forward (both motors)
                                # RC3=throttle in standard Rover config
                                # Send 1600 (mild forward) for 2 s
                                test_results: list[str] = []
                                for phase_name, rc_ch, rc_val, dur in [
                                    ("Forward (RC3=1600)", 3, 1600, 2.0),
                                    ("Steer left (RC1=1300)", 1, 1300, 2.0),
                                    ("Steer right (RC1=1700)", 1, 1700, 2.0),
                                    ("Neutral (RC1=1500,RC3=1500)", 0, 0, 0.5),
                                ]:
                                    if rc_ch > 0:
                                        send_rc_override(
                                            conn, {rc_ch: rc_val}
                                        )
                                    else:
                                        send_rc_override(
                                            conn, {1: 1500, 3: 1500}
                                        )
                                    phase_end = _time.monotonic() + dur
                                    s1_min = 9999
                                    s1_max = 0
                                    s3_min = 9999
                                    s3_max = 0
                                    while _time.monotonic() < phase_end:
                                        # Keep GPS flowing
                                        emitter.emit()
                                        vision.emit()
                                        srv = conn.recv_match(
                                            type="SERVO_OUTPUT_RAW",
                                            blocking=True,
                                            timeout=0.2,
                                        )
                                        if srv is not None:
                                            s1_min = min(s1_min, srv.servo1_raw)
                                            s1_max = max(s1_max, srv.servo1_raw)
                                            s3_min = min(s3_min, srv.servo3_raw)
                                            s3_max = max(s3_max, srv.servo3_raw)
                                    moved = (
                                        s1_max - s1_min > 10
                                        or s3_max - s3_min > 10
                                        or (rc_ch == 3 and s3_max > 1510)
                                        or (rc_ch == 1 and s1_max > 1510)
                                        or (rc_ch == 1 and s1_min < 1490)
                                    )
                                    status = (
                                        "[green]RESPONDED[/green]"
                                        if moved
                                        else "[red]NO RESPONSE[/red]"
                                    )
                                    line = (
                                        f"  {phase_name}: "
                                        f"S1=[{s1_min}–{s1_max}] "
                                        f"S3=[{s3_min}–{s3_max}] "
                                        f"→ {status}"
                                    )
                                    test_results.append(line)
                                    console.print(line)

                                # Release overrides
                                send_rc_override(conn, {1: 0, 3: 0})

                                any_response = any(
                                    "RESPONDED" in r for r in test_results
                                )
                                if any_response:
                                    console.print(
                                        "[bold green]Motor test: at "
                                        "least one channel responded. "
                                        "Motor path is alive.[/bold green]"
                                    )
                                else:
                                    console.print(
                                        "[bold red]Motor test: NO "
                                        "servo response to any RC "
                                        "override. Motor/RC/IOMCU "
                                        "config is broken — this is "
                                        "upstream of the nav "
                                        "controller.[/bold red]"
                                    )

                                motor_test_done = True
                                console.print(
                                    "[cyan]Motor test complete. "
                                    "Resuming normal flow...[/cyan]"
                                )

                            # On first arm, park the autopilot in HOLD
                            # instead of AUTO. ModeAuto::_enter would
                            # otherwise queue mission.start_or_resume at
                            # the exact moment the EKF first reports an
                            # origin — which precedes HORIZ_POS_ABS and
                            # can silently fail the first do_nav_wp.
                            # HOLD needs no navigation state, so we can
                            # safely linger there until flags=831.
                            if watcher.armed_latch and not holding and not nav_engaged:
                                set_rover_mode(conn, ROVER_MODE_HOLD)
                                console.print(
                                    "[cyan]Forced mode=HOLD. "
                                    "Switching to "
                                    f"{drive_mode_normalised.upper()} "
                                    "once EKF reports flags=831.[/cyan]"
                                )
                                holding = True

                            # HOLD stickiness: while we're in the "wait
                            # for EKF health" window, aggressively
                            # re-assert HOLD if something external (QGC,
                            # a stale auto-re-engage on the autopilot)
                            # flips the mode away. This prevents
                            # ModeAuto::_enter from firing twice against
                            # an unhealthy EKF — once on the initial
                            # user-arm in AUTO and again on a QGC
                            # re-command — which the V5 log showed
                            # happened at t≈6.2 s. See
                            # docs/SIM_AUTOPILOT_ISSUE_V5.md §Issue 4.
                            if (
                                holding
                                and not nav_engaged
                                and last_custom_mode is not None
                                and last_custom_mode != ROVER_MODE_HOLD
                            ):
                                set_rover_mode(conn, ROVER_MODE_HOLD)
                                console.print(
                                    f"[yellow]Re-asserted HOLD "
                                    f"(autopilot flipped to "
                                    f"{rover_mode_name(last_custom_mode)} "
                                    f"before EKF healthy).[/yellow]"
                                )

                            # Keep the autopilot in the chosen nav mode
                            # once engaged. If something (RC failsafe,
                            # manual override via QGC) kicks it out,
                            # drive it back. We only do this AFTER
                            # nav_engaged is true so we don't fight the
                            # operator during the HOLD-wait window.
                            if nav_engaged and last_custom_mode is not None:
                                target_mode = (
                                    ROVER_MODE_AUTO
                                    if drive_mode_normalised == "auto"
                                    else ROVER_MODE_GUIDED
                                )
                                if last_custom_mode != target_mode:
                                    set_rover_mode(conn, target_mode)

                            # GUIDED requires the target position to be
                            # re-sent periodically. ArduPilot clears the
                            # GUIDED target after GUID_TIMEOUT (default
                            # 3 s) if no SET_POSITION_TARGET_* arrives,
                            # reverting to a loiter/stop. Re-send at
                            # 1 Hz to keep the target fresh.
                            if (
                                nav_engaged
                                and drive_mode_normalised == "guided"
                            ):
                                now_ms = _time.monotonic()
                                if now_ms - last_guided_target_ms > 1.0:
                                    set_position_target_global(
                                        conn, target_lat, target_lon
                                    )
                                    last_guided_target_ms = now_ms

                            if not watcher.armed_latch and armed_banner_printed:
                                console.print(
                                    "[yellow]Transient disarm — EKF may still be converging. "
                                    "Waiting for re-arm...[/yellow]"
                                )
                                armed_banner_printed = False

                            if verbose:
                                sim_t = tick_start - loop_start
                                if drive_type == DRIVE_SKID_STEER:
                                    servo_str = (
                                        f"L={s1:+.2f}({int(last_servo1)})  "
                                        f"R={s3:+.2f}({int(last_servo3)})"
                                    )
                                else:
                                    servo_str = (
                                        f"STR={s1:+.2f}({int(last_servo1)})  "
                                        f"THR={s3:+.2f}({int(last_servo3)})"
                                    )
                                mode_str = (
                                    rover_mode_name(last_custom_mode)
                                    if last_custom_mode is not None
                                    else "?"
                                )
                                console.print(
                                    f"t={sim_t:6.1f}  "
                                    f"mode={mode_str:<6}  "
                                    f"lat={_lat:.8f}  lon={_lon:.8f}  "
                                    f"hdg={_hdg:05.1f}\u00b0  "
                                    f"spd={spd:.2f}m/s  "
                                    f"{servo_str}"
                                )

                            if watcher.stop_reason == "DISARM":
                                console.print(
                                    "[yellow]Autopilot disarmed.[/yellow]"
                                )

                            watcher.check_duration()

                            elapsed = _time.monotonic() - tick_start
                            sleep_for = dt - elapsed
                            if sleep_for > 0:
                                _time.sleep(sleep_for)
                    except KeyboardInterrupt:
                        watcher.trip("KeyboardInterrupt")

                console.print(
                    f"[green]Sim stopped: {watcher.stop_reason or 'clean exit'}[/green]"
                )
            finally:
                # Restore original params and reboot to re-enable real GPS.
                console.print("[bold]Restoring original params...[/bold]")
                sim_ctx.__exit__(None, None, None)
                console.print(
                    "[bold]Rebooting autopilot to restore GPS driver...[/bold]"
                )
                reboot_autopilot(conn)

    except (
        MissionDownloadError,
        FrameMismatchError,
        GpsSimError,
    ) as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)
    except MowerProvisionerError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)


@nav_app.command("upload")
def nav_upload(
    waypoint_file: Annotated[
        Path, typer.Argument(help="Path to QGC WPL 110 .waypoints file."),
    ],
    device: DeviceOption = DEFAULT_DEVICE,
    baud: BaudOption = DEFAULT_BAUD,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Show what would be uploaded.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation.")
    ] = False,
) -> None:
    """Upload a .waypoints mission file to the autopilot via MAVLink.

    Uses the same connection machinery as `misc connect`, so pointing at the
    BlueOS MAVLink proxy is just `-d tcp:<host>:5760`.
    """
    from .exceptions import MissionUploadError, MowerProvisionerError
    from .mission_planning import read_waypoints
    from .mission_upload import upload_mission

    try:
        items = read_waypoints(str(waypoint_file), include_home=True)
    except (FileNotFoundError, ValueError) as e:
        err_console.print(f"[red]Failed to read {waypoint_file}: {e}[/red]")
        raise typer.Exit(1)

    if not items:
        err_console.print(
            f"[red]{waypoint_file} contains no waypoints[/red]"
        )
        raise typer.Exit(1)

    mission_count = max(len(items) - 1, 0)
    console.print(
        f"Loaded [bold]{mission_count}[/bold] waypoints (+ home) from "
        f"[bold]{waypoint_file}[/bold]"
    )

    if dry_run:
        console.print("[yellow]DRY RUN — no MAVLink connection will be opened.[/yellow]")
        for seq, (lat, lon) in enumerate(items):
            label = "home" if seq == 0 else f"wp{seq}"
            console.print(f"  [{seq:3d}] {label}: {lat:.8f}, {lon:.8f}")
        return

    if not yes:
        typer.confirm(
            f"Upload {mission_count} waypoints to {device}?", abort=True
        )

    try:
        with mavlink_connection(device, baud=baud) as conn:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                console=console,
            ) as progress:
                task = progress.add_task(
                    "Uploading mission...", total=len(items)
                )

                def on_progress(written: int, total: int) -> None:
                    progress.update(task, completed=written)

                upload_mission(conn, items, progress_callback=on_progress)
    except MissionUploadError as e:
        err_console.print(f"[red]Mission upload failed: {e}[/red]")
        raise typer.Exit(1)
    except MowerProvisionerError as e:
        err_console.print(f"[red]{e}[/red]")
        raise typer.Exit(1)

    console.print(
        f"[green]Uploaded {mission_count} waypoints to {device}.[/green]"
    )


@nav_app.command("plan")
def nav_plan(
    kml_file: Annotated[
        Path, typer.Argument(help="Path to KML boundary file."),
    ],
    width: Annotated[
        float,
        typer.Option("--width", "-w", help="Mower cutting width in inches."),
    ],
    output: Annotated[
        Optional[Path],
        typer.Option("--output", "-o", help="Output base path for .waypoints files."),
    ] = None,
    visualize: Annotated[
        bool,
        typer.Option("--visualize", help="Generate an interactive HTML map visualization."),
    ] = False,
    kml_track: Annotated[
        bool,
        typer.Option("--kml-track", help="Generate KML with gx:Track animation for Google Earth."),
    ] = False,
    kml_tour: Annotated[
        bool,
        typer.Option("--kml-tour", help="Generate KML tour flyover for Google Earth."),
    ] = False,
) -> None:
    """Generate contour-following mowing missions from a KML polygon boundary.

    Pure file-to-file: opens no MAVLink or HTTP connection.
    """
    from rich.panel import Panel

    from .mission_planning import (
        INCHES_TO_METERS,
        extract_spine,
        generate_contour_paths,
        generate_kml_track,
        generate_kml_tour,
        generate_visualization_html,
        parse_kml_file,
        to_latlon,
        to_xy,
        write_waypoints,
    )

    kml_path_str = str(kml_file)

    # Parse and project the polygon
    vertices = parse_kml_file(kml_path_str)
    console.print(f"[bold]Polygon:[/bold] {len(vertices)} vertices from {kml_file}")

    xy, origin = to_xy(vertices)

    # Extract spine (vertices walked until first >= 90 degree turn)
    spine_xy = extract_spine(xy)
    console.print(f"[bold]Spine:[/bold] {len(spine_xy)} vertices (until \u226590\u00b0 turn)")

    width_m = width * INCHES_TO_METERS
    console.print(f"[bold]Mower width:[/bold] {width}\" ({width_m:.4f}m)")

    mower_paths_xy = generate_contour_paths(xy, spine_xy, width_inches=width)
    num_mowers = len(mower_paths_xy)
    console.print(f"[bold]Mowers required:[/bold] {num_mowers}")

    mower_paths = [to_latlon(path, origin) for path in mower_paths_xy]

    # Determine output base path (strip extension if user gave one)
    if output is None:
        base = os.path.splitext(kml_path_str)[0]
    else:
        base = os.path.splitext(str(output))[0]

    if num_mowers == 0:
        err_console.print(
            "[red]No paths generated \u2014 polygon may be too narrow for the mower width[/red]"
        )
        raise typer.Exit(code=1)
    elif num_mowers == 1:
        out_path = f"{base}.waypoints"
        write_waypoints(out_path, mower_paths[0], home=vertices[0])
        console.print(Panel(f"[green]Written to {out_path}[/green]", title="Done"))
    else:
        written_paths = []
        for i, segment in enumerate(mower_paths, start=1):
            out_path = f"{base}_mower{i}.waypoints"
            write_waypoints(out_path, segment, home=vertices[0])
            written_paths.append(out_path)
        file_list = "\n".join(f"  [green]{p}[/green]" for p in written_paths)
        console.print(
            Panel(
                f"[green]{num_mowers} mower files written:[/green]\n{file_list}",
                title="Done",
            )
        )

    if visualize:
        viz_path = f"{base}.html"
        generate_visualization_html(mower_paths, viz_path)
        console.print(f"[bold]Visualization:[/bold] [cyan]{viz_path}[/cyan]")

    if kml_track:
        track_path = f"{base}_track.kml"
        generate_kml_track(mower_paths, track_path)
        console.print(f"[bold]KML Track:[/bold] [cyan]{track_path}[/cyan]")

    if kml_tour:
        tour_path = f"{base}_tour.kml"
        generate_kml_tour(mower_paths, tour_path)
        console.print(f"[bold]KML Tour:[/bold] [cyan]{tour_path}[/cyan]")
