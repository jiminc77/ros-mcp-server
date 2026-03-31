# IMECE Staged Boundary Study

## 1. Goal and Boundary

This document defines the experiment specification for a staged study of beginner-oriented drone control with a Gemini CLI agent connected to PX4 through generic ROS interfaces.

The primary question is not whether an LLM can replace a flight controller. The primary question is where generic ROS-level tool use stops being sufficient and where a minimal non-semantic support layer becomes necessary.

### In-scope

- `arm / disarm`
- `takeoff / hover / land`
- short-range local-position motion
- mid-flight correction or abort
- ambiguity handling through clarification or safe refusal
- failure characterization and sim-to-real transfer under a tightly constrained indoor setup

### Out-of-scope

- obstacle avoidance
- perception-heavy autonomy
- SLAM or planning stacks
- body-frame velocity control as the main interface
- semantic drone APIs such as `takeoff()`, `goto()`, `fly_square()`
- persistent memory adaptation during official evaluation

## 2. Fixed Platform Assumptions

- OS: `Ubuntu 24.04`
- middleware: `ROS2 Jazzy`
- simulator: `Gazebo`
- autopilot: `PX4`
- bridge: `MAVROS`
- MCP bridge: `ros-mcp-server`
- agent runtime: `Gemini CLI`

The official comparison unit is a `Gemini CLI auto-routing agent session` with ros-mcp attached. The routed model remains `auto`; the actual routed model used in each episode is logged as metadata.

Official evaluation always starts a fresh Gemini session per episode. Discovery work may use longer interactive sessions, but official runs may not carry memory between episodes.

The official control surface is restricted to ROS introspection, topic publish, topic subscribe, state read, and service call over a `local pose` flight interface plus mode and arming control.

### Control Surface Boundary

The study does not expose the full ROS graph to the agent. It exposes an IMECE-scoped subset of ros-mcp that is sufficient for the target tasks but intentionally excludes higher-level or off-scope interfaces.

| Category | Allowed surface | Excluded surface | Boundary reason |
| --- | --- | --- | --- |
| State observation | `/mavros/state`, `/mavros/local_position/pose`, `/mavros/battery` | arbitrary ROS topics, node graph, parameters | enough state for task completion, safety checks, and post-hoc scoring |
| Control output | `/mavros/setpoint_position/local` | velocity control, body-frame control, mission topics, arbitrary publish targets | fixes the study on local-pose control so frame and timing failures remain observable |
| Services | `/mavros/set_mode`, `/mavros/cmd/arming` | `/mavros/cmd/takeoff`, `/mavros/cmd/land`, and other MAVROS services | removes semantic shortcuts and preserves the need to reason about mode ordering and arming |
| Generic tool families | topic and service introspection, subscribe, publish, call | actions, nodes, parameters, robot spec tools, image tools | removes unrelated surface area that would weaken attribution of failures |

The boundary was chosen to preserve three properties:

- task sufficiency: the agent can still complete `T1-T4` using ROS-level primitives only
- non-semantic control: the agent cannot collapse the task into high-level flight calls such as `takeoff()`, `goto()`, or mission executors
- failure interpretability: errors remain attributable to prompt reasoning, message construction, frame handling, or offboard timing rather than to hidden controller abstractions

This boundary is shared by `C0` and `C1`. `C2` keeps the same generic boundary and adds only a frozen helper subset justified by repeated discovery failures.

## 3. Condition Design

| Condition | Tool surface | Prompt context | Helper layer | Purpose |
| --- | --- | --- | --- | --- |
| `C0` | Generic ROS-MCP only | No | None | raw baseline |
| `C1` | Same as `C0` | Yes | None | prompt-only improvement |
| `C2` | Same as `C1` | Yes | Frozen minimal helper subset | minimum required low-layer |

### C0

- Generic ROS-MCP tools only
- No drone-operation hints beyond connection context

### C1

- Same tool surface as `C0`
- Adds only concise operational facts:
  - local position is `ENU`
  - `OFFBOARD` requires setpoint prestream before mode switch
  - setpoint streaming must continue during flight
  - ambiguity should trigger a short clarification question
  - final descent should prefer `LAND` mode

### C2

- Same ROS interface surface as `C1`
- Adds a frozen subset of non-semantic helpers only after discovery pilots show repeated failures that prompt/context alone cannot address

### Allowed Helper Catalog for C2

- `setpoint_relay`
  - maintains the last valid local pose target at `20 Hz`
- `frame_guard`
  - normalizes `ENU` local pose conventions and rejects obvious frame/sign inconsistencies
- `mode_guard`
  - enforces the minimum safe order: prestream -> `OFFBOARD` -> arm -> `LAND`
- `abort_watchdog`
  - triggers `LAND` on timeout or abort path

### Forbidden Helper Behavior

- automatic altitude choice
- automatic waypoint or mission generation
- path generators such as `square`, `triangle`, or `return-home`
- behavior trees or mission executors that hide multiple semantic flight steps behind one call

## 4. Failure Taxonomy

### F1. Ambiguity

- unclear direction, distance, altitude, or stopping criterion
- body/world reference confusion in user wording
- missing information that should trigger clarification or safe refusal

### F2. Tool or Interface Misuse

- wrong topic or service selected
- required state inspection omitted
- incorrect use of ROS interface structure

### F3. Message or Frame Error

- missing message fields
- wrong message type or units
- sign or frame inconsistency under `ENU` local pose conventions

