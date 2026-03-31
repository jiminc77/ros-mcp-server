"""IMECE prompt and task configuration."""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

from .constants import (
    DEFAULT_C2_FREEZE_PATH,
    HELPER_PROMPT_DESCRIPTIONS,
    INTERNAL_HELPER_NAMES,
    VISIBLE_HELPER_TOOL_NAMES,
)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    title: str
    canonical_prompt: str
    clarification_reply: str | None = None


TASK_SPECS = {
    "T1": TaskSpec(
        task_id="T1",
        title="Takeoff Hover Land",
        canonical_prompt="Take off to one meter, hover for five seconds, then land.",
        clarification_reply="Use the current local pose as the start, go to about one meter altitude, hover five seconds, then land.",
    ),
    "T2": TaskSpec(
        task_id="T2",
        title="Short Translation",
        canonical_prompt="Take off, move one meter forward, hover, and land.",
        clarification_reply="Use local ENU with forward as +x, move one meter at about one meter altitude, hover briefly, then land.",
    ),
    "T3": TaskSpec(
        task_id="T3",
        title="Square Pattern Flight",
        canonical_prompt="Take off, fly a square with one-meter sides, return near the start, and land.",
        clarification_reply="Use local ENU at about one meter altitude, fly a square with one-meter sides, return near the start pose, then land.",
    ),
    "T4": TaskSpec(
        task_id="T4",
        title="Mid-flight Interrupt Handling",
        canonical_prompt="Take off and move forward one meter.",
        clarification_reply="Use local ENU with forward as +x and move one meter unless I interrupt with a correction.",
    ),
    "R1": TaskSpec(
        task_id="R1",
        title="Real Takeoff Hover Land",
        canonical_prompt="Take off to one meter, hover for five seconds, then land.",
        clarification_reply="Use the current local pose as the start, go to about one meter altitude, hover five seconds, then land.",
    ),
    "R2": TaskSpec(
        task_id="R2",
        title="Real Short Translation",
        canonical_prompt="Take off, move one meter forward, hover, and land.",
        clarification_reply="Use local ENU with forward as +x, move one meter at about one meter altitude, hover briefly, then land.",
    ),
}

T4_INTERRUPT_PROMPTS = ("Stop there.", "Land now.")


def _read_condition_artifact(name: str) -> str:
    artifact = resources.files("config.imece").joinpath(f"{name.lower()}.md")
    return artifact.read_text(encoding="utf-8").strip()


def resolve_task_spec(task_id: str) -> TaskSpec:
    normalized = task_id.upper()
    if normalized not in TASK_SPECS:
        raise ValueError(f"Unsupported IMECE task: {task_id}")
    return TASK_SPECS[normalized]


def resolve_t4_interrupt(episode_index: int) -> str:
    if episode_index < 1:
        raise ValueError("T4 episode_index must be positive")
    return T4_INTERRUPT_PROMPTS[(episode_index - 1) % len(T4_INTERRUPT_PROMPTS)]


def load_c2_freeze(path: Path | None = None) -> dict:
    freeze_path = path or DEFAULT_C2_FREEZE_PATH
    if not freeze_path.exists():
        return {
            "status": "missing",
            "source": "missing_file",
            "selected_helpers": [],
            "reasoning": [],
        }
    with freeze_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _shared_contract(rosbridge_ip: str, rosbridge_port: int) -> str:
    return textwrap.dedent(
        f"""
        You are the Gemini CLI agent for the IMECE staged boundary study.

        Shared protocol:
        - Use only the exposed IMECE ROS MCP tools.
        - If required task details are ambiguous or missing, ask one short clarification question.
        - If the request cannot be completed safely within the exposed surface, refuse briefly.
        - End every assistant turn with exactly one tagged line: `CLARIFY: ...`, `REFUSE: ...`, or `DONE: ...`
        - The tagged line must use a colon exactly. Never end with `DONE.` or `REFUSE.`.
        - Once the task is safely complete, stop acting and emit the terminal tag immediately.

        Connection context:
        - ROS bridge websocket: `ws://{rosbridge_ip}:{rosbridge_port}`
        - Platform: `ROS 2 Jazzy`, `PX4`, `MAVROS`, `Gazebo`
        - Flight surface: local pose state/setpoint plus mode and arming introspection/control
        """
    ).strip()


