"""IMECE discovery analysis and C2 helper selection."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .scoring import task_success

HISTORICAL_INTERFACE_MISMATCH_SNIPPETS = (
    "wait_for_previous",
    "unexpected keyword argument",
)

EXPLICIT_FRAME_ERROR_SNIPPETS = (
    "invalid frame",
    "frame mismatch",
    "frame_id must",
    "frame id must",
    "enu",
    "ned",
    "body frame",
    "body-frame",
    "quaternion",
    "negative altitude",
)

RUNTIME_METADATA_FIELDS = (
    "repo_commit_sha",
    "ros_mcp_repo_commit_sha",
    "px4_commit_sha",
    "gemini_cli_version",
    "actual_routed_model",
    "mavros_version",
    "gazebo_version",
    "ros_distro",
)


def historical_interface_mismatch(report: dict[str, Any]) -> bool:
    errors = "\n".join(report.get("tool_error_messages", [])).lower()
    return all(snippet in errors for snippet in HISTORICAL_INTERFACE_MISMATCH_SNIPPETS)


def explicit_frame_error(report: dict[str, Any]) -> bool:
    if historical_interface_mismatch(report):
        return False
    errors = "\n".join(report.get("tool_error_messages", [])).lower()
    return any(snippet in errors for snippet in EXPLICIT_FRAME_ERROR_SNIPPETS)


def effective_task_success(report: dict[str, Any]) -> bool:
    if "task_success_current_spec" in report:
        return bool(report.get("task_success_current_spec"))
    return bool(report.get("task_success"))


def classify_episode_report(report: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    task_id = report.get("task_id")
    terminal_label = report.get("terminal_label")
    actuation_seen = bool(report.get("actuation_seen"))
    invalid_tool_call_count = int(report.get("invalid_tool_call_count", 0))
    offboard_rejection_count = int(report.get("offboard_rejection_count", 0))
    offboard_drop_count = int(report.get("offboard_drop_count", 0))
    watchdog_triggered = bool(report.get("watchdog_triggered"))
    timed_out = bool(report.get("timed_out"))
    tool_errors = "\n".join(report.get("tool_error_messages", []))
    intentional_t4_pause = task_id == "T4" and bool(report.get("interrupt_sent"))
    final_position = report.get("final_position") or {}
    final_z = float(final_position.get("z", 0.0)) if isinstance(final_position, dict) else 0.0
    safe_landed = final_z <= 0.2 and report.get("latest_armed") is False
    interface_mismatch = historical_interface_mismatch(report)

    if terminal_label == "CLARIFY" and actuation_seen:
        failures.append("F1")

    if invalid_tool_call_count > 0:
        failures.append("F2")

    if explicit_frame_error(report):
        failures.append("F3")

    explicit_transport_error = (
        offboard_rejection_count > 0
        or (offboard_drop_count > 0 and not intentional_t4_pause)
        or ("offboard" in tool_errors.lower() and not interface_mismatch)
        or ("setpoint" in tool_errors.lower() and not interface_mismatch)
    )
    sparse_stream = (
        float(report.get("max_setpoint_gap_s", 0.0)) > 1.0
        and not intentional_t4_pause
        and not (effective_task_success(report) and safe_landed and not explicit_transport_error)
    )
    if explicit_transport_error or sparse_stream:
        failures.append("F4")

    if watchdog_triggered or timed_out or bool(report.get("operator_intervention")):
        failures.append("F5")

    seen = []
    for code in failures:
        if code not in seen:
            seen.append(code)
    return seen


def _count_streaming_f4(report: dict[str, Any]) -> bool:
    return (
        float(report.get("max_setpoint_gap_s", 0.0)) > 1.0
        or (
            "setpoint" in "\n".join(report.get("tool_error_messages", [])).lower()
            and not historical_interface_mismatch(report)
        )
    )


def _count_mode_f4(report: dict[str, Any]) -> bool:
    errors = "\n".join(report.get("tool_error_messages", [])).lower()
    return int(report.get("offboard_rejection_count", 0)) > 0 or (
        "offboard" in errors and not historical_interface_mismatch(report)
    )


def _unsafe_abort(report: dict[str, Any]) -> bool:
    return bool(report.get("timed_out")) or bool(report.get("operator_intervention")) or bool(
        report.get("interrupt_failure")
    )


def select_c2_helpers(episode_reports: list[dict[str, Any]]) -> dict[str, Any]:
    c1_reports = [report for report in episode_reports if report.get("condition") == "C1"]
    selected: list[str] = []
    reasoning: list[str] = []

    streaming_failures = sum(
        1
        for report in c1_reports
        if "F4" in report.get("failure_codes", []) and _count_streaming_f4(report)
    )
    if streaming_failures >= 2:
        selected.append("setpoint_relay")
        reasoning.append(f"setpoint_relay enabled after {streaming_failures} post-C1 streaming/timing failures")

    mode_failures = sum(
        1
        for report in c1_reports
        if "F4" in report.get("failure_codes", []) and _count_mode_f4(report)
    )
    if mode_failures >= 2:
        selected.append("mode_guard")
        reasoning.append(f"mode_guard enabled after {mode_failures} post-C1 mode-transition failures")

    frame_failures = sum(1 for report in c1_reports if explicit_frame_error(report))
    if frame_failures >= 2:
        selected.append("frame_guard")
        reasoning.append(f"frame_guard enabled after {frame_failures} post-C1 frame/sign failures")

    if any(_unsafe_abort(report) for report in c1_reports):
        selected.append("abort_watchdog")
        reasoning.append("abort_watchdog enabled after at least one post-C1 unsafe timeout/abort event")

    return {
        "status": "frozen" if selected else "pending",
        "source": "discovery_batch_analysis",
        "selected_helpers": selected,
        "reasoning": reasoning,
        "counts": dict(
            Counter(code for report in c1_reports for code in report.get("failure_codes", []))
        ),
    }


def audit_batch(batch_dir: Path) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    interface_mismatch_episodes: list[dict[str, Any]] = []
    explicit_frame_episodes: list[dict[str, Any]] = []
    success_by_condition_task: dict[str, dict[str, int]] = {}
    metadata_coverage = {field: 0 for field in RUNTIME_METADATA_FIELDS}
    episodes_with_runtime_metadata = 0
    episodes_missing_runtime_metadata: list[str] = []

    for metrics_path in sorted(batch_dir.rglob("metrics.json")):
        with metrics_path.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
        report["task_success_current_spec"] = task_success(str(report.get("task_id")), report)
        report["historical_interface_mismatch"] = historical_interface_mismatch(report)
        report["explicit_frame_error"] = explicit_frame_error(report)
        reports.append(report)

        key = f"{report.get('condition')}:{report.get('task_id')}"
        bucket = success_by_condition_task.setdefault(key, {"success": 0, "total": 0})
        bucket["total"] += 1
        if report["task_success_current_spec"]:
            bucket["success"] += 1

        stored_success = report.get("stored_task_success", report.get("task_success"))
        if bool(stored_success) != bool(report["task_success_current_spec"]):
            mismatches.append(
                {
                    "episode": f"{report.get('condition')}:{report.get('task_id')}:{int(report.get('episode_index', 0)):02d}",
                    "stored_task_success": stored_success,
                    "current_task_success": report["task_success_current_spec"],
                }
            )
        if report["historical_interface_mismatch"]:
            interface_mismatch_episodes.append(
                {
                    "episode": f"{report.get('condition')}:{report.get('task_id')}:{int(report.get('episode_index', 0)):02d}",
                    "failure_codes": report.get("failure_codes", []),
                }
            )
        if report["explicit_frame_error"]:
            explicit_frame_episodes.append(
                {
                    "episode": f"{report.get('condition')}:{report.get('task_id')}:{int(report.get('episode_index', 0)):02d}",
                    "failure_codes": report.get("failure_codes", []),
                }
            )

        metadata_path = metrics_path.with_name("metadata.json")
        runtime_metadata = {}
        if metadata_path.exists():
            with metadata_path.open("r", encoding="utf-8") as handle:
                metadata = json.load(handle)
            runtime_metadata = metadata.get("runtime_metadata", {})
            if isinstance(runtime_metadata, dict) and runtime_metadata:
                episodes_with_runtime_metadata += 1
        episode_name = (
            f"{report.get('condition')}:{report.get('task_id')}:{int(report.get('episode_index', 0)):02d}"
        )
        missing_runtime_fields = []
        for field in RUNTIME_METADATA_FIELDS:
            value = runtime_metadata.get(field) if isinstance(runtime_metadata, dict) else None
            if value not in (None, ""):
                metadata_coverage[field] += 1
            else:
                missing_runtime_fields.append(field)
        if missing_runtime_fields:
            episodes_missing_runtime_metadata.append(episode_name)

    notes: list[str] = []
    if interface_mismatch_episodes:
        notes.append(
            "Preserved discovery contains historical generic-tool schema mismatches; treat related F2/F4 counts as contaminated by interface drift."
        )
    if mismatches:
        notes.append(
            "Stored task_success labels in preserved artifacts do not always match the current task specification; use current_task_success summaries for paper claims."
        )
    if not explicit_frame_episodes:
        notes.append(
            "The preserved artifact set does not contain repeated explicit frame/sign error traces under the current classifier."
        )
    if episodes_missing_runtime_metadata:
        notes.append(
            "Some preserved artifacts predate top-level runtime metadata capture; use current runner outputs for paper-grade reproducibility metadata in official_sim."
        )

    return {
        "batch_dir": str(batch_dir),
        "stored_vs_current_task_success_mismatches": mismatches,
        "current_task_success_by_condition_task": success_by_condition_task,
        "historical_interface_mismatch": {
            "count": len(interface_mismatch_episodes),
            "episodes": interface_mismatch_episodes,
        },
        "explicit_frame_error": {
            "count": len(explicit_frame_episodes),
            "episodes": explicit_frame_episodes,
        },
        "reproducibility_metadata": {
            "required_fields": list(RUNTIME_METADATA_FIELDS),
            "episodes_with_runtime_metadata": episodes_with_runtime_metadata,
            "episodes_missing_runtime_metadata": episodes_missing_runtime_metadata,
            "field_coverage": metadata_coverage,
        },
        "notes": notes,
    }


def review_c2_freeze_batch(episode_reports: list[dict[str, Any]]) -> dict[str, Any]:
    c2_reports = [report for report in episode_reports if report.get("condition") == "C2"]
    if not c2_reports:
        return {
            "status": "not_applicable",
            "helper_change_request": [],
            "reasoning": [],
            "counts": {},
            "task_success": {},
        }

    failure_counts = Counter(code for report in c2_reports for code in report.get("failure_codes", []))
    task_success = {
        task_id: {
            "success": sum(
                1 for report in c2_reports if report.get("task_id") == task_id and report.get("task_success")
            ),
            "total": sum(1 for report in c2_reports if report.get("task_id") == task_id),
        }
        for task_id in sorted({str(report.get("task_id")) for report in c2_reports})
    }

    reasoning: list[str] = []
    if any(not report.get("task_success") for report in c2_reports):
        reasoning.append("C2 freeze batch still has task failures, so official_sim should not start yet")
    if failure_counts.get("F2", 0):
        reasoning.append("Observed F2 during C2; fix tool-call compatibility before the next freeze pass")
    if failure_counts.get("F4", 0):
        reasoning.append("Observed residual F4 during C2; retain the relay and guarded OFFBOARD path")
    if failure_counts.get("F3", 0):
        reasoning.append("Observed at least one C2 frame/message fault; keep frame_guard active")
    if failure_counts.get("F5", 0):
        reasoning.append("Observed timeout/watchdog events during C2; tighten completion and landing behavior")

    return {
        "status": "validated" if all(report.get("task_success") for report in c2_reports) else "issues_found",
        "helper_change_request": [],
        "reasoning": reasoning,
        "counts": dict(failure_counts),
        "task_success": task_success,
    }


def analyze_batch(batch_dir: Path) -> dict[str, Any]:
    reports: list[dict[str, Any]] = []
    for metrics_path in sorted(batch_dir.rglob("metrics.json")):
        with metrics_path.open("r", encoding="utf-8") as handle:
            report = json.load(handle)
        if "stored_task_success" not in report:
            report["stored_task_success"] = report.get("task_success")
        report["task_success_current_spec"] = task_success(str(report.get("task_id")), report)
        report["historical_interface_mismatch"] = historical_interface_mismatch(report)
        report["explicit_frame_error"] = explicit_frame_error(report)
        report["task_success"] = report["task_success_current_spec"]
        report["failure_codes"] = classify_episode_report(report)
        reports.append(report)
        with metrics_path.open("w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, sort_keys=True)
            handle.write("\n")
    selection = select_c2_helpers(reports)
    freeze_review = review_c2_freeze_batch(reports)
    audit = audit_batch(batch_dir)
    return {"reports": reports, "selection": selection, "freeze_review": freeze_review, "audit": audit}
