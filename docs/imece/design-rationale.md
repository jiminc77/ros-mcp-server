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

The completed discovery batch is under `artifacts/imece/discovery-20260331/`.

That batch contains:

- `40` completed discovery episodes
- `0` infrastructure failures
- the full discovery matrix: `C0`, `C1` x `T1-T4` x `5` repetitions

Representative failures:

- `C0/T1/episode-01/metrics.json`
  - `failure_codes = ["F2", "F4", "F5"]`
  - `max_setpoint_gap_s = 25.00`
  - `offboard_rejection_count = 4`
  - `timed_out = true`
  - `watchdog_triggered = true`
- `C1/T1/episode-01/metrics.json`
  - `failure_codes = ["F2", "F4", "F5"]`
  - `invalid_tool_call_count = 4`
  - `setpoint_count = 60`
  - `max_altitude_m = 1.9835`
  - `timed_out = true`
- `C1/T1/episode-02/metrics.json`
  - `failure_codes = ["F2", "F4"]`
  - `invalid_tool_call_count = 2`
  - `setpoint_count = 4`
  - `offboard_rejection_count = 2`
  - `max_altitude_m = 0.0291`

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

The helper freeze output is stored in [`config/imece/c2_freeze.json`](../../config/imece/c2_freeze.json), but the discovery batch analysis is the source of truth that produces it:

- repeated `F4` after `C1` selected `setpoint_relay`
- repeated `F4` mode-transition failures selected `mode_guard`
- at least one unsafe timeout/abort selected `abort_watchdog`

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

The preserved discovery audit now matters here. It shows:

- many preserved discovery failures contain historical generic-tool schema mismatch
- repeated explicit frame/sign failures are not present under the current classifier

So the current paper-safe frozen subset is:

- `setpoint_relay`
- `mode_guard`
- `abort_watchdog`

`frame_guard` is still implemented in the codebase as an available helper, but it is not part of the currently frozen subset and should not be described as discovery-frozen evidence.

Minimality still matters here. The discovery batch froze only the helpers backed by repeated post-`C1` evidence. No extra semantic takeoff, goto, or mission-level abstraction was added.

## 6. Why C2 prompt text is separated into callable tools and runtime safeguards

The `C2` prompt builder in `ros_mcp/imece/config.py` separates:

- callable helper tools
- active runtime safeguards

This matters because:

- `setpoint_relay` and `mode_guard` are tools the agent can call
- `abort_watchdog` is active runtime behavior, not a callable primitive

Without that separation, the prompt would incorrectly suggest that all selected helpers are agent-facing tools, which would blur the experiment boundary.

## 7. What discovery justifies, and what comes next

`discovery-20260331` justifies the frozen `C2` subset. It does not by itself replace the dedicated `C2` confirmation stage.

The current preserved confirmation artifact is the targeted `c2-freeze-t3-20260331` validation batch, which runs with this exact frozen subset:

- `setpoint_relay`
- `mode_guard`
- `abort_watchdog`

That preserved stage supports one narrow claim: the remaining `T3` square-pattern gap was repaired under the frozen subset. It does not yet support the broader claim that `C2` has been fully validated across all of `T1-T4`.

The regenerated `T3` square-pattern discovery evidence does not currently justify a new helper class. It continues to fail through the same transport/timing and timeout modes already captured by `setpoint_relay`, `mode_guard`, and `abort_watchdog`. What it does change is the freeze-validation scope: because `T3` is now a core study task rather than the removed ambiguity probe, `c2_freeze` must also validate `T3`. `T3` is now judged from the logged pose path itself, not only from coarse span metrics, so the square must actually reach the takeoff hold, three corners, and return hold in order.

Before `official_sim`, the shared generic surface was stabilized in two narrow, non-semantic ways:

- generic tools now tolerate stray `wait_for_previous` fields instead of failing on interface drift
- `subscribe_for_duration` now returns a compact summary with `first_msg`, `last_msg`, and `summary` so the model does not waste context on long pose dumps

This does not change the preserved discovery argument. It means only that the official comparison phase can start from a stable shared interface across all conditions.

## 8. Experiment counts from the specification

Fixed counts from `implementation.md`:

- discovery pilot
  - `C0`, `C1`
  - `T1-T4`
  - `5` repetitions each
  - total: `2 x 4 x 5 = 40`
- one `C2` freeze-validation batch
  - `C2`
  - `T1-T4`
  - `5` repetitions each
  - total: `1 x 4 x 5 = 20`
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

- simulation before real flight: `40 + 20 + 120 = 180`
- including official real flight: `180 + 10 = 190`

Each additional `C2` freeze-validation batch adds `20` more episodes.

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
