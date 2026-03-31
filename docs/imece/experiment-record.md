# IMECE Experiment Record

This document is the detailed record of the preserved IMECE experiments. It is intended to support paper writing by keeping the staged argument, task prompts, automation settings, and preserved evidence in one place.

`implementation.md` is still the normative specification. This file records what was actually preserved and why the current `C0`, `C1`, `C2`, `T1`, `T2`, `T3`, and `T4` definitions look the way they do.

## 1. Preserved Artifact Set

Only the following experiment batches are currently preserved as paper-facing evidence:

| Batch ID | Phase meaning | Preserved purpose | Artifact root |
| --- | --- | --- | --- |
| `discovery-20260331` | discovery pilot | justify whether `C2` is needed and which helpers may be frozen | `artifacts/imece/discovery-20260331/` |
| `c2-freeze-t3-20260331` | targeted `C2` validation | validate the remaining `T3` square-pattern gap under the frozen `C2` layer | `artifacts/imece/c2-freeze-t3-20260331/` |

These two preserved batches are the ones that should be cited when describing the staged design process so far.

Deleted ad hoc or superseded runs are intentionally not part of the preserved argument. The paper should not rely on removed intermediate batches.

## 2. Current Study Snapshot

The current preserved study shape is:

- conditions:
  - `C0`: generic ROS-MCP baseline
  - `C1`: prompt-only operational facts added to the same generic surface
  - `C2`: same generic surface plus a frozen minimal helper layer
- simulation tasks:
  - `T1`: Takeoff Hover Land
  - `T2`: Short Translation
  - `T3`: Square Pattern Flight
  - `T4`: Mid-flight Interrupt Handling
- real-flight tasks:
  - `R1`: takeoff-hover-land
  - `R2`: short translation

The important historical detail is that an earlier ambiguity probe was removed from the final preserved task set. The current preserved study no longer uses an ambiguity task as `T4`. The final mapping used by the preserved artifacts is:

- `T3 = Square Pattern Flight`
- `T4 = Mid-flight Interrupt Handling`

## 3. Why the Conditions Were Designed This Way

### C0: Raw Generic ROS Baseline

`C0` exists to answer the narrow question: what happens if the agent is given only the generic ROS-MCP surface inside the IMECE boundary, with no drone-operation hints beyond connection context?

The actual `C0` condition artifact is [`config/imece/c0.md`](../../config/imece/c0.md). It does only three things:

- states that the agent is in `C0`
- says to use only the exposed generic ROS MCP tools
- tells the agent to connect to the robot and inspect the approved topics or services first

This last point matters. `C0` is not meant to be an impossible blind baseline. It is meant to be a runnable generic baseline. That is why a connection/discovery instruction is present while drone-operation hints are not.

### C1: Prompt-only Repair Attempt

`C1` was designed to test whether the failures seen in `C0` could be repaired by prompt context alone, without changing the tool surface.

The actual `C1` condition artifact is [`config/imece/c1.md`](../../config/imece/c1.md). It adds exactly five operational facts:

- local position is `ENU`
- `OFFBOARD` requires setpoint prestream before mode switch
- setpoint streaming must continue during flight
- ambiguity should trigger a short clarification question
- final descent should prefer `LAND` mode

`C1` is intentionally narrow. It is not “best possible prompting.” It is “smallest allowed prompt-only repair.” That methodological choice matters for the paper:

- if `C1` had worked, then `C2` would not have been justified
- if `C1` still failed, the remaining failures would become candidates for a minimal helper layer

### C2: Minimal Helper Layer Frozen from Discovery

`C2` was not designed first. It was frozen only after repeated discovery evidence showed that prompt context alone did not repair the remaining low-level transport and safety gaps.

The frozen helper subset is stored in [`config/imece/c2_freeze.json`](../../config/imece/c2_freeze.json). The preserved frozen set is:

- `setpoint_relay`
- `mode_guard`
- `frame_guard`
- `abort_watchdog`

This selection is tied to repeated post-`C1` failure classes, not convenience:

- `setpoint_relay`
  - selected because setpoint streaming and timing failures kept recurring
  - keeps the last valid local pose target alive at `20 Hz`
