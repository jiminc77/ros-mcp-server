# IMECE Experiment Record

This document records what was actually run, what was preserved, how those artifacts were analyzed, and what paper claims are supported by the preserved evidence.

Use this file for:

- preserved batch history
- the exact condition and prompt setup used in preserved evidence
- machine-generated summaries and how they should be read
- paper-safe result statements and current limitations

[`implementation.md`](./implementation.md) remains the normative specification.
If the two documents diverge, this file should explain the preserved reality and `implementation.md` should explain the intended rule.

## 1. Preserved Evidence Boundary

The following preserved batches are the current paper-facing evidence:

| Batch ID | Phase meaning | Preserved purpose | Artifact root |
| --- | --- | --- | --- |
| `discovery-20260331` | discovery pilot | determine whether `C2` is needed and which helpers can be frozen | `artifacts/imece/discovery-20260331/` |
| `c2-freeze-t3-20260331` | targeted `C2` validation | validate the remaining `T3` square-pattern gap under the frozen `C2` subset | `artifacts/imece/c2-freeze-t3-20260331/` |
| `official-sim-001` | official simulation evaluation | compare `C0`, `C1`, and `C2` head-to-head on the final `T1-T4` task set | `artifacts/imece/official-sim-001/` |

These are the only preserved batches that should be cited as direct evidence in the paper right now.

Deleted ad hoc runs and superseded internal runs are not part of the paper-facing argument and should not be reconstructed into tables or claims.

## 2. Machine-generated Analysis Outputs

Each preserved batch has:

- `analysis.json`
  - batch summary under current scoring
  - helper freeze review
  - task success summary
- `audit.json`
  - historical interface mismatch counts
  - stored-vs-current task-success drift
  - reproducibility metadata coverage

Important differences across preserved batches:

- preserved discovery predates top-level runtime metadata capture
- preserved `c2-freeze-t3-20260331` has complete per-episode `runtime_metadata`
- preserved `official-sim-001` has complete per-episode `runtime_metadata` and no historical interface mismatch contamination

## 3. Current Study Snapshot

### Conditions

- `C0`: generic ROS-MCP baseline
- `C1`: prompt-only operational facts on the same generic surface
- `C2`: same generic surface plus the frozen minimal helper subset

### Tasks

- simulation:
  - `T1`: Takeoff Hover Land
  - `T2`: Short Translation
  - `T3`: Square Pattern Flight
  - `T4`: Mid-flight Interrupt Handling
- planned real flight:
  - `C2` only
  - `T1-T4`
  - `5` repetitions per task
  - total `20` episodes

### Historical Note

An earlier ambiguity-oriented draft task was retired.
The preserved final mapping is:

- `T3 = Square Pattern Flight`
- `T4 = Mid-flight Interrupt Handling`

The paper should use only this final mapping.

## 4. Condition Record

### C0

Condition artifact: [`config/imece/c0.md`](../../config/imece/c0.md)

What the agent receives:

- condition name
- instruction to use only the exposed IMECE tools
- instruction to inspect the approved ROS surface first

Why this matters:

- `C0` is a runnable generic baseline
- it is not a drone-aware baseline
- it is not an impossible blind baseline

### C1

Condition artifact: [`config/imece/c1.md`](../../config/imece/c1.md)

Additional prompt facts:

- local position is `ENU`
- `OFFBOARD` requires setpoint prestream before mode switch
- setpoint streaming must continue during flight
- ambiguity should trigger a short clarification question
- final descent should prefer `LAND` mode

Why this matters:

- `C1` is the smallest prompt-only repair
- if `C1` had repaired the failures, `C2` would not be justified

### C2

Condition artifacts:

- [`config/imece/c2.md`](../../config/imece/c2.md)
- [`config/imece/c2_freeze.json`](../../config/imece/c2_freeze.json)

Current frozen helper subset:

- `setpoint_relay`
- `mode_guard`
- `abort_watchdog`

Important qualification:

- `frame_guard` exists in code but is not part of the currently frozen subset
- the preserved discovery audit does not show repeated explicit frame/sign failures under the current classifier

This is the paper-safe way to describe `C2`:

- a frozen minimal low-level helper subset
- not a semantic drone API layer
- not a mission planner

## 5. Why `C0 -> C1 -> C2` Was Designed This Way

The staged condition design was not chosen abstractly. It was chosen because the preserved discovery traces showed a specific progression.

