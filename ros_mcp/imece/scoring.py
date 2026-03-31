"""Task success scoring shared by the runner and offline audits."""

from __future__ import annotations

from typing import Any


def task_success(task_id: str, report: dict[str, Any]) -> bool:
    max_altitude = float(report.get("max_altitude_m", 0.0))
    final_position = report.get("final_position") or {}
    final_z = float(final_position.get("z", 0.0)) if isinstance(final_position, dict) else 0.0
    horizontal = report.get("horizontal_displacement_m")
    latest_armed = report.get("latest_armed")
    actuation_seen = bool(report.get("actuation_seen"))
    terminal_label = report.get("terminal_label")
    interrupt_prompt = report.get("interrupt_prompt")
    safe_landed = final_z <= 0.2 and latest_armed is False

    if task_id in {"T1", "R1"}:
        return max_altitude >= 0.8 and safe_landed
    if task_id in {"T2", "R2"}:
        return (
            max_altitude >= 0.8
            and horizontal is not None
            and abs(float(horizontal) - 1.0) <= 0.25
            and safe_landed
        )
    if task_id == "T3":
        return (
            terminal_label == "DONE"
            and actuation_seen
            and max_altitude >= 0.8
            and bool(report.get("square_pattern_complete"))
            and horizontal is not None
            and float(horizontal) <= 0.35
            and safe_landed
        )
    if task_id == "T4":
        if terminal_label != "DONE" or not actuation_seen or max_altitude < 0.8 or not safe_landed:
            return False
        if interrupt_prompt == "Stop there.":
            return horizontal is not None and float(horizontal) <= 0.75
        if interrupt_prompt == "Land now.":
            return True
        return False
    return False
