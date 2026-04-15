# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Codebase Analysis Prep (READ FIRST)

**Before doing any non-trivial analysis of the existing code (audits,
architecture review, cross-file refactors, "where is X used?" surveys,
debugging that spans multiple modules, etc.), regenerate the codebase
index:**

```bash
bunx repomix@latest
```

This writes a single consolidated XML snapshot of the entire repository
to `./repomix-output.xml`. Read that file as your primary index of the
codebase — it gives you the complete file tree, file contents, and
dependency relationships in one self-contained document, which is far
more efficient than recursive Glob/Grep traversal for broad questions.

**Workflow:**

1. Run `bunx repomix@latest` (takes a few seconds, idempotent).
2. Read `./repomix-output.xml` for the global picture.
3. Use targeted Read/Grep/Glob only for the specific files the index
   points you to.

**When to skip the index** — narrow, targeted edits where you already
know the file and line you're modifying. The regenerate-and-read
overhead isn't worth it for one-line bug fixes.

**Keep the index fresh** — if you've made non-trivial edits and need to
re-analyze, re-run `bunx repomix@latest` so the snapshot reflects your
changes. `./repomix-output.xml` is regenerated on demand.

## Build & Test

```bash
uv sync                                    # install deps (never use pip)
uv run pytest                              # all tests
uv run pytest --tb=short -v                # verbose with short tracebacks
uv run pytest tests/test_params.py         # single file
uv run pytest tests/test_params.py::TestDiffParams::test_mixed_changes  # single test
uv tool install .                          # install CLI globally
mower-provision --help                     # CLI entry point
```

No linter or formatter configured.

## Architecture

Python 3.11+ CLI built with Typer, managed by uv + hatchling. Entry point: `cli:app` (registered as `mower-provision`).

**Data flow**: `.param` file <-> `config.py` (I/O + filtering) <-> `params.py` (MAVLink operations) <-> `connection.py` (device transport)

**Module responsibilities**:
- `config.py` — File I/O and the `CALIBRATION_PARAMS` frozenset (~70 vehicle-specific params). This is the safety gate — all load/save/write/diff operations filter through it unless `--include-calibration` is passed.
- `connection.py` — `mavlink_connection()` context manager: connect -> heartbeat wait -> yield -> close. All CLI commands use this.
- `params.py` — `fetch_all_params()` uses index-based gap detection (not simple request-and-wait): requests all, waits, then re-requests missing indices in batches of 10. `write_params()` sends individually with PARAM_VALUE ack + 3 retries. `diff_params()` uses `EPSILON = 1e-6` float tolerance.
- `cli.py` — Six Typer commands: `connect`, `read`, `write`, `diff`, `sync`, `backup`. Shared options via `Annotated` type aliases (`DeviceOption`, `BaudOption`, `CalibrationOption`). Uses Rich progress bars and tables for output.
- `exceptions.py` — Hierarchy rooted at `MowerProvisionerError`. Connection errors, param errors, and file errors are separate branches.

## Key Design Decisions

- **Calibration protection is the core safety mechanism.** `CALIBRATION_PARAMS` excludes IMU, compass, battery, RC, and SYSID params from all operations by default. Do not weaken this without explicit intent. The `--include-calibration` flag is the only override.
- **`sync` command passes `include_calibration=True` to `write_params`** because it has already filtered through `diff_params`. This is intentional — don't add a second filter.
- **`backup` always includes calibration** (`include_calibration=True`) to capture complete device state.
- **Integer-valued floats** are written without decimals in .param files (e.g., `3` not `3.0`) for ArduPilot compatibility.

## Testing Patterns

Tests mock the MAVLink connection via `conftest.py::mock_conn` fixture (MagicMock with `target_system`, `target_component`, `mav`). No integration tests against real hardware.

- `test_config.py` — .param file round-trip, format parsing (comma and space), calibration filtering, error cases
- `test_params.py` — diff logic (epsilon tolerance, calibration exclusion), write ack/retry, fetch with progress callbacks

To simulate param messages in fetch tests, use `_make_param_msg()` helper that creates MagicMock with `param_id` (bytes), `param_value`, `param_index`, `param_count`.

<!-- BACKLOG.MD MCP GUIDELINES START -->

<CRITICAL_INSTRUCTION>

## BACKLOG WORKFLOW INSTRUCTIONS

This project uses Backlog.md MCP for all task and project management activities.

**CRITICAL GUIDANCE**

- If your client supports MCP resources, read `backlog://workflow/overview` to understand when and how to use Backlog for this project.
- If your client only supports tools or the above request fails, call `backlog.get_backlog_instructions()` to load the tool-oriented overview. Use the `instruction` selector when you need `task-creation`, `task-execution`, or `task-finalization`.

- **First time working here?** Read the overview resource IMMEDIATELY to learn the workflow
- **Already familiar?** You should have the overview cached ("## Backlog.md Overview (MCP)")
- **When to read it**: BEFORE creating tasks, or when you're unsure whether to track work

These guides cover:
- Decision framework for when to create tasks
- Search-first workflow to avoid duplicates
- Links to detailed guides for task creation, execution, and finalization
- MCP tools reference

You MUST read the overview resource to understand the complete workflow. The information is NOT summarized here.

</CRITICAL_INSTRUCTION>

<!-- BACKLOG.MD MCP GUIDELINES END -->
