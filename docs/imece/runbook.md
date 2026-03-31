# IMECE Runbook

This runbook keeps the IMECE additions reproducible without changing upstream `ros-mcp` defaults.

## Project MCP setup

```bash
./scripts/imece/setup_gemini_project_mcp.sh
```

This writes a project-scoped `.gemini/settings.json` that points Gemini CLI at the repo-local `ros_mcp.imece.server` entrypoint. The file is intentionally gitignored.

## Start the simulation stack

```bash
./scripts/imece/start_sim_stack.sh
```

This launches:

- `make px4_sitl gz_x500` from `/home/husl-ai/workspace/PX4-Autopilot`
- `ros2 launch mavros px4.launch fcu_url:=udp://:14540@127.0.0.1:14557`
- `ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=9090`

QGroundControl remains optional and manual.

## Run discovery

Single episode:

```bash
uv run python -m ros_mcp.imece.runner run-episode --condition C0 --task T1 --episode-index 1
```

Discovery batch:

```bash
uv run python -m ros_mcp.imece.runner run-phase discovery \
  --batch-id discovery-001 \
  --resume \
  --max-attempts 3
```

The runner now prints live terminal progress by default:

- batch start and resume summary
- episode start and end
- failure summary and infrastructure error detail
- quota warnings detected in `gemini.stderr.log`

Use `--no-progress` to suppress terminal output and rely only on artifacts.

Artifacts are written under `artifacts/imece/<batch_id>/...` and include:

- `batch_state.json`
- `prompt.txt`
- `gemini.jsonl`
- `monitor.jsonl`
- `metadata.json`
- `metrics.json`
- `rosbag/`

## Analyze an existing batch

```bash
uv run python -m ros_mcp.imece.runner analyze-batch \
  --batch-dir artifacts/imece/<batch_id> \
  --write-freeze
```

This updates each `metrics.json` with `failure_codes` and writes batch-level helper selection output.

## Plan the full study

```bash
uv run python -m ros_mcp.imece.runner plan-study
```

This prints the official episode counts from the experiment specification, including:

- discovery: `40`
- one `C2` freeze-validation batch: `15`
- official simulation: `120`
- official real-flight: `10`
- fixed total with one `C2` freeze batch: `185`

## Retry and resume behavior

- `run-batch` and `run-phase` write `batch_state.json`
- completed episodes are skipped on `--resume`
- infrastructure failures are marked separately from task failures
- `--retry-at-end` retries infrastructure-failed episodes after the first pass
- `--max-attempts N` limits retries per episode

Example explicit batch run:

```bash
uv run python -m ros_mcp.imece.runner run-batch \
  --conditions C0 C1 \
  --tasks T1 T2 T3 T4 \
  --repetitions 5 \
  --batch-id live-discovery-v3 \
  --resume \
  --retry-at-end \
  --max-attempts 3 \
  --freeze-c2
```

## Current assumptions

- The runner uses fresh non-interactive Gemini turns plus `--resume` for continuation. For `T3`, the first turn pauses at the halfway hold and ends with `CLARIFY`; the scheduled `Stop there.` or `Land now.` correction prompt is then sent as the next turn in the same session.
- `frame_guard` and `abort_watchdog` are implemented as helper-runtime behavior. The visible helper tools are `setpoint_relay` and `mode_guard`.
- `c2_freeze.json` is the freeze artifact consumed by `C2` runs.
