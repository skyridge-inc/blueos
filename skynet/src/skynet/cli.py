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
        typer.Option("--rate", help="GPS_INPUT emit rate in Hz (1-20)."),
    ] = 5,
    track_width: Annotated[
        float,
        typer.Option(
            "--track-width", help="Skid-steer track width in meters."
        ),
    ] = 0.5,
    duration: Annotated[
        Optional[float],
        typer.Option("--duration", help="Wall-clock safety timeout (s)."),
    ] = None,
    start_seq: Annotated[
        int,
        typer.Option("--start-seq", help="Mission seq to spawn at."),
    ] = 1,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Print plan and exit.")
    ] = False,
    yes: Annotated[
        bool, typer.Option("--yes", "-y", help="Skip confirmation.")
    ] = False,
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
    import time as _time

    from .exceptions import (
        FrameMismatchError,
        GpsSimError,
        MissionDownloadError,
        MowerProvisionerError,
    )
    from .gps_sim import (
        MPH_TO_MPS,
        SIM_PARAMS,
        GpsInputEmitter,
        ServoNormalizer,
        SimParamContext,
        SkidSteerModel,
        StopWatcher,
        request_servo_output_stream,
        sidecar_path,
        validate_skid_steer,
        wait_for_servo_output,
    )
    from .mission_download import download_mission
    from .params import fetch_all_params

    max_speed_mps = ground_speed * MPH_TO_MPS

    # Refuse upfront if sidecar exists — before even opening a connection.
    sidecar = sidecar_path(device)
    if sidecar.exists():
        err_console.print(
            f"[red]Leftover sidecar file detected: {sidecar}[/red]\n"
            f"[red]A previous `skynet nav sim` run likely crashed. "
            f"Restore the autopilot with:[/red]\n"
            f"  [bold]skynet misc write {sidecar} --yes --include-calibration[/bold]\n"
            f"[red]Then delete the sidecar and retry.[/red]"
        )
        raise typer.Exit(1)

    try:
        with mavlink_connection(device, baud=baud) as conn:
            with console.status("Downloading mission from autopilot..."):
                mission = download_mission(conn)
            console.print(
                f"Downloaded [bold]{len(mission) - 1}[/bold] waypoints "
                f"(+ home) from autopilot"
            )

            if start_seq < 1 or start_seq >= len(mission):
                err_console.print(
                    f"[red]--start-seq {start_seq} out of range "
                    f"(mission has {len(mission)} items, valid 1..{len(mission) - 1})[/red]"
                )
                raise typer.Exit(1)

            with console.status("Reading frame and servo params..."):
                all_params = fetch_all_params(conn)
            validate_skid_steer(all_params)
            console.print(
                "[green]Frame OK:[/green] skid-steer rover "
                "(SERVO1=ThrottleLeft, SERVO3=ThrottleRight)"
            )

            start_lat, start_lon = mission[start_seq]
            last_seq = len(mission) - 1

            table = Table(title="Sim config")
            table.add_column("Setting", style="bold")
            table.add_column("Value")
            table.add_row("Device", device)
            table.add_row("Ground speed", f"{ground_speed} mph ({max_speed_mps:.4f} m/s)")
            table.add_row("Rate", f"{rate} Hz")
            table.add_row("Track width", f"{track_width} m")
            table.add_row("Start seq", str(start_seq))
            table.add_row("Start lat/lon", f"{start_lat:.8f}, {start_lon:.8f}")
            table.add_row("Last mission seq", str(last_seq))
            table.add_row("Duration", f"{duration}s" if duration else "none")
            console.print(table)

            if dry_run:
                console.print("[yellow]DRY RUN — param diff that would be applied:[/yellow]")
                for name, sim_val in sorted(SIM_PARAMS.items()):
                    current = all_params.get(name, "—")
                    console.print(f"  {name}: {current} → {sim_val}")
                console.print("[yellow]DRY RUN — no GPS_INPUT sent, no params written.[/yellow]")
                return

            if not yes:
                typer.confirm(
                    f"Apply sim param overrides to {device} and start the loop?",
                    abort=True,
                )

            left_norm = ServoNormalizer(1, all_params)
            right_norm = ServoNormalizer(3, all_params)
            model = SkidSteerModel(
                start_lat=start_lat,
                start_lon=start_lon,
                max_speed_mps=max_speed_mps,
                track_width_m=track_width,
            )

            with SimParamContext(conn, device):
                request_servo_output_stream(conn, rate_hz=10.0)
                with console.status("Waiting for SERVO_OUTPUT_RAW..."):
                    first = wait_for_servo_output(conn, timeout=2.0)

                emitter = GpsInputEmitter(conn, model, rate_hz=float(rate))
                watcher_cm = StopWatcher(
                    last_mission_seq=last_seq, duration_seconds=duration
                )

                dt = 1.0 / float(rate)
                last_servo1 = float(first.servo1_raw)
                last_servo3 = float(first.servo3_raw)
                armed_banner_printed = False

                with watcher_cm as watcher:
                    console.print(
                        "[green]Sim running. Arm in AUTO via GCS to begin.[/green]"
                    )
                    try:
                        while not watcher.should_stop:
                            tick_start = _time.monotonic()

                            # Drain inbox for state updates.
                            while True:
                                msg = conn.recv_match(blocking=False)
                                if msg is None:
                                    break
                                t = msg.get_type()
                                if t == "SERVO_OUTPUT_RAW":
                                    last_servo1 = float(msg.servo1_raw)
                                    last_servo3 = float(msg.servo3_raw)
                                elif t == "HEARTBEAT":
                                    watcher.observe_heartbeat(msg.base_mode)
                                elif t == "MISSION_ITEM_REACHED":
                                    watcher.observe_mission_reached(msg.seq)

                            left = left_norm.normalize(last_servo1)
                            right = right_norm.normalize(last_servo3)
                            _lat, _lon, _hdg, vn, ve = model.step(dt, left, right)
                            emitter.set_velocity(vn, ve)
                            emitter.emit()

                            if watcher.armed_latch and not armed_banner_printed:
                                console.print(
                                    "[green]GPS lock established. Autopilot is armed.[/green]"
                                )
                                armed_banner_printed = True

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