| Condition | Preserved log evidence | Design implication |
| --- | --- | --- |
| `C0` | [`C0/T1/episode-01/metrics.json`](../../artifacts/imece/discovery-20260331/C0/T1/episode-01/metrics.json) records `44` tool calls, `9` setpoints, `max_altitude_m = 0.0245`, `offboard_rejection_count = 4`, `timed_out = true`, `watchdog_triggered = true`. | `C0` needed to remain runnable as a generic ROS baseline, not an impossible blind baseline. |
| `C1` | [`C1/T1/episode-02/gemini.jsonl`](../../artifacts/imece/discovery-20260331/C1/T1/episode-02/gemini.jsonl) shows the model explicitly reasoning about prestream and continuous streaming, but the preserved tool outputs contain `wait_for_previous` validation drift and later only `published_count = 1` for multi-second publish windows. [`metrics.json`](../../artifacts/imece/discovery-20260331/C1/T1/episode-02/metrics.json) records `setpoint_count = 4` and `max_altitude_m = 0.0291`. | `C1` had to remain the smallest prompt-only repair so the study could show that reasoning improved while the mechanism still failed. |
| `C2` | Discovery freezes only `setpoint_relay`, `mode_guard`, and `abort_watchdog`; targeted `C2:T3` then validates the remaining square-pattern gap; later `official-sim-001` shows `C2` removing the recurrent `F1-F5` pattern while leaving only a few task-criterion misses. | `C2` had to be a thin low-level stabilization layer, not a semantic mission interface. |

Three design points matter for the paper narrative:

- `C0` still includes connection/discovery because otherwise the baseline would collapse into blind failure rather than generic ROS-level interaction.
- `C1` is intentionally narrow because the study needs a clean prompt-only repair attempt, not an unconstrained prompting contest.
- `C2` was frozen only after discovery showed that prompt context alone did not fix the transport/timing and abort path.

The preserved `C1/T1/episode-02` trace is the clearest justification for the transition from `C1` to `C2`. The model says it will prestream setpoints and maintain streaming, but the preserved tool results either fail on historical schema drift or report only one published setpoint for a multi-second publish window. This is why the paper-safe discovery conclusion is:

- `C1` improved reasoning
- `C1` did not reliably repair the mechanism
- the remaining gap justified a thin helper layer tied only to transport and safety

## 6. Prompt Assembly and Task Prompt Record

The first-turn prompt is assembled by [`ros_mcp/imece/config.py`](../../ros_mcp/imece/config.py) in this order:

1. shared contract
2. condition artifact
3. `C2` helper block if the condition is `C2`
4. task-specific execution block if the task has one
5. episode metadata
6. canonical task prompt

This matters experimentally because each episode preserves the exact delivered text in `prompt.txt`.

### Shared Contract Held Constant

Across the preserved runs, the first-turn prompt keeps these shared requirements:

- use only the exposed IMECE tools
- ask one short clarification question if necessary
- refuse briefly if the request cannot be completed safely
- end every turn with exactly one of `CLARIFY: ...`, `REFUSE: ...`, or `DONE: ...`

### Task Prompt Record

| Task | Title | Canonical prompt | Experimentally important task-specific setting |
| --- | --- | --- | --- |
| `T1` | Takeoff Hover Land | `Take off to one meter, hover for five seconds, then land.` | no extra task block |
| `T2` | Short Translation | `Take off, move one meter forward, hover, and land.` | exactly two motion targets: takeoff hold, then one-meter-forward hold |
| `T3` | Square Pattern Flight | `Take off, fly a square with one-meter sides, return near the start, and land.` | exactly five start-relative local-pose targets |
| `T4` | Mid-flight Interrupt Handling | `Take off and move forward one meter.` | first turn ends with `CLARIFY`, second turn receives deterministic correction |

Additional task settings held fixed in the preserved study:

- `T2`
  - use exactly two motion targets
  - do not retarget until the takeoff hold is reached
- `T3`
  - derive the square from the first sampled local pose
  - use exactly five motion targets
  - verify through `subscribe_for_duration`
  - emit exactly `DONE: square complete`
- `T4`
  - first turn uses takeoff hold then halfway-forward hold
  - first turn ends with `CLARIFY: awaiting correction`
  - deterministic correction rotation:
    - odd episodes: `Stop there.`
    - even episodes: `Land now.`

## 7. Phase-by-phase Record

