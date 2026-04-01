# IMECE Runbook

This document explains how to execute each IMECE study step on the current machine and what the runner arguments mean.

Use this file for:

- environment bring-up
- batch and episode execution commands
- argument meanings
- artifact inspection workflow

Use [`implementation.md`](./implementation.md) for the normative study design.
Use [`experiment-record.md`](./experiment-record.md) for preserved results and interpretation.

## 1. Before Running Anything

### Project MCP Setup

```bash
./scripts/imece/setup_gemini_project_mcp.sh
```

This writes a project-scoped `.gemini/settings.json` that points Gemini CLI at the IMECE server entrypoint.
That file is local to the repo checkout.

### Start the Simulation Stack

```bash
./scripts/imece/start_sim_stack.sh
```

This starts:

- `PX4 SITL`
- `MAVROS`
- `rosbridge_websocket`

To stop it:

```bash
./scripts/imece/stop_sim_stack.sh
```

QGroundControl is optional and manual.

## 2. Runner Command Map

The runner entrypoint is:

```bash
uv run python -m ros_mcp.imece.runner
```

Available subcommands:

- `run-episode`
- `run-real-episode`
- `run-batch`
- `run-phase`
- `analyze-batch`
- `audit-batch`
- `plan-study`

## 3. Common Arguments

These arguments appear on most execution commands.

| Argument | Meaning |
| --- | --- |
| `--cwd` | working directory used when launching Gemini CLI and local scripts |
| `--output-root` | artifact root directory; default batch outputs go under `artifacts/imece/` |
| `--policy-path` | Gemini tool policy file, normally `config/imece/gemini-policy.toml` |
| `--freeze-path` | frozen helper subset file, normally `config/imece/c2_freeze.json` |
| `--gemini-binary` | Gemini CLI binary to execute |
| `--rosbridge-ip` | rosbridge host |
| `--rosbridge-port` | rosbridge port |
| `--timeout` | per-episode hard timeout in seconds |
| `--watchdog-timeout` | helper-side abort watchdog timeout in seconds |
| `--batch-id` | name of the output batch directory |
| `--clean-existing` | remove an existing episode directory before rerunning that episode |
| `--progress` / `--no-progress` | enable or suppress terminal progress logs |

## 4. Batch-control Arguments

These matter for `run-batch` and `run-phase`.

| Argument | Meaning |
| --- | --- |
| `--conditions` | explicit condition list for a custom batch |
| `--tasks` | explicit task list for a custom batch |
| `--repetitions` | repetitions per condition-task pair for a custom batch |
| `--freeze-c2` | write updated helper-freeze output after successful analysis |
| `--resume` | continue from `batch_state.json` and skip completed episodes |
| `--max-attempts` | cap retry attempts for infrastructure-failed episodes |
| `--retry-at-end` / `--no-retry-at-end` | run a second pass over infrastructure-failed episodes after the first pass |

`--freeze-c2` is for analysis output management. It is not permission to change the study design mid-phase.

## 5. Analysis-command Arguments

| Command | Argument | Meaning |
| --- | --- | --- |
| `analyze-batch` | `--batch-dir` | batch directory to analyze |
| `analyze-batch` | `--freeze-path` | where to write the freeze mirror if `--write-freeze` is used |
| `analyze-batch` | `--write-freeze` | sync the discovery helper selection into `c2_freeze.json` |
| `audit-batch` | `--batch-dir` | batch directory to audit |
| `audit-batch` | `--write-path` | custom output path for `audit.json` |
| `plan-study` | `--write-path` | optional output file for the study plan summary |

## 6. Discovery

### Standard Phase Command

```bash
uv run python -m ros_mcp.imece.runner run-phase discovery \
  --batch-id discovery-001 \
  --resume \
  --max-attempts 3
```

What it runs:

- conditions: `C0`, `C1`
- tasks: `T1`, `T2`, `T3`, `T4`
- repetitions: `5`

Use discovery to:

- measure the raw baseline and prompt-only repair
- decide whether `C2` is justified
- generate helper freeze evidence

### One-off Discovery Episode

```bash
uv run python -m ros_mcp.imece.runner run-episode \
  --condition C0 \
  --task T1 \
  --episode-index 1 \
  --batch-id scratch-discovery
```

Use this only for debugging or ad hoc inspection, not for preserved paper evidence unless the batch is intentionally retained.

## 7. C2 Freeze

### Standard Full C2 Freeze Phase

```bash
uv run python -m ros_mcp.imece.runner run-phase c2_freeze \
  --batch-id c2-freeze-001 \
  --resume \
  --max-attempts 3
```

