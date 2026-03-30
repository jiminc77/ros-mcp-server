# IMECE Agent Development Guide

You are extending `ros-mcp-server` for the IMECE staged boundary study.

Read [implementation.md](./implementation.md) first. That document is the experiment specification and takes priority over this guide when there is a conflict about task definitions, condition boundaries, or evaluation rules.

## 1. Development Objective

Implement the minimum repository changes needed to support the IMECE experiment workflow described in `implementation.md`.

The target is not a general drone autonomy framework. The target is a narrow experiment harness that can evaluate:

- `C0`: generic ROS-MCP only
- `C1`: prompt-context only
- `C2`: frozen minimal transport/safety helpers

## 2. Non-negotiable Constraints

- Do not introduce semantic drone primitives such as `takeoff`, `goto`, `square`, `return-home`, or mission executors.
- Keep the flight interface limited to local-pose control plus mode and arming paths.
- Official evaluation must use fresh Gemini sessions per episode.
- Official runs must be scriptable on the execution machine.
- Preserve upstream ros-mcp behavior wherever possible; add IMECE-specific logic in clearly isolated files.
- Keep changes minimal and proportional to the experiment need.

## 3. What to Build

Build only what is needed to make the staged experiment executable and reproducible:

- condition-specific prompt or configuration artifacts for `C0`, `C1`, and `C2`
- a scripted episode runner that can launch a fresh Gemini CLI session and capture structured output
- logging capture for prompt history, tool trace, ROS events, and run metadata
- the minimal `C2` helper subset if discovery work justifies it
- configuration or documentation needed on the execution machine to run the official episodes

## 4. What Not to Build

- no semantic task planner
- no behavior tree framework unless it is already required by upstream code
- no body-frame velocity experiment surface for v1
- no broad mission abstraction layer
- no speculative UX or dashboard work
- no feature work that is unrelated to the IMECE experiment

## 5. Repo Strategy

- Put IMECE-specific docs under `docs/imece/`.
- Prefer isolated config, examples, or helper modules rather than invasive edits across unrelated files.
- If a new script or config is needed, make its scope obvious from its path and name.
- Avoid changing upstream defaults unless the experiment absolutely requires it.

## 6. Implementation Priorities

1. Make `C0` and `C1` runnable with fresh-session Gemini launches and complete logging.
2. Make the execution-machine run flow reproducible from a fixed commit.
3. Add only the minimum `C2` helper support needed for transport and safety.
4. Keep metrics and log outputs aligned with `implementation.md`.
5. Document any unavoidable assumption in the changed files or run notes.

## 7. Completion Criteria

The work is done only when all of the following are true:

- `implementation.md` can be used as the experiment source of truth
- official episodes can be launched reproducibly from scripts
- session isolation, logging, and allowlist behavior are explicit
- any `C2` helper remains non-semantic
- the resulting diff is small enough that each changed file is clearly justified