### F4. Offboard or Timing Failure

- mode switch before setpoint prestream
- setpoint stream too sparse or interrupted
- reasoning delay causes `OFFBOARD` rejection or drop

### F5. Recovery or Safety Abort

- stale plan persists after state change
- correction prompt is mishandled
- timeout, geofence stop, watchdog landing, or operator takeover occurs

## 5. Task Design

### Main Simulation Tasks

#### T1. Takeoff-Hover-Land

- canonical prompt: `Take off to one meter, hover for five seconds, then land.`

#### T2. Short Translation

- canonical prompt: `Take off, move one meter forward, hover, and land.`
- the initial yaw is aligned with world `+x` so that `forward` is well defined

#### T3. Mid-flight Interrupt or Abort

- base prompt: `Take off and move forward one meter.`
- the first turn must execute only the initial half-meter segment and hold there
- once the halfway hold is stable, the agent must end the turn with `CLARIFY: awaiting correction`
- the scheduled correction prompt is then sent in the same Gemini session as the second turn
- deterministic interrupt rotation:
  - odd-numbered episodes: `Stop there.`
  - even-numbered episodes: `Land now.`

#### T4. Pattern Flight

- canonical prompt: `Take off, fly a one-meter square, return near the start, and land.`
- the square is executed with local-pose waypoints only; no semantic pattern or mission helper is introduced
- this task replaces the earlier ambiguity probe because the study is focused on the minimum control layer required for novice-requested flight behavior

### Controlled Real-flight Tasks

- `R1`: takeoff-hover-land
- `R2`: short translation

`T3` is a simulation gate for recovery and safety competence. It is not part of the official real-flight task set.

## 6. Multi-turn Policy

### Clarification Policy

- if the agent asks a clarification question, the human may answer in freeform natural language
- the reply must be at most one sentence
- the reply must answer only the missing information requested by the agent
- the reply must not add extra hints about ROS interfaces, flight modes, or implementation details
- both the question and the human reply are logged

### Success Criteria

#### Shared

- episode timeout: `120 s`
- no operator intervention for success
- success is judged from logged state and task-specific criteria only
- each episode begins from a runner-normalized landed/disarmed baseline before the first Gemini turn

#### T1 / R1

- reach target altitude near `1.0 m`
- maintain hover for `5 s`
- land safely

#### T2 / R2

- reach the commanded local translation of `1.0 m`
- final position error after the translation target: `<= 0.25 m`

#### T3

- the interrupt prompt is handled safely
- the resulting behavior matches the interrupt intent
- no operator intervention occurs

#### T4

- fly a square pattern with motion in both local `x` and local `y`
- return near the start pose before landing
- land safely

## 7. Experimental Phases

### Discovery Pilot

- conditions: `C0`, `C1`
- tasks: `T1-T4`
- repetitions: `5` per task per condition
- goal: identify repeated failures and decide whether `C2` is necessary

### C2 Freeze Rule

- helper selection changes only between pilot batches
- the `C2` subset is frozen once one complete pilot batch of `T1-T3` with `5` repetitions each produces no helper change request

### Official Simulation Evaluation

- conditions: `C0`, `C1`, `C2`
- tasks: `T1-T4`
- repetitions: `10` per task per condition
- launch a fresh Gemini session per episode
- change no helper, prompt, or policy during this phase

### Real-flight Promotion Gate

Promote only the lowest-support condition that satisfies all of the following:

- `T1` success rate `>= 8/10`
- `T2` success rate `>= 8/10`
- `T3` safe interrupt or abort success rate `>= 8/10`
- critical safety failures in the final gate batch: `0`

### Official Real-flight Evaluation

- promoted condition only
- tasks: `R1`, `R2`
- repetitions: `5` per task
- environment: indoor mocap

## 8. Metrics and Metadata

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

### Metadata

- repo commit SHA
- Gemini CLI version
- actual routed model
- account tier if observable
- ros-mcp version or commit
- PX4, MAVROS, and Gazebo revision information

## 9. Procedure and Safety

### Episode Procedure

1. reset the simulator or real-flight environment
2. verify `PX4 <-> MAVROS <-> ROS2 <-> ros-mcp` connectivity
3. verify the fixed repo commit on the execution machine
4. start `rosbag` and metadata logging
5. launch a fresh Gemini CLI session with the condition-specific prompt and tool allowlist
6. send the initial user prompt
7. answer clarification requests under the one-sentence rule
8. for `T3`, inject the scheduled correction prompt at the deterministic trigger
9. allow tool use until success, failure, operator takeover, watchdog landing, or timeout
10. stop logs and compute metrics

### Logging Requirements

- full prompt and clarification history
- Gemini CLI structured output or JSON trace
- full tool invocation trace
- all ROS service calls
- all setpoint messages
- state topic timeline
- position, attitude, battery, and mode history
- operator abort or takeover flag
- watchdog-triggered land events

### Real-flight Safety

- manual takeover through RC or QGroundControl must remain available
- `abort_watchdog` must trigger `LAND` on timeout or abort path
- real-flight evaluation is centered inside the mocap safety volume
- fixed task envelope:
  - takeoff altitude: `1.0 m`
  - horizontal translation: `1.0 m`
  - hover duration: `5 s`
- actual geofence and ceiling values are execution-machine environment facts and must be measured and written into the run configuration before real-flight trials
