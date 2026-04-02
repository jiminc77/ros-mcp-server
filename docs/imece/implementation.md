# IMECE Study Specification and Implementation Map

This document is the normative source of truth for the IMECE staged boundary study.

Use this file for:

- the paper's intended argument flow
- the fixed experiment boundary and success criteria
- the current implementation map of the repository
- the exact meaning of each study phase

Use [`experiment-record.md`](./experiment-record.md) for preserved evidence and paper-facing analysis of what actually ran.
Use [`runbook.md`](./runbook.md) for commands and operator steps.
Use [`agent-development-guide.md`](./agent-development-guide.md) for how future agents should analyze results and update the documentation set.

## 1. Study Positioning

The study asks a narrow question:

- how far can an off-the-shelf LLM operate a PX4 drone through generic ROS-level tools alone
- where does prompt-only guidance stop being enough
- what is the minimum non-semantic stabilization needed before drone-specific MCP design is justified

The intended paper flow is staged, not monolithic:

1. `C0` measures the raw generic ROS-MCP baseline.
2. `C1` tests whether prompt context alone repairs the baseline.
3. `C2` adds only a frozen minimal helper layer after discovery shows repeated low-level failures that prompt context did not repair.

The study is therefore not a claim that a generic ROS tool surface is sufficient for all drone control. It is a boundary study about where generic tool use breaks and what minimum extra support is required.

## 2. Research Questions

### RQ1. Feasibility

- Can generic ROS-level tool selection support basic PX4 beginner flight tasks?

### RQ2. Failure Modes

- Where does generic tool use become brittle?
- Which failures are prompt-repairable, and which require a thin low-level support layer?

### RQ3. Transfer

- Can the interaction pattern that works in simulation transfer at minimum scale to controlled indoor real flight?

## 3. Claim Boundary and Current Study Status

The current preserved evidence supports the following narrow claims:

- discovery justifies why a frozen `C2` helper subset is needed at all
- the currently frozen subset is `setpoint_relay`, `mode_guard`, and `abort_watchdog`
- the remaining `T3` square-pattern gap was validated separately as a targeted `C2` batch
- the current preserved state is sufficient to begin `official_sim`
- `official-sim-001` identifies `C2` as the strongest condition to carry forward into the planned real-flight phase

The current preserved evidence does not yet support these stronger claims:

- that `C2` has already been fully validated across the final `T1-T4` task set
- that real-flight transfer has already been demonstrated
- that repeated explicit frame/sign failures are part of the preserved freeze rationale

Operationally, the study can proceed as:

1. `official_sim`
2. `official_real` with `C2` only

## 4. Scope and Boundary

### In Scope

- `arm / disarm`
- `takeoff / hover / land`
- short-range local-position motion
- mid-flight correction or abort in simulation
- clarification and safe refusal
- failure characterization under a fixed indoor stack
- C2-only sim-to-real transfer in a controlled indoor real-flight phase

### Out of Scope

- obstacle avoidance
- perception-heavy autonomy
- SLAM or planning stacks
- body-frame velocity control as the main interface
- semantic drone APIs such as `takeoff()`, `goto()`, `fly_square()`
- mission executors, behavior trees, or path generators
- adaptive memory across official episodes

## 5. Fixed Platform Assumptions

- OS: `Ubuntu 24.04`
- middleware: `ROS 2 Jazzy`
- simulator: `Gazebo`
- autopilot: `PX4`
- bridge: `MAVROS`
- MCP bridge: `ros-mcp-server`
- agent runtime: `Gemini CLI`

The official comparison unit is one fresh Gemini CLI session per episode.
The routed model remains `auto`; the actual routed model must be logged from the episode trace.

## 6. Control Surface Boundary

The study intentionally exposes only an IMECE-scoped subset of ros-mcp.

| Category | Allowed surface | Excluded surface | Why |
| --- | --- | --- | --- |
| State observation | `/mavros/state`, `/mavros/local_position/pose`, `/mavros/battery` | arbitrary ROS topics, node graph, parameters | enough state for completion, scoring, and safety checks |
| Control output | `/mavros/setpoint_position/local` | velocity control, body-frame control, mission topics, arbitrary publish targets | keeps the study on local-pose control |
| Services | `/mavros/set_mode`, `/mavros/cmd/arming` | semantic MAVROS flight services such as takeoff or land | preserves mode-order reasoning and arming responsibility |
| Generic tool families | topic/service introspection, subscribe, publish, call | actions, parameters, robot-spec tools, unrelated surface | keeps failure attribution interpretable |

