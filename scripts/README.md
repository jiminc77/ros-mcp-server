## Prompt/Tool Timing Automation

```bash
cd /<ABSOLUTE_PATH>/ros-mcp-server
./scripts/run_gemini_with_timing.sh
```

The wrapper keeps normal Gemini CLI behavior, and only adds telemetry env vars:
- `GEMINI_TELEMETRY=true`
- `GEMINI_TELEMETRY_TARGET=local`
- `GEMINI_TELEMETRY_OUTFILE=<session_raw_log>`

### Generated logs

By default logs are written to:
`~/.gemini/timing_logs/<session_id>/`

Files:
- `telemetry_raw.jsonl` (raw telemetry for analysis)
- `session_report.txt` (human-readable summary)
- `session_report.json` (structured summary)

`session_report.txt` includes:
- Prompt start/end timestamps (`enter` -> `done`)
- Prompt elapsed time
- Tool call name and start/end timestamps
- Tool call elapsed time and status

Environment overrides:
- `GEMINI_TIMING_LOG_DIR` to change log output root directory
- `GEMINI_BIN` to use a non-default Gemini executable
- `GEMINI_DEFAULT_ARGS` to set default Gemini CLI args (default: `--yolo`)

---

## Batch Experiment Automation (Gemini + rosbag)

`run_experiment_batch.py` automates repeated experiment runs with:
- automatic `RUN_ID` generation
- automatic folder creation
- automatic `ros2 bag record` start/stop
- automatic Gemini telemetry collection via `run_gemini_with_timing.sh`
- resume support (skip completed runs)

### Profile file

Default profile:
- `scripts/experiment_profiles.json`

It defines:
- task/condition/environment mapping
- canonical prompt per task
- topic list to record for rosbag
- suggested timeout per task

Action notes:
- For ROS 2 actions, prefer recording `/_action/status` and `/_action/feedback` topics.

### Basic usage

```bash
cd /<ABSOLUTE_PATH>/ros-mcp-server
./scripts/run_experiment_batch.sh \
  --task T1-2 \
  --condition C2 \
  --env sim \
  --repeats 20
```

When each run starts:
1. rosbag recording starts automatically.
2. Gemini CLI opens automatically (`--yolo` by default).
3. You interact in Gemini, then exit Gemini.
4. rosbag stops and artifacts are saved.
5. Next run starts.

Default Gemini args:
- `--gemini-args "--yolo"`

Override example:

```bash
./scripts/run_experiment_batch.sh \
  --task T1-2 \
  --condition C2 \
  --env sim \
  --repeats 20 \
  --gemini-args "--yolo --model gemini-2.5-pro"
```

### Resume usage

If the batch stops at run 4, restart with:

```bash
./scripts/run_experiment_batch.sh \
  --task T1-2 \
  --condition C2 \
  --env sim \
  --repeats 20 \
  --resume
```

Completed runs are preserved and skipped.

### Start from specific run index

```bash
./scripts/run_experiment_batch.sh \
  --task T2 \
  --condition P2 \
  --env real \
  --repeats 10 \
  --from-run 4 \
  --gemini-args "--yolo"
```

### Output structure

Artifacts are stored under:
- `experiments/<task>/<condition>/<env>/`

Per run:
- `experiments/<task>/<condition>/<env>/<RUN_ID>/status.json`
- `experiments/<task>/<condition>/<env>/<RUN_ID>/run_meta.json`
- `experiments/<task>/<condition>/<env>/<RUN_ID>/attempts/attempt_XXX/`
  - `rosbag/` (contains `metadata.yaml`)
  - `gemini/session_report.json`
  - `gemini/session_report.txt`
  - `gemini/telemetry_raw.jsonl`

Batch manifest:
- `experiments/<task>/<condition>/<env>/manifest.jsonl`

### Validate artifacts

```bash
python3 ./scripts/check_run_artifacts.py \
  --run-dir experiments/T1-2/C2/sim/T1-2_C2_SIM_004
```

Or validate a specific attempt:

```bash
python3 ./scripts/check_run_artifacts.py \
  --attempt-dir experiments/T1-2/C2/sim/T1-2_C2_SIM_004/attempts/attempt_001
```

### Notes

- Required commands: `ros2`, `gemini`, `python3`
- The batch runner is stop-on-failure by default.
- Use `--continue-on-failure` if you want to keep going after a failed run.
- You can override Gemini binary with `GEMINI_BIN`.