### Phase A. Discovery Pilot

Artifact root: [`artifacts/imece/discovery-20260331/`](../../artifacts/imece/discovery-20260331/)

Purpose:

- decide whether generic-only or prompt-only conditions are enough
- identify repeated failure families
- justify or reject a frozen `C2` layer

Matrix:

- conditions: `C0`, `C1`
- tasks: `T1`, `T2`, `T3`, `T4`
- repetitions: `5`
- total: `40`

Preserved summary:

- completed episodes: `40`
- infrastructure failures: `0`
- exhaustion count: `0`

Current-analysis result:

- freeze selection counts:
  - `F2 = 15`
  - `F4 = 18`
  - `F5 = 13`
- historical generic-tool schema mismatch episodes: `30`
- repeated explicit frame/sign error episodes under the current classifier: `0`

Representative baseline failure:

- [`C0/T1/episode-01/metrics.json`](../../artifacts/imece/discovery-20260331/C0/T1/episode-01/metrics.json)
  - `task_success = false`
  - `failure_codes = ["F2", "F4", "F5"]`
  - `max_altitude_m = 0.0245`
  - `max_setpoint_gap_s = 25.00`
  - `offboard_rejection_count = 4`
  - `timed_out = true`
  - `watchdog_triggered = true`

Representative `C1` partial repair:

- [`C1/T1/episode-01/metrics.json`](../../artifacts/imece/discovery-20260331/C1/T1/episode-01/metrics.json)
  - `task_success_current_spec = true`
  - `failure_codes = ["F2", "F4", "F5"]`
  - `max_altitude_m = 1.9835`
  - `max_setpoint_gap_s = 10.14`
  - `offboard_rejection_count = 6`
  - `offboard_drop_count = 2`
  - `timed_out = true`
  - `watchdog_triggered = true`

Critical log-based rationale episode:

- [`C1/T1/episode-02/gemini.jsonl`](../../artifacts/imece/discovery-20260331/C1/T1/episode-02/gemini.jsonl)
  - the model explicitly reasons about prestream and continuous streaming
  - preserved tool results show historical `wait_for_previous` validation drift
  - later successful publish calls still report only `published_count = 1`

How this phase was analyzed:

- current task success is recomputed by shared scoring in [`ros_mcp/imece/scoring.py`](../../ros_mcp/imece/scoring.py)
- failure codes are recomputed by [`ros_mcp/imece/analysis.py`](../../ros_mcp/imece/analysis.py)
- helper selection is taken from `analysis.json.selection`
- fairness and reproducibility caveats are taken from `audit.json`

Discovery conclusion:

- `C1` improved operational reasoning
- `C1` did not repair the low-level mechanism
- repeated post-`C1` transport/timing and safety failures justify a minimal `C2` subset
- current preserved discovery does not justify freezing `frame_guard`

### Phase B. Targeted C2 Validation for T3

Artifact root: [`artifacts/imece/c2-freeze-t3-20260331/`](../../artifacts/imece/c2-freeze-t3-20260331/)

Purpose:

- validate the remaining `T3` square-pattern gap under the frozen `C2` subset

Matrix:

- condition: `C2`
- task: `T3`
- repetitions: `5`
- total: `5`

What was active:

- frozen helper subset from discovery:
  - `setpoint_relay`
  - `mode_guard`
  - `abort_watchdog`
- square-pattern task-specific execution block from the current prompt builder

Preserved summary:

- completed episodes: `5`
- infrastructure failures: `0`
- exhaustion count: `0`

Current-analysis result:

- `freeze_review.status = "validated"`
- `freeze_review.task_success.T3.success = 5`
- `freeze_review.task_success.T3.total = 5`

Reproducibility result:

- episodes with runtime metadata: `5`
- episodes missing runtime metadata: `[]`
- full field coverage for repo commit, ros-mcp repo commit, PX4 commit, Gemini CLI version, routed model, MAVROS version, Gazebo version, and ROS distro

Validation conclusion:

- the frozen `C2` subset closes the remaining preserved `T3` gap
- this is a targeted validation result, not a claim of full `C2:T1-T4` validation

### Phase C. Official Simulation

Artifact root: [`artifacts/imece/official-sim-001/`](../../artifacts/imece/official-sim-001/)

Purpose:

- compare `C0`, `C1`, and `C2` head-to-head under the fixed final task set
- identify the strongest preserved condition to carry forward into the planned `C2` real-flight phase

