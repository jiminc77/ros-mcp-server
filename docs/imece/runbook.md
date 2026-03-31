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

For `T3`, `metrics.json` now records whether the logged pose path actually reached the five expected square waypoints in order:

- `square_waypoints_reached`
- `square_pattern_complete`

The current generic verification tool also returns compact subscription payloads with `first_msg`, `last_msg`, and `summary` so long pose windows do not flood the model context.

## Analyze an existing batch

```bash
uv run python -m ros_mcp.imece.runner analyze-batch \
  --batch-dir artifacts/imece/<batch_id> \
  --write-freeze
```

This updates each `metrics.json` with `failure_codes` and writes batch-level helper selection output.

To write the fairness and reproducibility audit alongside the batch analysis:

```bash
uv run python -m ros_mcp.imece.runner audit-batch \
  --batch-dir artifacts/imece/<batch_id>
```

`run-batch` and `run-phase` also write `audit.json` automatically after the batch analysis step.

## Plan the full study

```bash
uv run python -m ros_mcp.imece.runner plan-study
```

This prints the official episode counts from the experiment specification, including:

- discovery: `40`
- one `C2` freeze-validation batch: `20`
- official simulation: `120`
- official real-flight: `10`
- fixed total with one `C2` freeze batch: `190`

## Run official simulation

```bash
uv run python -m ros_mcp.imece.runner run-phase official_sim \
  --batch-id official-sim-001 \
  --resume \
  --max-attempts 3
```

This should be started only after documenting the preserved staged argument honestly:

- discovery justifies the frozen `C2` subset
- the preserved targeted `C2:T3` batch closes the last remaining final-task gap
- this is still narrower than a claim of full `C2` validation across `T1-T4`

## Run one real-flight episode

```bash
uv run python -m ros_mcp.imece.runner run-real-episode \
  --condition C2 \
  --task R1 \
  --episode-index 1 \
  --batch-id official-real-r1-001
```

Use the promoted condition for `--condition`. This scaffold:

- builds the same full first-turn prompt used in simulation
- runs Gemini CLI non-interactively in a fresh headless session
- records `prompt.txt`, `gemini.jsonl`, `monitor.jsonl`, `metadata.json`, and `metrics.json`
- checks for a connected, landed, disarmed, upright preflight baseline before starting

It does not batch multiple real flights and does not replace operator go/no-go judgment.

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

- The runner uses fresh non-interactive Gemini turns plus `--resume` for continuation. For `T4` mid-flight interrupt handling, the first turn pauses at the halfway hold and ends with `CLARIFY`; the scheduled `Stop there.` or `Land now.` correction prompt is then sent as the next turn in the same session.
- The current frozen `C2` subset is `setpoint_relay`, `mode_guard`, and `abort_watchdog`.
- The runner loads missing variables from the repo-local `.env` file before launching Gemini CLI, so `GEMINI_API_KEY=...` can live in `.env` without manual export.
- `abort_watchdog` is implemented as helper-runtime behavior. The visible helper tools are `setpoint_relay` and `mode_guard`.
- `c2_freeze.json` is the freeze artifact consumed by `C2` runs.
