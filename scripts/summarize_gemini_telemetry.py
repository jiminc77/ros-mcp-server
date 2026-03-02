#!/usr/bin/env python3
"""Summarize Gemini CLI telemetry into prompt/tool timing reports.

This parser is intentionally tolerant because telemetry payload shapes can vary
between Gemini CLI versions and OpenTelemetry exporters.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


DURATION_KEYS = (
    "duration_ms",
    "durationMs",
    "latency_ms",
    "elapsed_ms",
)
PROMPT_ID_KEYS = ("prompt_id", "promptId", "turn_id", "turnId", "request_id", "requestId")
PROMPT_TEXT_KEYS = ("prompt", "user_prompt", "text", "prompt_text", "input")
TOOL_NAME_KEYS = (
    "tool_name",
    "toolName",
    "function_name",
    "functionName",
    "name",
    "tool",
    "mcp_tool_name",
)
START_KEYS = (
    "start_time",
    "startTime",
    "start_timestamp",
    "startTimestamp",
)
END_KEYS = (
    "end_time",
    "endTime",
    "end_timestamp",
    "endTimestamp",
    "timestamp",
)
STATUS_KEYS = ("status", "result", "outcome", "success", "error", "error_code", "errorCode")


@dataclass
class Event:
    raw_name: str
    name: str
    timestamp: datetime | None
    duration_ms: float | None
    attributes: dict[str, Any]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Summarize Gemini telemetry logs")
    parser.add_argument("--input", required=True, help="Path to raw telemetry file")
    parser.add_argument("--output-text", required=True, help="Path to human-readable report")
    parser.add_argument("--output-json", required=True, help="Path to structured summary JSON")
    parser.add_argument("--session-id", default="unknown", help="Session identifier")
    return parser.parse_args()


def load_json_objects(path: Path) -> list[Any]:
    if not path.exists():
        return []

    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return []

    objects: list[Any] = []

    # Try NDJSON first.
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped[0] not in "[{":
            continue
        try:
            objects.append(json.loads(stripped))
        except json.JSONDecodeError:
            continue

    if objects:
        return objects

    # Fallback to one full JSON document.
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return []

    if isinstance(parsed, list):
        return parsed
    return [parsed]


def parse_otlp_any_value(value: Any) -> Any:
    if not isinstance(value, dict):
        return value

    if "stringValue" in value:
        return value["stringValue"]
    if "intValue" in value:
        return safe_number(value["intValue"])
    if "doubleValue" in value:
        return safe_number(value["doubleValue"])
    if "boolValue" in value:
        return bool(value["boolValue"])
    if "bytesValue" in value:
        return value["bytesValue"]

    if "arrayValue" in value:
        arr = value["arrayValue"]
        vals = arr.get("values", []) if isinstance(arr, dict) else arr
        return [parse_otlp_any_value(v) for v in vals]

    if "kvlistValue" in value:
        kv = value["kvlistValue"]
        vals = kv.get("values", []) if isinstance(kv, dict) else kv
        out: dict[str, Any] = {}
        for item in vals:
            if isinstance(item, dict) and "key" in item:
                out[str(item["key"])] = parse_otlp_any_value(item.get("value"))
        return out

    return value


def parse_attributes(raw_attrs: Any) -> dict[str, Any]:
    if raw_attrs is None:
        return {}

    if isinstance(raw_attrs, list):
        out: dict[str, Any] = {}
        for item in raw_attrs:
            if isinstance(item, dict) and "key" in item:
                out[str(item["key"])] = parse_otlp_any_value(item.get("value"))
        return out

    if isinstance(raw_attrs, dict):
        out: dict[str, Any] = {}
        for key, value in raw_attrs.items():
            if isinstance(value, dict):
                out[str(key)] = parse_otlp_any_value(value)
            else:
                out[str(key)] = value
        return out

    return {}


def safe_number(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return 1.0 if value else 0.0
    if isinstance(value, (int, float)):
        if math.isnan(float(value)):
            return None
        return float(value)
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None

    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)

    if isinstance(value, (int, float)):
        return epoch_to_datetime(float(value))

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None

        # Numeric timestamp string.
        numeric = safe_number(stripped)
        if numeric is not None:
            return epoch_to_datetime(numeric)

        if stripped.endswith("Z"):
            stripped = stripped[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(stripped)
        except ValueError:
            return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    return None


def epoch_to_datetime(value: float) -> datetime | None:
    # Heuristic conversion based on magnitude.
    if value <= 0:
        return None

    # ns/us/ms/sec
    if value > 1e17:
        seconds = value / 1e9
    elif value > 1e14:
        seconds = value / 1e6
    elif value > 1e11:
        seconds = value / 1e3
    else:
        seconds = value

    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def event_name_from_record(record: dict[str, Any], attrs: dict[str, Any]) -> str | None:
    for key in ("name", "event_name", "eventName", "event", "eventType"):
        value = record.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    body = record.get("body")
    if isinstance(body, str) and body.strip():
        return body.strip()
    if isinstance(body, dict):
        body_val = parse_otlp_any_value(body)
        if isinstance(body_val, str) and body_val.strip():
            return body_val.strip()

    for key in ("event_name", "eventName", "event"):
        value = attrs.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    return None


def normalize_event_name(name: str) -> str:
    stripped = name.strip()
    if stripped.startswith("gemini_cli."):
        stripped = stripped[len("gemini_cli.") :]
    return stripped


def extract_duration_ms(record: dict[str, Any], attrs: dict[str, Any]) -> float | None:
    for key in DURATION_KEYS:
        value = safe_number(attrs.get(key))
        if value is not None:
            return value

    for key in DURATION_KEYS:
        value = safe_number(record.get(key))
        if value is not None:
            return value

    return None


def extract_timestamp(record: dict[str, Any], attrs: dict[str, Any]) -> datetime | None:
    for key in ("timestamp", "time", "timeUnixNano", "observedTimeUnixNano"):
        ts = parse_timestamp(record.get(key))
        if ts is not None:
            return ts

    for key in END_KEYS:
        ts = parse_timestamp(attrs.get(key))
        if ts is not None:
            return ts

    return None


def should_keep_event(raw_name: str | None, normalized: str | None) -> bool:
    if not raw_name and not normalized:
        return False

    candidates = [v for v in (raw_name, normalized) if isinstance(v, str)]
    for cand in candidates:
        if cand.startswith("gemini_cli."):
            return True
        if cand in {
            "user_prompt",
            "tool_call",
            "tool_decision",
            "api_request",
            "api_response",
            "api_error",
            "chat_compression",
            "next_speaker_check",
            "token_count",
        }:
            return True
    return False


def walk_events(node: Any, out: list[Event]) -> None:
    if isinstance(node, dict):
        attrs = parse_attributes(node.get("attributes"))
        raw_name = event_name_from_record(node, attrs)
        name = normalize_event_name(raw_name) if raw_name else ""

        if should_keep_event(raw_name, name):
            out.append(
                Event(
                    raw_name=raw_name or "",
                    name=name,
                    timestamp=extract_timestamp(node, attrs),
                    duration_ms=extract_duration_ms(node, attrs),
                    attributes=attrs,
                )
            )

        for value in node.values():
            walk_events(value, out)
        return

    if isinstance(node, list):
        for item in node:
            walk_events(item, out)


def first_value(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        value = mapping.get(key)
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        return value
    return None


def iso_or_none(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).isoformat()


def compute_start_end(
    event: Event,
) -> tuple[datetime | None, datetime | None, float | None]:
    attrs = event.attributes

    start = None
    for key in START_KEYS:
        start = parse_timestamp(attrs.get(key))
        if start is not None:
            break

    end = event.timestamp
    if end is None:
        for key in END_KEYS:
            end = parse_timestamp(attrs.get(key))
            if end is not None:
                break

    duration_ms = event.duration_ms

    if duration_ms is None and start is not None and end is not None:
        duration_ms = max((end - start).total_seconds() * 1000.0, 0.0)

    if start is None and end is not None and duration_ms is not None:
        start = end - timedelta(milliseconds=duration_ms)

    if end is None and start is not None and duration_ms is not None:
        end = start + timedelta(milliseconds=duration_ms)

    return start, end, duration_ms


def normalize_status(attrs: dict[str, Any]) -> str:
    value = first_value(attrs, STATUS_KEYS)
    if isinstance(value, bool):
        return "ok" if value else "error"
    if value is None:
        return "unknown"
    return str(value)


def sort_key_time(value: datetime | None) -> tuple[int, datetime]:
    if value is None:
        return (1, datetime.max.replace(tzinfo=timezone.utc))
    return (0, value)


def build_summary(events: list[Event], source_file: Path, session_id: str) -> dict[str, Any]:
    prompt_events = [event for event in events if event.name == "user_prompt"]
    tool_events = [event for event in events if event.name == "tool_call"]

    prompts: list[dict[str, Any]] = []

    for idx, event in enumerate(prompt_events, start=1):
        attrs = event.attributes
        start_dt, end_dt, duration_ms = compute_start_end(event)
        prompt_id_raw = first_value(attrs, PROMPT_ID_KEYS)
        prompt_id = str(prompt_id_raw) if prompt_id_raw is not None else f"prompt-{idx}"
        prompt_text = first_value(attrs, PROMPT_TEXT_KEYS)

        prompts.append(
            {
                "index": idx,
                "prompt_id": prompt_id,
                "prompt_text": str(prompt_text) if prompt_text is not None else None,
                "start_time": iso_or_none(start_dt),
                "end_time": iso_or_none(end_dt),
                "duration_ms": duration_ms,
                "attributes": attrs,
                "tools": [],
            }
        )

    prompts.sort(
        key=lambda item: sort_key_time(
            parse_timestamp(item.get("start_time")) or parse_timestamp(item.get("end_time"))
        )
    )
    for index, prompt in enumerate(prompts, start=1):
        prompt["index"] = index

    prompt_id_to_indexes: dict[str, list[int]] = {}
    for idx, prompt in enumerate(prompts):
        prompt_id_to_indexes.setdefault(prompt["prompt_id"], []).append(idx)

    orphan_tools: list[dict[str, Any]] = []

    for event in tool_events:
        attrs = event.attributes
        start_dt, end_dt, duration_ms = compute_start_end(event)

        tool_name_raw = first_value(attrs, TOOL_NAME_KEYS)
        tool_name = str(tool_name_raw) if tool_name_raw is not None else "unknown_tool"

        tool_data = {
            "tool_name": tool_name,
            "start_time": iso_or_none(start_dt),
            "end_time": iso_or_none(end_dt),
            "duration_ms": duration_ms,
            "status": normalize_status(attrs),
            "prompt_id": None,
            "attributes": attrs,
        }

        prompt_id_raw = first_value(attrs, PROMPT_ID_KEYS)
        if prompt_id_raw is not None:
            prompt_id = str(prompt_id_raw)
            candidates = prompt_id_to_indexes.get(prompt_id, [])
            if candidates:
                target = prompts[candidates[-1]]
                tool_data["prompt_id"] = prompt_id
                target["tools"].append(tool_data)
                continue

        # Fallback: assign to latest prompt that already started.
        chosen_idx = -1
        tool_end = end_dt or start_dt
        for idx, prompt in enumerate(prompts):
            prompt_start = parse_timestamp(prompt.get("start_time"))
            if tool_end is None:
                continue
            if prompt_start is None or prompt_start <= tool_end:
                chosen_idx = idx

        if chosen_idx >= 0:
            tool_data["prompt_id"] = prompts[chosen_idx]["prompt_id"]
            prompts[chosen_idx]["tools"].append(tool_data)
        else:
            orphan_tools.append(tool_data)

    for prompt in prompts:
        prompt["tool_count"] = len(prompt["tools"])
        prompt["tools"].sort(
            key=lambda item: sort_key_time(
                parse_timestamp(item.get("start_time")) or parse_timestamp(item.get("end_time"))
            )
        )

    return {
        "session_id": session_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_file": str(source_file),
        "event_count": len(events),
        "prompt_count": len(prompts),
        "tool_call_count": len(tool_events),
        "prompts": prompts,
        "orphan_tool_calls": orphan_tools,
    }


def format_duration_ms(value: float | None) -> str:
    if value is None:
        return "unknown"
    if value >= 1000:
        return f"{value:.1f} ms ({value / 1000.0:.3f} s)"
    return f"{value:.1f} ms"


def render_text_report(summary: dict[str, Any]) -> str:
    lines: list[str] = []
    lines.append("Gemini CLI Telemetry Report")
    lines.append(f"session_id: {summary['session_id']}")
    lines.append(f"generated_at: {summary['generated_at']}")
    lines.append(f"source_file: {summary['source_file']}")
    lines.append(f"events_parsed: {summary['event_count']}")
    lines.append(f"prompt_count: {summary['prompt_count']}")
    lines.append(f"tool_call_count: {summary['tool_call_count']}")
    lines.append("")

    prompts = summary.get("prompts", [])
    if not prompts:
        lines.append("No user_prompt events were found.")
        return "\n".join(lines) + "\n"

    for prompt in prompts:
        lines.append(f"[Prompt {prompt['index']}] id={prompt['prompt_id']}")
        lines.append(f"enter_time_utc: {prompt.get('start_time') or 'unknown'}")
        lines.append(f"done_time_utc: {prompt.get('end_time') or 'unknown'}")
        lines.append(f"elapsed: {format_duration_ms(prompt.get('duration_ms'))}")

        prompt_text = prompt.get("prompt_text")
        if isinstance(prompt_text, str) and prompt_text.strip():
            compact = " ".join(prompt_text.split())
            lines.append(f"prompt_text: {compact}")

        lines.append(f"tool_count: {prompt['tool_count']}")

        if prompt["tools"]:
            for tool in prompt["tools"]:
                lines.append(
                    "tool: "
                    f"name={tool['tool_name']} | "
                    f"start={tool.get('start_time') or 'unknown'} | "
                    f"end={tool.get('end_time') or 'unknown'} | "
                    f"elapsed={format_duration_ms(tool.get('duration_ms'))} | "
                    f"status={tool.get('status', 'unknown')}"
                )
        else:
            lines.append("tool: none")
        lines.append("")

    orphans = summary.get("orphan_tool_calls", [])
    if orphans:
        lines.append("[Orphan Tool Calls]")
        for tool in orphans:
            lines.append(
                "tool: "
                f"name={tool['tool_name']} | "
                f"start={tool.get('start_time') or 'unknown'} | "
                f"end={tool.get('end_time') or 'unknown'} | "
                f"elapsed={format_duration_ms(tool.get('duration_ms'))} | "
                f"status={tool.get('status', 'unknown')}"
            )

    return "\n".join(lines) + "\n"


def write_outputs(summary: dict[str, Any], output_text: Path, output_json: Path) -> None:
    output_text.parent.mkdir(parents=True, exist_ok=True)
    output_json.parent.mkdir(parents=True, exist_ok=True)

    output_json.write_text(json.dumps(summary, ensure_ascii=True, indent=2), encoding="utf-8")
    output_text.write_text(render_text_report(summary), encoding="utf-8")


def main() -> int:
    args = parse_args()
    input_path = Path(args.input).expanduser().resolve()
    output_text = Path(args.output_text).expanduser()
    output_json = Path(args.output_json).expanduser()

    objects = load_json_objects(input_path)

    events: list[Event] = []
    for obj in objects:
        walk_events(obj, events)

    summary = build_summary(events, input_path, args.session_id)
    write_outputs(summary, output_text, output_json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