Matrix:

- conditions: `C0`, `C1`, `C2`
- tasks: `T1`, `T2`, `T3`, `T4`
- repetitions: `10`
- total: `120`

What was held fixed:

- the final task set `T1-T4`
- the frozen helper subset in [`config/imece/c2_freeze.json`](../../config/imece/c2_freeze.json)
- the current shared generic tool surface
- the current prompt assembly logic and Gemini policy

Preserved summary:

- completed episodes: `120`
- infrastructure failures: `0`
- exhaustion count: `0`
- overall pooled success across all conditions: `48/120 = 40.0%`

Initial official comparison from `official-sim-001`:

| Condition | Overall success | `T1` | `T2` | `T3` | `T4` |
| --- | --- | --- | --- | --- | --- |
| `C0` | `6/40 = 15.0%` | `5/10` | `0/10` | `0/10` | `1/10` |
| `C1` | `6/40 = 15.0%` | `6/10` | `0/10` | `0/10` | `0/10` |
| `C2` | `36/40 = 90.0%` | `7/10` | `10/10` | `10/10` | `9/10` |

The pooled `48/120` number is not the main result. The condition-stratified table above is the paper-relevant comparison.

Failure-pattern result in `official-sim-001`:

| Condition | `F1` | `F2` | `F3` | `F4` | `F5` | Historical interface mismatch | Explicit frame/sign error |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `C0` | `2` | `0` | `0` | `39` | `33` | `0` | `0` |
| `C1` | `0` | `2` | `0` | `39` | `32` | `0` | `0` |
| `C2` | `0` | `0` | `0` | `0` | `0` | `0` | `0` |

Reproducibility result in `official-sim-001`:

- episodes with runtime metadata: `120`
- episodes missing runtime metadata: `[]`
- full coverage for repo commit, ros-mcp repo commit, PX4 commit, Gemini CLI version, routed model, MAVROS version, Gazebo version, and ROS distro

Representative successful `C2` episodes that were already stable in `official-sim-001`:

- [`C2/T2/episode-01/metrics.json`](../../artifacts/imece/official-sim-001/C2/T2/episode-01/metrics.json)
  - `task_success = true`
  - `horizontal_displacement_m = 0.9927`
  - `max_altitude_m = 1.0136`
  - `offboard_rejection_count = 0`
  - `offboard_drop_count = 0`
- [`C2/T3/episode-01/metrics.json`](../../artifacts/imece/official-sim-001/C2/T3/episode-01/metrics.json)
  - `task_success = true`
  - `square_pattern_complete = true`
  - `horizontal_displacement_m = 0.0548`
  - `offboard_rejection_count = 0`
  - `offboard_drop_count = 0`

Representative remaining `C2` misses in `official-sim-001`:

- [`C2/T1/episode-04/metrics.json`](../../artifacts/imece/official-sim-001/C2/T1/episode-04/metrics.json)
  - terminal `DONE`, but `max_altitude_m = 0.4477`
  - safe landing happened, but the takeoff criterion itself was not met
- [`C2/T1/episode-06/metrics.json`](../../artifacts/imece/official-sim-001/C2/T1/episode-06/metrics.json)
  - terminal `DONE`, but `max_altitude_m = 0.0728`
- [`C2/T1/episode-09/metrics.json`](../../artifacts/imece/official-sim-001/C2/T1/episode-09/metrics.json)
  - terminal `DONE`, but `max_altitude_m = 0.3898` and `latest_armed = true`
- [`C2/T4/episode-05/metrics.json`](../../artifacts/imece/official-sim-001/C2/T4/episode-05/metrics.json)
  - terminal `DONE`, but `horizontal_displacement_m = 11.3679` under `Stop there.`

Interpretation from the initial official batch:

- `C1` remains low not because of the old schema-drift issue, but because prompt-only guidance still leaves the model exposed to recurrent offboard and timing brittleness on the generic surface.
- In `official-sim-001`, `C1` has `0` historical interface mismatch episodes, yet `T2` and `T3` still finish `0/10`, with every episode carrying `F4`, every episode timing out, and every episode triggering the watchdog.
- `C1/T2` and `C1/T3` therefore show that once the interface itself is stabilized, prompt-only knowledge still does not reliably maintain the transport mechanics needed for multi-step motion.
- The remaining `C2` misses point to a different class of issue. They are not transport/watchdog failures, they do not request a new helper class, and they are captured by task-success criteria rather than by the current `F1-F5` taxonomy.
- In `C2/T1`, the three failures all end with terminal `DONE` but never satisfy the altitude criterion, which suggests premature completion without a strong enough final altitude verification step.
- In `C2/T4/episode-05`, the trace reads the current pose near `x ~= 12`, then uses relay targets at `(0, 0, 1)` and `(0.5, 0, 1)`, indicating a start-relative parameterization miss rather than a helper-layer failure.