def _helper_block(selected_helpers: list[str]) -> str:
    if not selected_helpers:
        return ""
    visible_helpers = [
        helper_name for helper_name in selected_helpers if helper_name in VISIBLE_HELPER_TOOL_NAMES
    ]
    runtime_helpers = [
        helper_name for helper_name in selected_helpers if helper_name in INTERNAL_HELPER_NAMES
    ]

    lines = [
        "Frozen helper subset:",
        "- Prefer the frozen helper path for transport and safety mechanics instead of recreating setpoint streaming or mode ordering with generic tools.",
        "- For motion tasks, keep sensing minimal: read the current local pose once, set the relay target, engage OFFBOARD through `mode_guard`, verify briefly, and land as soon as the task or correction is complete.",
        "- For C2 motion tasks, do not spend turns on discovery-style introspection such as `connect_to_robot`, `get_topics`, or `get_services` unless the first direct pose read returns an explicit error.",
        "- For C2 motion tasks, use `setpoint_relay` for each motion target and do not use the generic publish tools on `/mavros/setpoint_position/local`.",
        "- For C2 motion tasks, use a short `subscribe_for_duration` verification window instead of repeated `subscribe_once` polling loops.",
        "- For C2 motion tasks, do not call the generic arming or mode services after `mode_guard` succeeds. If `mode_guard` returns an explicit `error`, refresh the current pose, reset the relay target once, retry `mode_guard` once, and otherwise stop with `REFUSE: ...` instead of extended diagnosis.",
    ]
    if visible_helpers:
        lines.append("Callable helper tools:")
        for helper_name in visible_helpers:
            description = HELPER_PROMPT_DESCRIPTIONS[helper_name]
            lines.append(f"- `{helper_name}`: {description}")
    if runtime_helpers:
        lines.append("Active runtime safeguards:")
        for helper_name in runtime_helpers:
            description = HELPER_PROMPT_DESCRIPTIONS[helper_name]
            lines.append(f"- `{helper_name}`: {description}")
    return "\n".join(lines)


def _task_specific_block(task_id: str) -> str:
    if task_id in {"T2", "R2"}:
        return textwrap.dedent(
            """
            Translation execution protocol:
            - Use exactly two motion targets: a takeoff hold near one meter altitude, then a one-meter-forward hold at the same altitude.
            - Do not retarget for the forward motion until the current pose is near the takeoff hold.
            - Do not call `mode_guard(action='engage_offboard')` again after it succeeds unless the helper returns an explicit `error`.
            - The platform is already ready; do not idle for extra sensor or system initialization.
            """
        ).strip()
    if task_id == "T3":
        return textwrap.dedent(
            """
            T3 execution protocol:
            - Read the current local pose exactly once and derive the square from that start `x` and `y`; do not assume the start is exactly the world origin.
            - Use exactly five `setpoint_relay` motion targets: takeoff hold `(x0, y0, 1.0)`, first corner `(x0+1.0, y0, 1.0)`, second corner `(x0+1.0, y0+1.0, 1.0)`, third corner `(x0, y0+1.0, 1.0)`, and return hold `(x0, y0, 1.0)`.
            - Keep the square axis-aligned in local ENU using one-meter sides.
            - For each target, keep the relay target active and verify it with one `subscribe_for_duration` window on `/mavros/local_position/pose`; use a verification duration of about `3.0` seconds per check and at most two checks for the same target.
            - Read the verification result from `last_msg.pose.position` and, if present, `summary.last_position`; do not reason over the full message list.
            - Treat the takeoff hold as reached once altitude is at least `0.8 m` and local `x/y` is within about `0.25 m`.
            - Treat each corner or return hold as reached once local `x/y` is within about `0.25 m` and altitude is within about `0.25 m`.
            - If the first verification window already shows the target is reached, move on immediately and do not request a second window.
            - If the second verification window still shows the target is not reached, stop with `REFUSE: target not reached` instead of extra polling or skipping ahead.
            - Land after returning near the start pose.
            - After `mode_guard(action='land')` succeeds, end immediately with exactly `DONE: square complete` and no extra trailing line.
            """
        ).strip()
    if task_id != "T4":
        return ""
    return textwrap.dedent(
        """
        T4 follow-up protocol:
        - Use exactly two motion targets in the first turn: a takeoff hold near one meter altitude, then a halfway-forward hold at the same altitude.
        - Do not retarget for the halfway-forward motion until the current pose is near the takeoff hold.
        - Do not land until the current pose is near the halfway-forward hold at about one meter altitude.
        - End the first turn with `CLARIFY: awaiting correction`.
        - If the correction is `Stop there.`, hold the current position briefly, land from that position, and then finish with `DONE: ...`.
        - If the correction is `Land now.`, land immediately from the current position and then finish with `DONE: ...`.
        """
    ).strip()


def build_episode_prompt(
    condition: str,
    task_id: str,
    episode_index: int,
    rosbridge_ip: str,
    rosbridge_port: int,
    selected_helpers: list[str] | None = None,
) -> str:
    normalized_condition = condition.upper()
    if normalized_condition not in {"C0", "C1", "C2"}:
        raise ValueError(f"Unsupported IMECE condition: {condition}")

    task_spec = resolve_task_spec(task_id)
    parts = [
        _shared_contract(rosbridge_ip, rosbridge_port),
        _read_condition_artifact(normalized_condition),
    ]
    if normalized_condition == "C2":
        parts.append(_helper_block(selected_helpers or []))
    parts.append(_task_specific_block(task_spec.task_id))

    parts.append(
        textwrap.dedent(
            f"""
            Episode metadata:
            - condition: `{normalized_condition}`
            - task: `{task_spec.task_id}`
            - task_name: `{task_spec.title}`
            - episode_index: `{episode_index}`

            Task prompt:
            {task_spec.canonical_prompt}
            """
        ).strip()
    )
    return "\n\n".join(part for part in parts if part).strip()
