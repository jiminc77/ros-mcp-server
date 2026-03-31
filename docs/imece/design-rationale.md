# IMECE C0-C2 Design Rationale

This document explains why the IMECE implementation is structured as `C0 -> C1 -> C2`, and why the `C2` helper layer was kept minimal.

`implementation.md` remains the experiment source of truth. This document is the engineering rationale for the implementation and automation choices.

## 1. Core argument

The intended paper argument is:

1. `C0` is the raw generic ROS baseline.
2. `C1` tries to fix the baseline with prompt context only.
3. `C2` is introduced only after repeated discovery evidence shows that prompt context alone does not fix the transport and safety failures.

The important point is that `C2` was not designed first and then justified later. It was frozen only after repeated discovery failures in `C0/C1` established what prompt-only guidance could and could not repair.

## 2. Why C0 still contains a connection instruction

`C0` is not supposed to include drone-operation hints, but it still needs to be runnable as an agent condition rather than an impossible blind baseline.

That is why [`config/imece/c0.md`](../../config/imece/c0.md) includes only one extra instruction:

- connect to the robot through the ROS MCP surface
- inspect the approved topics or services before attempting the task

This does not teach flight policy. It only ensures the agent can discover the existing ROS surface and actually begin the task.

## 3. Why C1 is exactly five facts

`C1` is intentionally narrow. [`config/imece/c1.md`](../../config/imece/c1.md) contains only the five operational facts allowed by the specification:

- local position is `ENU`
- `OFFBOARD` requires setpoint prestream before mode switch
- setpoint streaming must continue during flight
- ambiguity should trigger a short clarification question
- final descent should prefer `LAND` mode

The reason for keeping `C1` this small is methodological:

- if `C1` works, then prompt context alone is enough
- if `C1` still fails, the remaining failures are good candidates for a minimal helper layer

The purpose of `C1` is therefore not “best possible prompt engineering.” It is “smallest allowed prompt-only repair.”

## 4. Discovery evidence that motivated C2

The live discovery artifacts are under `artifacts/imece/live-discovery-v2/`.

Representative failures:

- `C0/T1/episode-01/metrics.json`
  - `failure_codes = ["F4", "F5"]`
  - `max_setpoint_gap_s = 23.80`
  - `offboard_rejection_count = 2`
  - `timed_out = true`
  - `watchdog_triggered = true`
- `C1/T1/episode-01/metrics.json`
  - `failure_codes = ["F2", "F4", "F5"]`
  - `invalid_tool_call_count = 3`
  - `setpoint_count = 2`
  - `max_altitude_m = 0.0278`
  - `timed_out = true`
- `C1/T1/episode-02/metrics.json`
  - `failure_codes = ["F2", "F4", "F5"]`
  - `invalid_tool_call_count = 2`
  - `setpoint_count = 2`
  - `offboard_rejection_count = 1`
  - `timed_out = true`

The critical qualitative observation from the `C1` logs was:

- the model explicitly reasoned about prestream and continuous streaming
- but the generic `publish_for_durations` surface still caused sparse setpoint output in practice

Example from `C1/T1/episode-02/gemini.jsonl`:

- the agent says it will “stream a 0-meter altitude setpoint for 2 seconds to satisfy the OFFBOARD prestream requirement”
- the tool result shows `published_count = 1`
- it then says it will “start a 15-second 1-meter altitude stream”
- the tool result again shows `published_count = 1`

That is the exact point of the staged argument:

- `C1` improved reasoning
- `C1` did not solve the transport/timing mechanism itself

## 5. Why the frozen C2 layer is minimal

The helper freeze output is stored in [`config/imece/c2_freeze.json`](../../config/imece/c2_freeze.json):

- repeated `F4` after `C1` selected `setpoint_relay`
- repeated `F4` mode-transition failures selected `mode_guard`
- at least one unsafe timeout/abort selected `abort_watchdog`
- no repeated `F3` evidence meant `frame_guard` was not frozen into the selected subset

This is important for the paper narrative. The chosen subset is not a convenience bundle. Each helper is tied to a repeated failure class:

- `setpoint_relay`
  - repairs sparse or interrupted setpoint streaming
  - keeps the last valid target alive at `20 Hz`
- `mode_guard`
  - repairs ordering failures around `prestream -> OFFBOARD -> arm`
  - exposes only guarded offboard engage and land
- `abort_watchdog`
  - repairs timeout and abort safety gaps
  - forces `LAND` when the runner heartbeat stops or an abort flag is raised

The omitted helper is equally important:

- `frame_guard` stayed out of the frozen subset because repeated discovery evidence for `F3` did not materialize

This omission supports the “minimal intervention” claim.

## 6. Why C2 prompt text is separated into callable tools and runtime safeguards

The `C2` prompt builder in `ros_mcp/imece/config.py` separates:

- callable helper tools
- active runtime safeguards

This matters because:

- `setpoint_relay` and `mode_guard` are tools the agent can call
- `abort_watchdog` is active runtime behavior, not a callable primitive

Without that separation, the prompt would incorrectly suggest that all selected helpers are agent-facing tools, which would blur the experiment boundary.

## 7. Evidence that C2 can repair the specific failure mode

The successful smoke artifact is `artifacts/imece/c2-smoke-v2/C2/T1/episode-01/`.

In that run:

- the agent used `setpoint_relay` to establish a persistent local pose target
- `mode_guard` waited for `prestream_publishes = 21` before engaging `OFFBOARD` and arming
- the final metrics recorded:
  - `task_success = true`
  - `failure_codes = []`
  - `max_altitude_m = 1.022`
  - `max_setpoint_gap_s = 0.101`
  - `invalid_tool_call_count = 0`

That is exactly the intended claim for `C2`:

- it is not a semantic mission API
- it is the smallest low-level repair that closes the specific gap left by `C1`

## 8. Experiment counts from the specification

Fixed counts from `implementation.md`:

- discovery pilot
  - `C0`, `C1`
  - `T1-T4`
  - `5` repetitions each
  - total: `2 x 4 x 5 = 40`
- one `C2` freeze-validation batch
  - `C2`
  - `T1-T3`
  - `5` repetitions each
  - total: `1 x 3 x 5 = 15`
- official simulation
  - `C0`, `C1`, `C2`
  - `T1-T4`
  - `10` repetitions each
  - total: `3 x 4 x 10 = 120`
- official real flight
  - promoted condition only
  - `R1`, `R2`
  - `5` repetitions each
  - total: `1 x 2 x 5 = 10`

Fixed total with one `C2` freeze-validation batch:

- simulation before real flight: `40 + 15 + 120 = 175`
- including official real flight: `175 + 10 = 185`

Each additional `C2` freeze-validation batch adds `15` more episodes.

## 9. Automation design

The runner now supports:

- `plan-study`
  - computes official counts from the specification
- `run-phase`
  - runs `discovery`, `c2_freeze`, or `official_sim` by name
- `run-batch --resume`
  - resumes an interrupted batch from the remaining episodes
- `run-batch --retry-at-end`
  - finishes a first pass, then retries infrastructure-failed episodes
- `run-batch --max-attempts N`
  - caps retry count per episode

The state file is `artifacts/imece/<batch_id>/batch_state.json`.

This file tracks:

- planned episode matrix
- attempts per episode
- completed vs infrastructure-failed vs exhausted status
- last error and latest artifact directory

The retry logic is intentionally narrow:

- task failures remain task failures
- only infrastructure failures should be retried or resumed

That separation matters for the paper. A control failure must remain evidence. A model-transport or connector failure should not silently contaminate the task metrics.
