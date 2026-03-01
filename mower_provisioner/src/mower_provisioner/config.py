"""Param file I/O and calibration exclusion list."""

from __future__ import annotations

from pathlib import Path

from .exceptions import ParamFileError

# Parameters that are vehicle-specific calibration data and should NOT be
# overwritten during fleet provisioning (unless explicitly requested).
CALIBRATION_PARAMS: frozenset[str] = frozenset(
    {
        # IMU calibration
        "INS_ACC2OFFS_X",
        "INS_ACC2OFFS_Y",
        "INS_ACC2OFFS_Z",
        "INS_ACC2SCAL_X",
        "INS_ACC2SCAL_Y",
        "INS_ACC2SCAL_Z",
        "INS_ACC3OFFS_X",
        "INS_ACC3OFFS_Y",
        "INS_ACC3OFFS_Z",
        "INS_ACC3SCAL_X",
        "INS_ACC3SCAL_Y",
        "INS_ACC3SCAL_Z",
        "INS_ACCOFFS_X",
        "INS_ACCOFFS_Y",
        "INS_ACCOFFS_Z",
        "INS_ACCSCAL_X",
        "INS_ACCSCAL_Y",
        "INS_ACCSCAL_Z",
        "INS_GYR2OFFS_X",
        "INS_GYR2OFFS_Y",
        "INS_GYR2OFFS_Z",
        "INS_GYR3OFFS_X",
        "INS_GYR3OFFS_Y",
        "INS_GYR3OFFS_Z",
        "INS_GYROFFS_X",
        "INS_GYROFFS_Y",
        "INS_GYROFFS_Z",
        # Compass calibration
        "COMPASS_DIA_X",
        "COMPASS_DIA_Y",
        "COMPASS_DIA_Z",
        "COMPASS_DIA2_X",
        "COMPASS_DIA2_Y",
        "COMPASS_DIA2_Z",
        "COMPASS_DIA3_X",
        "COMPASS_DIA3_Y",
        "COMPASS_DIA3_Z",
        "COMPASS_MOT_X",
        "COMPASS_MOT_Y",
        "COMPASS_MOT_Z",
        "COMPASS_MOT2_X",
        "COMPASS_MOT2_Y",
        "COMPASS_MOT2_Z",
        "COMPASS_MOT3_X",
        "COMPASS_MOT3_Y",
        "COMPASS_MOT3_Z",
        "COMPASS_ODI_X",
        "COMPASS_ODI_Y",
        "COMPASS_ODI_Z",
        "COMPASS_ODI2_X",
        "COMPASS_ODI2_Y",
        "COMPASS_ODI2_Z",
        "COMPASS_ODI3_X",
        "COMPASS_ODI3_Y",
        "COMPASS_ODI3_Z",
        "COMPASS_OFS_X",
        "COMPASS_OFS_Y",
        "COMPASS_OFS_Z",
        "COMPASS_OFS2_X",
        "COMPASS_OFS2_Y",
        "COMPASS_OFS2_Z",
        "COMPASS_OFS3_X",
        "COMPASS_OFS3_Y",
        "COMPASS_OFS3_Z",
        # Battery calibration
        "BATT_AMP_OFFSET",
        "BATT_AMP_PERVLT",
        "BATT_VOLT_MULT",
        "BATT2_AMP_OFFSET",
        "BATT2_AMP_PERVLT",
        "BATT2_VOLT_MULT",
        # RC calibration
        "RC1_MIN",
        "RC1_MAX",
        "RC1_TRIM",
        "RC2_MIN",
        "RC2_MAX",
        "RC2_TRIM",
        "RC3_MIN",
        "RC3_MAX",
        "RC3_TRIM",
        "RC4_MIN",
        "RC4_MAX",
        "RC4_TRIM",
        "RC5_MIN",
        "RC5_MAX",
        "RC5_TRIM",
        "RC6_MIN",
        "RC6_MAX",
        "RC6_TRIM",
        "RC7_MIN",
        "RC7_MAX",
        "RC7_TRIM",
        "RC8_MIN",
        "RC8_MAX",
        "RC8_TRIM",
        # System identity
        "SYSID_THISMAV",
    }
)


def load_param_file(
    path: Path, *, include_calibration: bool = False
) -> dict[str, float]:
    """Load a .param file and return a dict of name -> value.

    Supports both comma-separated and space-separated formats.
    Lines starting with # are comments. Blank lines are skipped.
    """
    params: dict[str, float] = {}
    try:
        text = path.read_text()
    except OSError as e:
        raise ParamFileError(f"Cannot read {path}: {e}") from e

    for line_num, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        # Try comma first, then whitespace
        if "," in line:
            parts = line.split(",", maxsplit=1)
        else:
            parts = line.split(None, maxsplit=1)

        if len(parts) != 2:
            raise ParamFileError(
                f"Invalid format at {path}:{line_num}: {raw_line!r}"
            )

        name = parts[0].strip()
        try:
            value = float(parts[1].strip())
        except ValueError as e:
            raise ParamFileError(
                f"Invalid value at {path}:{line_num}: {parts[1]!r}"
            ) from e

        if not include_calibration and name in CALIBRATION_PARAMS:
            continue

        params[name] = value

    return params


def save_param_file(
    path: Path,
    params: dict[str, float],
    *,
    include_calibration: bool = True,
) -> None:
    """Save parameters to a .param file in comma-separated format.

    Integer-valued floats are written without decimals (e.g. 1 not 1.0).
    """
    lines: list[str] = []
    for name in sorted(params):
        if not include_calibration and name in CALIBRATION_PARAMS:
            continue
        value = params[name]
        # Format integers cleanly
        if value == int(value) and abs(value) < 2**31:
            lines.append(f"{name},{int(value)}")
        else:
            lines.append(f"{name},{value}")
    lines.append("")  # trailing newline

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines))
    except OSError as e:
        raise ParamFileError(f"Cannot write {path}: {e}") from e