Implementation implication from the initial official batch:

- no new helper class is justified by the preserved failures
- the highest-value next step is prompt or policy refinement inside `C2`, not helper expansion
- the two concrete targets are:
  - `T1`: require explicit altitude attainment verification before landing or `DONE`
  - `T4`: require `Stop there.` handling to remain start-relative and forbid origin-based retargeting

Official-simulation conclusion from `official-sim-001`:

- `C0` and `C1` remain brittle on the final task set
- `C2` is decisively stronger than `C0` and `C1` on the same fixed interface and task map
- `C2` fully repairs `T2` and `T3` in the preserved official comparison and reaches strong but imperfect performance on `T1` and `T4`
- `official-sim-001` therefore motivates carrying `C2` forward into real flight as the strongest condition, while still preserving the remaining `T1` and `T4` misses as part of the paper narrative

### Phase D. Official Real Flight

Current status:

- not yet preserved
- single-episode scaffold exists
- the planned matrix is `C2 x T1-T4 x 5 = 20` episodes

What it should mean in the paper:

- `C2` only
- indoor mocap environment
- tasks `T1`, `T2`, `T3`, `T4`
- `5` repetitions per task
- operator remains responsible for go/no-go and takeover readiness

## 8. Analysis Method Used on Preserved Artifacts

### Source of Task Success

Do not use preserved `task_success` blindly when the current task specification changed.

Use:

- current scoring from [`ros_mcp/imece/scoring.py`](../../ros_mcp/imece/scoring.py)
- `audit.json.current_task_success_by_condition_task`
- `audit.json.stored_vs_current_task_success_mismatches`

Current known stored-vs-current drift:

- `C1:T4:04`
- `C1:T4:05`

These episodes were stored as success historically but are not success under the current `T4` rule.

### Source of Failure Taxonomy

Use:

- current classification from [`ros_mcp/imece/analysis.py`](../../ros_mcp/imece/analysis.py)
- current failure counts from batch `analysis.json`

Important caveats:

- discovery contains historical interface mismatch tied to `wait_for_previous`
- because of that contamination, the paper-safe claim about `C1` should stay qualitative rather than a clean numeric prompt-only improvement claim
- in `official-sim-001`, the remaining `C2` misses are currently task-criterion misses with empty `failure_codes`, so they should not be mislabeled as transport/timing failures

### Source of Helper Freeze Justification

Use:

- discovery `analysis.json.selection`
- runtime mirror in [`config/imece/c2_freeze.json`](../../config/imece/c2_freeze.json)

These two should stay synchronized.

### Source of Reproducibility Metadata

Use:

- per-episode `metadata.json.runtime_metadata`
- batch `audit.json.reproducibility_metadata`

Important limitation:

- preserved discovery predates top-level runtime metadata capture

## 9. Paper-safe Claims

Supported today:

- generic-only operation is brittle for beginner PX4 local-pose control
- prompt-only guidance improves reasoning but does not reliably remove transport/timing and safety failures
- discovery justifies a frozen minimal `C2` subset of `setpoint_relay`, `mode_guard`, and `abort_watchdog`
- targeted `C2:T3` validation closes the remaining preserved square-pattern gap
- official simulation shows a large gap between `C2` and the `C0/C1` baselines on the final fixed task set
- `official-sim-001` identifies `C2` as the strongest preserved condition to carry forward into the planned real-flight phase

Not yet supported today:

- real-flight transfer result claims
- repeated frame/sign errors as a preserved freeze driver
- a claim that `C2` is already fully validated across `T1-T4` in preserved official evidence

## 10. What to Update When New Batches Arrive

When a new preserved batch is added:

1. record the exact batch ID and phase meaning here
2. state what was held fixed and what changed
3. summarize results from `batch_state.json`, `analysis.json`, and `audit.json`
4. separate preserved evidence from planned next steps
5. state explicitly which claims become newly supported and which still remain unsupported