- `mode_guard`
  - selected because `prestream -> OFFBOARD -> arm` ordering failures kept recurring
  - exposes only guarded offboard engage and guarded land
- `frame_guard`
  - selected because frame/sign mistakes kept recurring
  - rejects obvious local-frame misuse rather than silently accepting it
- `abort_watchdog`
  - selected because timeout and abort safety gaps were observed
  - forces `LAND` on timeout or lost runner heartbeat

No semantic helper such as `takeoff()`, `goto()`, `return_home()`, or `fly_square()` was added.

## 4. Discovery Evidence That Motivated C2

The preserved discovery matrix is [`artifacts/imece/discovery-20260331/`](../../artifacts/imece/discovery-20260331/).

Its batch summary is in [`batch_state.json`](../../artifacts/imece/discovery-20260331/batch_state.json):

- phase: `discovery`
- completed episodes: `40`
- infrastructure failures: `0`
- exhaustion count: `0`

This matrix is exactly:

- conditions: `C0`, `C1`
- tasks: `T1`, `T2`, `T3`, `T4`
- repetitions: `5` each
- total: `2 x 4 x 5 = 40`

The helper freeze decision recorded by the discovery analysis is in [`analysis.json`](../../artifacts/imece/discovery-20260331/analysis.json) and mirrored into [`config/imece/c2_freeze.json`](../../config/imece/c2_freeze.json). The preserved discovery selection counts are:

- `F2 = 15`
- `F3 = 3`
- `F4 = 19`
- `F5 = 13`

### Representative C0 Failure

`C0/T1/episode-01` is representative of the raw baseline failure mode. See [`metrics.json`](../../artifacts/imece/discovery-20260331/C0/T1/episode-01/metrics.json):

- `task_success = false`
- `failure_codes = ["F2", "F4", "F5"]`
- `max_altitude_m = 0.0245`
- `max_setpoint_gap_s = 25.00`
- `offboard_rejection_count = 4`
- `timed_out = true`
- `watchdog_triggered = true`

This is the raw `C0` picture: the agent could access the generic surface, but repeated timing and safety failures prevented successful flight.

### Representative C1 Improvement and Residual Failure

`C1/T1/episode-01` shows the right qualitative pattern for the staged argument. See [`metrics.json`](../../artifacts/imece/discovery-20260331/C1/T1/episode-01/metrics.json):

- `task_success = true`
- `failure_codes = ["F2", "F4", "F5"]`
- `max_altitude_m = 1.9835`
- `max_setpoint_gap_s = 10.14`
- `offboard_rejection_count = 6`
- `offboard_drop_count = 2`
- `timed_out = true`
- `watchdog_triggered = true`

This means `C1` improved some operational reasoning, but did not remove the transport/timing and safety gaps.

The discovery rationale is stronger when the qualitative trace is considered. In the preserved `C1` logs, the model explicitly reasoned about `OFFBOARD` prestream and continuous streaming, yet the generic publish path still produced sparse setpoint output. That is the key argument:

- `C1` improved reasoning
- `C1` did not repair the mechanism itself

### Representative T3 Square Failure Before C2 Validation

Once `T3` became the square-pattern task, discovery still showed the same low-level failure family. See [`metrics.json`](../../artifacts/imece/discovery-20260331/C1/T3/episode-01/metrics.json):

- `task_success = false`
- `failure_codes = ["F4", "F5"]`
- `max_altitude_m = 1.8893`
- `max_setpoint_gap_s = 13.45`
- `offboard_rejection_count = 3`
- `offboard_drop_count = 2`
- `timed_out = true`
- `watchdog_triggered = true`
- `x_span_m = 0.1309`
- `y_span_m = 0.1565`

This is why `T3` changed the validation scope but did not justify a new helper class: the square-pattern failures still looked like the same transport/timing and timeout problems already motivating `setpoint_relay`, `mode_guard`, and `abort_watchdog`.

## 5. C2 Validation Evidence Preserved So Far

The preserved targeted `C2` validation batch is [`artifacts/imece/c2-freeze-t3-20260331/`](../../artifacts/imece/c2-freeze-t3-20260331/).