The shared generic surface used for future `official_sim` runs is stabilized in only two narrow ways:

- generic tools tolerate stray `wait_for_previous` fields instead of failing on historical schema drift
- `subscribe_for_duration` returns a compact payload with `first_msg`, `last_msg`, and `summary`

These are interface stabilizations, not semantic flight primitives.

## 7. Conditions

| Condition | Tool surface | Prompt context | Helper layer | Intended role |
| --- | --- | --- | --- | --- |
| `C0` | generic ROS-MCP only | none beyond connection context | none | raw generic baseline |
| `C1` | same as `C0` | five operational facts | none | prompt-only repair attempt |
| `C2` | same generic surface | same as `C1` | frozen minimal helper subset | minimum required transport and safety support |

### C0

`C0` must remain runnable, but not informed by drone-operation hints.
Its condition artifact therefore does only three things:

- names the condition
- restricts the agent to the exposed IMECE tools
- tells the agent to inspect the approved surface before acting

This is a runnable baseline, not an impossible blind baseline.

### C1

`C1` adds exactly five operational facts:

- local position is `ENU`
- `OFFBOARD` requires setpoint prestream before mode switch
- setpoint streaming must continue during flight
- ambiguity should trigger one short clarification question
- final descent should prefer `LAND` mode

`C1` is intentionally not "best possible prompting." It is the smallest allowed prompt-only repair.

### C2

`C2` keeps the same generic surface and prompt basis as `C1`, then adds only a frozen helper subset justified by repeated discovery failures.

#### Allowed Helper Catalog

- `setpoint_relay`
  - maintains the last valid local pose target at `20 Hz`
- `frame_guard`
  - normalizes `ENU` local-pose conventions and rejects obvious frame/sign inconsistencies
- `mode_guard`
  - enforces the minimum safe sequence: prestream -> `OFFBOARD` -> arm -> `LAND`
- `abort_watchdog`
  - forces `LAND` on timeout or runner-abort path

#### Currently Frozen Subset

- `setpoint_relay`
- `mode_guard`
- `abort_watchdog`

`frame_guard` remains implemented but is not part of the currently frozen subset because the preserved discovery audit does not show repeated explicit frame/sign failures under the current classifier.

#### Forbidden Helper Behavior

- automatic altitude choice
- automatic waypoint or mission generation
- path generators such as square, triangle, or return-home
- behavior trees or mission executors that hide multi-step flight semantics behind one call

## 8. Failure Taxonomy

### F1. Ambiguity

- unclear direction, distance, altitude, or stopping criterion
- wording that should trigger clarification or refusal

### F2. Tool or Interface Misuse

- wrong topic or service
- incorrect ROS interface usage
- invalid tool parameterization

### F3. Message or Frame Error

- wrong message fields, units, or frame/sign conventions under local `ENU`

### F4. Offboard or Timing Failure

- insufficient prestream
- sparse or interrupted setpoint streaming
- `OFFBOARD` rejection or drop caused by ordering or timing

### F5. Recovery or Safety Abort

- timeout
- operator intervention
- watchdog-triggered landing
- failed interrupt handling

## 9. Task Set

### Simulation Tasks

| Task | Title | Canonical prompt | Experimental role |
| --- | --- | --- | --- |
| `T1` | Takeoff Hover Land | `Take off to one meter, hover for five seconds, then land.` | basic offboard takeoff, hover, landing |
| `T2` | Short Translation | `Take off, move one meter forward, hover, and land.` | short local translation |
| `T3` | Square Pattern Flight | `Take off, fly a square with one-meter sides, return near the start, and land.` | repeated multi-step local waypoint sequencing |
| `T4` | Mid-flight Interrupt Handling | `Take off and move forward one meter.` | interruption, correction, and safe termination |

`T3` is derived from the first sampled local pose rather than an assumed world origin.
`T4` uses deterministic correction prompts:

- odd episodes: `Stop there.`
- even episodes: `Land now.`

### Real-flight Tasks

The real-flight phase reuses the same task IDs as simulation:

- `T1`: Takeoff Hover Land
- `T2`: Short Translation
- `T3`: Square Pattern Flight
- `T4`: Mid-flight Interrupt Handling

## 10. Success Criteria

### Shared