This is the symmetric full `C2 x T1-T4 x 5` batch shape.

### Targeted C2 Validation for T3

The current preserved `C2` evidence is narrower and uses a custom batch:

```bash
uv run python -m ros_mcp.imece.runner run-batch \
  --conditions C2 \
  --tasks T3 \
  --repetitions 5 \
  --batch-id c2-freeze-t3-001 \
  --resume \
  --retry-at-end \
  --max-attempts 3
```

Use this targeted form only when the goal is explicitly to validate the remaining `T3` gap under the already frozen subset.

## 8. Official Simulation

```bash
uv run python -m ros_mcp.imece.runner run-phase official_sim \
  --batch-id official-sim-001 \
  --resume \
  --max-attempts 3
```

What it runs:

- conditions: `C0`, `C1`, `C2`
- tasks: `T1`, `T2`, `T3`, `T4`
- repetitions: `10`

Before running `official_sim`, make sure:

- the frozen subset is the intended one in `config/imece/c2_freeze.json`
- the prompt and policy files are fixed
- the documentation already states the current evidence honestly

## 9. Official Real Flight

There is no batch-level `official_real` phase command yet.
Current real flight is one episode at a time, but the intended preserved matrix is:

- condition: `C2`
- tasks: `T1`, `T2`, `T3`, `T4`
- repetitions: `5` each
- total: `20`

Single-episode command:

```bash
uv run python -m ros_mcp.imece.runner run-real-episode \
  --condition C2 \
  --task T1 \
  --episode-index 1 \
  --batch-id official-real-001
```

To preserve the full 20-episode real-flight batch under one batch ID:

```bash
for task in T1 T2 T3 T4; do
  for i in 1 2 3 4 5; do
    uv run python -m ros_mcp.imece.runner run-real-episode \
      --condition C2 \
      --task "${task}" \
      --episode-index "${i}" \
      --batch-id official-real-001
  done
done
```

Important:

- keep the same `--batch-id` across all 20 episodes if they belong to one preserved official real-flight batch
- use `T1`, `T2`, `T3`, or `T4`
- keep operator go/no-go judgment manual
- keep RC or QGroundControl takeover available

Do not treat repeated manual `run-real-episode` calls as an official real-flight batch unless you preserve them deliberately as one coherent real-flight batch record.

## 10. Analyze and Audit a Batch

### Analyze

```bash
uv run python -m ros_mcp.imece.runner analyze-batch \
  --batch-dir artifacts/imece/<batch_id> \
  --write-freeze
```

Use `--write-freeze` only when the batch is intended to define or update the frozen subset.

### Audit

```bash
uv run python -m ros_mcp.imece.runner audit-batch \
  --batch-dir artifacts/imece/<batch_id>
```

`run-batch` and `run-phase` already write `analysis.json` and `audit.json` automatically after the batch completes.
Manual re-analysis is for post hoc updates or explicit re-auditing.

## 11. Plan the Study

```bash
uv run python -m ros_mcp.imece.runner plan-study
```

This prints the official episode counts implied by the current specification.

## 12. Artifact Layout

Each batch writes:

- `batch_state.json`
- `analysis.json`
- `audit.json`

Each episode writes:

- `prompt.txt`
- `gemini.jsonl`
- `gemini.stderr.log`
- `monitor.jsonl`
- `metrics.json`
- `metadata.json`
- `rosbag/`

## 13. What to Check After a Run

### First Check

- `batch_state.json`
  - completed count
  - infra error count
  - exhausted count

### Second Check

- `analysis.json`
  - task success summary
  - helper freeze review
  - failure counts

### Third Check

- `audit.json`
  - historical interface mismatch
  - stored-vs-current task-success drift
  - runtime metadata coverage

### Fourth Check

- representative `metrics.json` files
- `prompt.txt`
- `gemini.jsonl`

## 14. Resume and Retry Behavior

- `--resume` skips completed episodes and continues from `batch_state.json`
- task failures remain task failures
- only infrastructure failures should be retried
- `--retry-at-end` performs a second pass over infrastructure-failed episodes
- `--max-attempts` limits how many times an infrastructure-failed episode can be retried

This separation matters. Control failures are evidence. Connector or execution-transport failures are retry candidates.

## 15. Current Assumptions

- the current frozen `C2` subset is `setpoint_relay`, `mode_guard`, `abort_watchdog`
- `abort_watchdog` is runtime behavior, not an agent-callable semantic tool
- the runner loads missing variables from repo-local `.env` before launching Gemini CLI
- `T4` uses a two-turn pattern in one Gemini session
- `subscribe_for_duration` returns compact summaries rather than flooding the model context