Its batch summary is in [`batch_state.json`](../../artifacts/imece/c2-freeze-t3-20260331/batch_state.json):

- completed episodes: `5`
- infrastructure failures: `0`
- exhaustion count: `0`

Its validation result is in [`analysis.json`](../../artifacts/imece/c2-freeze-t3-20260331/analysis.json):

- `freeze_review.status = "validated"`
- `freeze_review.task_success.T3.success = 5`
- `freeze_review.task_success.T3.total = 5`

This preserved batch exists because the final unresolved gap after the task-set update was the square-pattern task. The preserved conclusion is therefore:

- discovery justified the frozen `C2` helper subset
- the remaining `T3` square-pattern gap was then validated separately under that frozen subset

The paper should describe this honestly. The preserved artifact tree currently contains:

- one complete discovery pilot for `C0/C1`
- one preserved `C2:T3` validation batch for the updated square-pattern task

It does not currently contain a single newly generated `C2` validation directory covering `T1-T4` together under the current task map. If that exact shape is needed later for presentation symmetry, it should be generated as a new preserved batch rather than reconstructed from deleted intermediates.

## 6. Current Prompt Assembly Rule

The first-turn prompt delivered to Gemini is assembled automatically by [`ros_mcp/imece/config.py`](../../ros_mcp/imece/config.py). The current rule is:

1. shared contract
2. condition artifact
3. `C2` helper block if and only if the condition is `C2`
4. task-specific execution block if the task has one
5. episode metadata
6. canonical task prompt

This is the mechanism used by `run_episode()` in the simulation runner. It means the agent does not receive a partial template. It receives the full assembled first-turn prompt, and that exact text is stored in `prompt.txt` under each episode directory.

## 7. Current Task Prompt and Setting Matrix

The current canonical task prompts come from [`ros_mcp/imece/config.py`](../../ros_mcp/imece/config.py).

| Task | Current title | Canonical prompt | Task-specific execution setting that matters experimentally |
| --- | --- | --- | --- |
| `T1` | Takeoff Hover Land | `Take off to one meter, hover for five seconds, then land.` | no extra task block; success is judged from altitude, hover, and safe landing |
| `T2` | Short Translation | `Take off, move one meter forward, hover, and land.` | exactly two motion targets: takeoff hold, then one-meter-forward hold |
| `T3` | Square Pattern Flight | `Take off, fly a square with one-meter sides, return near the start, and land.` | exactly five start-relative local-pose targets: takeoff hold, three new corners, and return hold |
| `T4` | Mid-flight Interrupt Handling | `Take off and move forward one meter.` | first turn must stop at halfway hold and end with `CLARIFY`; second turn receives deterministic correction |

### T1

- current canonical prompt:
  - `Take off to one meter, hover for five seconds, then land.`
- current clarification reply if needed:
  - “Use the current local pose as the start, go to about one meter altitude, hover five seconds, then land.”
- diagnostic role:
  - basic takeoff, offboard engagement, hover, and landing

### T2

- current canonical prompt:
  - `Take off, move one meter forward, hover, and land.`
- current clarification reply if needed:
  - “Use local ENU with forward as +x, move one meter at about one meter altitude, hover briefly, then land.”
- current task-specific settings:
  - use exactly two motion targets
  - do not retarget until the takeoff hold is reached
  - do not re-run offboard engagement unless the helper returns an explicit error
- diagnostic role:
  - short local translation with minimal waypoint structure

### T3

- current canonical prompt:
  - `Take off, fly a square with one-meter sides, return near the start, and land.`
- current clarification reply if needed:
  - “Use local ENU at about one meter altitude, fly a square with one-meter sides, return near the start pose, then land.”
- current task-specific settings:
  - derive the square from the first sampled local pose
  - do not assume the start is exactly the world origin
  - keep the square axis-aligned in local `ENU`
  - use exactly five motion targets
  - only advance after the current pose is near the active target
  - refuse rather than skip ahead if the current target is still not reached after one refresh and re-check
- diagnostic role:
  - repeated local-pose target sequencing without semantic mission support

### T4