- episode timeout: `120 s`
- fresh Gemini session per official episode
- success judged from logged state and task-specific criteria
- each episode starts from a runner-normalized landed/disarmed baseline

### T1

- reach about `1.0 m`
- hold hover for `5 s`
- land safely

### T2

- reach the commanded local translation of `1.0 m`
- final translation error `<= 0.25 m`
- land safely

### T3

- reach the takeoff hold, three square corners, and return hold in order
- use a start-relative local `ENU` square with one-meter sides
- return near the start pose
- land safely

### T4

- handle the correction prompt safely
- end with behavior matching the interrupt intent
- avoid operator intervention

## 11. Experimental Phases

### Discovery Pilot

- conditions: `C0`, `C1`
- tasks: `T1-T4`
- repetitions: `5`
- goal: identify repeated failures and decide whether `C2` is justified

### C2 Freeze Confirmation Rule

- helper selection may change only between pilot batches
- once `T3` became the square-pattern task, any full `C2` confirmation batch had to cover `T1-T4`
- a fully symmetric `C2` confirmation batch means `C2 x T1-T4 x 5`
- the current preserved evidence is narrower: discovery plus targeted `C2:T3` validation

### Official Simulation

- conditions: `C0`, `C1`, `C2`
- tasks: `T1-T4`
- repetitions: `10`
- no prompt, helper, or policy change during the phase

### Official Real Flight

- condition: `C2` only
- tasks: `T1-T4`
- repetitions: `5`
- total: `20`
- indoor mocap environment
- manual operator go/no-go and takeover readiness required

### Current Execution Status

- `discovery`, `c2_freeze`, and `official_sim` are automated in the runner
- real flight currently has a single-episode scaffold through `run-real-episode`
- the current preserved evidence is sufficient to start `official_sim`
- the current author-directed next phase is `official_real` with `C2 x T1-T4 x 5`
- a separate `run-educational-batch` path now automates a `C2`-only simulation sweep over `4` prompt levels x `3` sibling prompts x `T1-T3 = 36` episodes

## 12. Educational Prompt Extension

This extension is separate from the `C0 -> C1 -> C2` boundary study.

### Reader and Task Grounding

The prompt profiles are treated as controlled readability variants, not as informal "student-like" rewrites.
The intended grounding follows four recurring dimensions from readability and simplification work:

- lexical familiarity
  - how common and concrete the words are
- syntactic load
  - how much clause packing appears in one request
- discourse explicitness
  - how much local sequencing support the text gives the reader
- abstraction and compression
  - whether the request is phrased as concrete actions or as a denser task objective

The working references for this extension are:

- Common Core Appendix A
  - text complexity should be evaluated through quantitative signals, qualitative dimensions, and reader/task considerations together
- simplification literature
  - simplification is not only lexical; it also changes syntax and discourse support
- educational GenAI evaluation
  - level targeting and meaning preservation should be checked together
- plain-language guidance
  - short sentences, common words, explicit organization, and one idea per sentence are recommended supports for less experienced readers

Reference links:

- [CCSS Appendix A Supplemental Information](https://www.thecorestandards.org/wp-content/uploads/Appendix-A-New-Research-on-Text-Complexity-revised.pdf)
- [Text Simplification to Specific Readability Levels](https://www.mdpi.com/2227-7390/11/9/2063)
- [Evaluating GenAI for Simplifying Texts for Education](https://arxiv.org/abs/2501.09158)
- [US EPA Readability Guidance](https://www.epa.gov/choose-fish-and-shellfish-wisely/readability-developing-and-pretesting-concepts-messages-materials)
- [NIH Plain Language: Getting Started or Brushing Up](https://www.nih.gov/sites/default/files/2025-02/nih-plain-language-getting-started-brushing-up.pdf)
- [National Archives Plain Language Principles](https://www.archives.gov/open/plain-writing/10-principles.html)

### Level Rubric

| Level | Visible signature | Lexical style | Sentence style |
| --- | --- | --- | --- |
| `elementary` | obviously stepwise and concrete | `go up`, `bring it down`, `keep it still` | mostly 3-4 short sentences, one action per sentence |
| `middle` | school-style procedural command | `take off`, `hover`, `return` | 2-3 short sentences or a short clause chain |
| `high` | more academic and compressed | `ascend`, `maintain`, `complete` | usually one dense sentence |
| `college` | most compressed adult phrasing | `establish`, `execute`, `trajectory`, `interval` | densest phrasing, more nominalized wording |

### Representative `T1` Ladder

| Level | Representative prompt |
| --- | --- |
| `elementary` | `Make the drone go up. Stop when it is about one meter high. Wait there for five seconds. Then bring it down and land.` |
| `middle` | `Take off to about one meter. Hover there for five seconds. Then land.` |
| `high` | `Ascend to roughly one meter, hold position for five seconds, and then land.` |
| `college` | `Establish a hover at approximately one meter altitude for five seconds, then execute landing.` |

### Sibling Prompt Rule

Each level has three sibling prompts identified as `a`, `b`, and `c`.
These are not supposed to create a second readability ladder.
They only provide small within-level paraphrases so the educational result is not tied to one exact sentence string.

### Fixed Prompt-profile Rules

- keep task semantics identical across all profiles
- keep the educational sweep on `T1`, `T2`, and `T3` only
- do not add hidden hints such as `OFFBOARD`, `setpoint`, `ENU`, `PX4`, or `MAVROS`
- do not add extra task decomposition beyond what is already visible in the user request
- keep the task-specific clarification replies fixed under the current runner

### Current Prompt-profile Matrix

| Factor | Values |
| --- | --- |
| condition | `C2` only |
| tasks | `T1`, `T2`, `T3` |
| prompt levels | `elementary`, `middle`, `high`, `college` |
| sibling prompts | `a`, `b`, `c` |
| repetitions | `1` |
| total | `36` |

The current runner implementation preserves prompt-profile metadata in both `metrics.json` and `metadata.json` as:

- `prompt_level`
- `prompt_variant`

Profiled simulation batches also write episode directories under:

- `artifacts/imece/<batch_id>/<condition>/<task>/<prompt_level>/<prompt_variant>/episode-01/`

## 13. Repository Map

### Documentation

| Path | Role |
| --- | --- |
| [`docs/imece/implementation.md`](./implementation.md) | normative study specification and code map |
| [`docs/imece/experiment-record.md`](./experiment-record.md) | preserved experiment history, results, and paper-facing interpretation |
| [`docs/imece/runbook.md`](./runbook.md) | execution steps, command examples, and argument meanings |
| [`docs/imece/agent-development-guide.md`](./agent-development-guide.md) | instructions for future agents that analyze batches and update the docs |
| [`docs/imece/design-rationale.md`](./design-rationale.md) | legacy redirect file; rationale now lives in the main docs |

### Configuration Artifacts

| Path | Role |
| --- | --- |
| [`config/imece/c0.md`](../../config/imece/c0.md) | raw generic baseline condition prompt block |
| [`config/imece/c1.md`](../../config/imece/c1.md) | prompt-only repair condition prompt block |
| [`config/imece/c2.md`](../../config/imece/c2.md) | shared `C2` helper guidance fragment |
| [`config/imece/c2_freeze.json`](../../config/imece/c2_freeze.json) | runtime mirror of the frozen helper subset |
| [`config/imece/gemini-policy.toml`](../../config/imece/gemini-policy.toml) | Gemini tool policy used by the runner |

### Runtime Code

| Path | Role |
| --- | --- |
| [`ros_mcp/imece/server.py`](../../ros_mcp/imece/server.py) | IMECE-scoped ros-mcp server entrypoint |
| [`ros_mcp/imece/constants.py`](../../ros_mcp/imece/constants.py) | allowed topics, services, helper names, defaults |
| [`ros_mcp/imece/boundary_tools.py`](../../ros_mcp/imece/boundary_tools.py) | filtered generic tools and compact subscription payloads |
| [`ros_mcp/imece/helpers.py`](../../ros_mcp/imece/helpers.py) | `setpoint_relay`, `frame_guard`, `mode_guard`, `abort_watchdog` |
| [`ros_mcp/imece/config.py`](../../ros_mcp/imece/config.py) | task specs, educational prompt profiles, prompt assembly, deterministic `T4` interrupt rotation |
| [`ros_mcp/imece/gemini.py`](../../ros_mcp/imece/gemini.py) | Gemini CLI turn execution and trace capture |
| [`ros_mcp/imece/rosbridge.py`](../../ros_mcp/imece/rosbridge.py) | rosbridge request and subscribe helpers used by the runner and monitor |
| [`ros_mcp/imece/monitor.py`](../../ros_mcp/imece/monitor.py) | runtime state capture used for scoring and diagnostics |
| [`ros_mcp/imece/scoring.py`](../../ros_mcp/imece/scoring.py) | task success logic shared by runtime and offline audit |
| [`ros_mcp/imece/analysis.py`](../../ros_mcp/imece/analysis.py) | failure classification, helper selection, audit generation |
| [`ros_mcp/imece/runner.py`](../../ros_mcp/imece/runner.py) | CLI entrypoint for episode, batch, phase, educational-batch, analysis, and audit workflows |

### Scripts

| Path | Role |
| --- | --- |
| [`scripts/imece/setup_gemini_project_mcp.sh`](../../scripts/imece/setup_gemini_project_mcp.sh) | project-local Gemini MCP configuration |
| [`scripts/imece/start_sim_stack.sh`](../../scripts/imece/start_sim_stack.sh) | PX4, MAVROS, and rosbridge bring-up |
| [`scripts/imece/stop_sim_stack.sh`](../../scripts/imece/stop_sim_stack.sh) | simulation shutdown |

### Tests

| Path | Role |
| --- | --- |
| [`tests/imece/test_boundary_surface.py`](../../tests/imece/test_boundary_surface.py) | control-surface allowlist behavior |
| [`tests/imece/test_boundary_tools.py`](../../tests/imece/test_boundary_tools.py) | compact subscription payload behavior |
| [`tests/imece/test_prompts.py`](../../tests/imece/test_prompts.py) | prompt assembly and task-specific instructions |
| [`tests/imece/test_helpers.py`](../../tests/imece/test_helpers.py) | helper-layer behavior |
| [`tests/imece/test_analysis.py`](../../tests/imece/test_analysis.py) | failure taxonomy, audit, and freeze logic |
| [`tests/imece/test_runner_batch.py`](../../tests/imece/test_runner_batch.py) | batch execution and artifact writing |
| [`tests/imece/test_gemini.py`](../../tests/imece/test_gemini.py) | Gemini runner integration contract |
| [`tests/imece/test_policy.py`](../../tests/imece/test_policy.py) | Gemini policy loading and application |

### Artifacts

`artifacts/imece/<batch_id>/` is the batch output root.
Per-episode outputs include:

- `prompt.txt`
- `gemini.jsonl`
- `gemini.stderr.log`
- `monitor.jsonl`
- `metrics.json`
- `metadata.json`
- `rosbag/`

Per-batch outputs include:

- `batch_state.json`
- `analysis.json`
- `audit.json`

## 13. Metrics, Metadata, and Logging

### Primary Metrics

- task success rate
- operator-intervention-free success rate
- completion time

### Diagnostic Metrics

- prompt turns per task
- clarification count
- tool call count
- invalid tool call count
- `OFFBOARD` rejection count
- `OFFBOARD` drop count
- first valid actuation latency
- max setpoint gap
- final pose error
- `T3` square waypoint count and completion flag

### Required Runtime Metadata

- repo commit SHA
- ros-mcp repo commit SHA
- PX4 commit SHA
- Gemini CLI version
- actual routed model
- MAVROS version
- Gazebo version
- ROS distro

Preserved discovery artifacts predate this metadata capture and must be described as such rather than backfilled.

### Logging Requirements

- full first-turn prompt
- clarification history
- Gemini structured output
- tool invocation trace
- ROS service calls and setpoint activity
- state and pose history
- batch-level `analysis.json`
- batch-level `audit.json`

## 14. Procedure and Safety

### Episode Procedure

1. reset or verify the sim or real-flight environment
2. verify `PX4 <-> MAVROS <-> ROS2 <-> ros-mcp` connectivity
3. verify the intended repo state on the execution machine
4. start logging and rosbag capture
5. launch a fresh Gemini session
6. send the initial prompt
7. answer clarification under the one-sentence rule if needed
8. for `T4`, inject the scheduled correction prompt
9. stop only on success, refusal, operator takeover, watchdog landing, or timeout
10. compute metrics and write batch analysis artifacts

### Real-flight Safety

- manual takeover through RC or QGroundControl must remain available
- `abort_watchdog` must trigger `LAND` on timeout or abort path
- real-flight evaluation stays inside the mocap safety volume
- fixed task envelope:
  - altitude: `1.0 m`
  - translation: `1.0 m`
  - hover: `5 s`
- actual geofence and ceiling values must be measured and recorded before real-flight trials