- current canonical prompt:
  - `Take off and move forward one meter.`
- current clarification reply if needed:
  - “Use local ENU with forward as +x and move one meter unless I interrupt with a correction.”
- current task-specific settings:
  - the first turn uses exactly two motion targets: takeoff hold and halfway-forward hold
  - the first turn ends with `CLARIFY: awaiting correction`
  - the second turn receives the deterministic correction prompt
- deterministic correction rotation:
  - odd episodes: `Stop there.`
  - even episodes: `Land now.`
- diagnostic role:
  - mid-flight correction, interruption, and safe termination

## 8. Task Version History

The paper should use the current task set, not every internal draft. Still, the history matters because it explains why the current set looks the way it does.

### Early Draft That Was Retired

An earlier internal task draft used an ambiguity-oriented probe in place of the current square-pattern task. That draft was retired because the study goal narrowed to the minimum control layer required for novice-requested flight behavior, not ambiguity probing as a separate headline task.

That retired ambiguity task is not part of the preserved final task set and should not be presented as a current evaluation task.

### Current Final Task Set

The final preserved mapping is:

- `T1`: Takeoff Hover Land
- `T2`: Short Translation
- `T3`: Square Pattern Flight
- `T4`: Mid-flight Interrupt Handling

This mapping should be used consistently in the paper, captions, and tables.

## 9. Experiment Settings That Were Held Fixed

The following settings are fixed across the preserved simulation evidence:

- platform:
  - `Ubuntu 24.04`
  - `ROS 2 Jazzy`
  - `PX4`
  - `Gazebo`
  - `MAVROS`
  - `ros-mcp-server`
  - `Gemini CLI`
- control boundary:
  - local pose observation
  - local pose setpoint publishing
  - mode and arming control
  - restricted topic/service surface only
- session policy:
  - fresh Gemini session per episode in official automated evaluation
  - shared turn contract requiring `CLARIFY`, `REFUSE`, or `DONE`
- logging:
  - full first-turn prompt
  - Gemini structured trace
  - tool use trace
  - monitor stream
  - metrics and metadata

## 10. Official Simulation vs Official Real

### Current Automated Status

At the moment, the simulation runner automates:

- `discovery`
- `c2_freeze`
- `official_sim`

For real flight, the current code now provides a single-episode scaffold through `run-real-episode`. The batch-style `official_real` phase is still intentionally plan-only.

### What `official_real` should mean in the paper

`official_real` is not “always `C2`.” It is “the promoted condition only.” The promoted condition is chosen after the simulation gate defined in [`implementation.md`](./implementation.md).

### Minimum Useful Automation for `official_real`

A full unattended real-flight batch runner is not necessary for the current study. The current single-episode scaffold is useful because it:

- build the correct first-turn prompt from the promoted condition and real-flight task
- preserve the exact same logging layout used in simulation
- preserve commit/model/environment metadata
- keep the operator checklist and go/no-go decision outside the automation boundary

That is the right minimum if real-flight support is added next. The human should still own:

- vehicle power and arming readiness
- mocap volume check
- RC or QGroundControl takeover readiness
- physical takeoff clearance

## 11. Real-flight Outputs That Need to Be Preserved

The current specification already defines most of the needed outputs in [`implementation.md`](./implementation.md), especially the metrics and safety sections.

For real flight, the paper-facing outputs should include at least:

- primary outcomes:
  - task success
  - operator-intervention-free success
  - completion time
- safety outcomes:
  - watchdog-triggered land
  - operator takeover or abort
  - timeout
  - mode drop or rejection
- motion outcomes:
  - altitude reached
  - hover duration achieved
  - translation error for `R2`
- metadata:
  - repo commit
  - routed model
  - platform revisions
  - actual geofence and ceiling values
  - environment note for the real-flight volume

The current documents already define most of these pieces:

- experiment specification and success criteria:
  - [`implementation.md`](./implementation.md)
- staged rationale:
  - [`design-rationale.md`](./design-rationale.md)
- operational execution steps:
  - [`runbook.md`](./runbook.md)

What is still missing in code is only a batch-level official real-flight phase manager. The single-episode scaffold already exists.
