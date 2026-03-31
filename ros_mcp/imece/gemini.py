"""Gemini CLI helpers for IMECE."""

from __future__ import annotations

import json
import os
import re
import selectors
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from .constants import MCP_SERVER_NAME

TERMINAL_RE = re.compile(r"(?:^|\n)(CLARIFY|REFUSE|DONE)\s*:\s*(.*)")


def parse_stream_event(line: str) -> dict[str, Any] | None:
    stripped = line.strip()
    if not stripped:
        return None
    try:
        event = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(event, dict):
        return None
    return event


def extract_terminal_marker(text: str) -> tuple[str | None, str | None]:
    matches = TERMINAL_RE.findall(text)
    if not matches:
        return None, None
    label, payload = matches[-1]
    return label, payload.strip()


@dataclass
class GeminiTurnResult:
    session_id: str | None
    assistant_text: str
    terminal_label: str | None
    terminal_payload: str | None
    result_status: str | None
    return_code: int
    stats: dict[str, Any] = field(default_factory=dict)
    tool_call_count: int = 0
    invalid_tool_call_count: int = 0
    tool_error_messages: list[str] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)


class GeminiRunner:
    """Small non-interactive Gemini CLI wrapper with JSONL trace capture."""

    def __init__(
        self,
        *,
        binary: str = "gemini",
        cwd: Path,
        base_env: dict[str, str],
    ) -> None:
        self.binary = binary
        self.cwd = cwd
        self.base_env = dict(base_env)

    def run_turn(
        self,
        *,
        prompt: str,
        trace_path: Path,
        stderr_path: Path,
        policy_path: Path,
        turn_index: int,
        timeout_s: float,
        resume_session_id: str | None = None,
        tick: Callable[[float], None] | None = None,
    ) -> GeminiTurnResult:
        trace_path.parent.mkdir(parents=True, exist_ok=True)
        stderr_path.parent.mkdir(parents=True, exist_ok=True)

        command = [
            self.binary,
            "-p",
            prompt,
            "--output-format",
            "stream-json",
            "--policy",
            str(policy_path),
            "--allowed-mcp-server-names",
            MCP_SERVER_NAME,
        ]
        if resume_session_id:
            command.extend(["--resume", resume_session_id])

        with trace_path.open("a", encoding="utf-8") as trace_handle, stderr_path.open(
            "a", encoding="utf-8"
        ) as stderr_handle:
            process = subprocess.Popen(
                command,
                cwd=self.cwd,
                env=self.base_env,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=stderr_handle,
                text=False,
                bufsize=0,
            )
            assert process.stdout is not None

            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)

            start = time.monotonic()
            assistant_parts: list[str] = []
            session_id: str | None = None
            result_status: str | None = None
            stats: dict[str, Any] = {}
            tool_errors: list[str] = []
            invalid_tool_call_count = 0
            tool_call_count = 0
            events: list[dict[str, Any]] = []
            saw_result = False
            stdout_buffer = ""

            while True:
                elapsed = time.monotonic() - start
                if tick:
                    tick(elapsed)

                if elapsed > timeout_s:
                    process.kill()
                    process.wait(timeout=5)
                    result_status = "timeout"
                    break

                ready = selector.select(timeout=0.25)
                if ready:
                    chunk = os.read(process.stdout.fileno(), 65536)
                    if chunk:
                        stdout_buffer += chunk.decode("utf-8", errors="replace")
                    while "\n" in stdout_buffer:
                        line, stdout_buffer = stdout_buffer.split("\n", 1)
                        event = parse_stream_event(line)
                        if event is None:
                            continue
                        event_record = {"turn_index": turn_index, **event}
                        trace_handle.write(json.dumps(event_record, ensure_ascii=True) + "\n")
                        trace_handle.flush()
                        events.append(event_record)

                        event_type = event.get("type")
                        if event_type == "init":
                            session_id = event.get("session_id")
                        elif event_type == "message" and event.get("role") == "assistant":
                            content = event.get("content", "")
                            if isinstance(content, str):
                                assistant_parts.append(content)
                        elif event_type == "tool_use":
                            tool_call_count += 1
                        elif event_type == "tool_result":
                            if event.get("status") == "error":
                                invalid_tool_call_count += 1
                                error = event.get("error", {})
                                if isinstance(error, dict):
                                    message = error.get("message")
                                    if isinstance(message, str):
                                        tool_errors.append(message)
                        elif event_type == "result":
                            result_status = event.get("status")
                            raw_stats = event.get("stats")
                            if isinstance(raw_stats, dict):
                                stats = raw_stats
                            saw_result = True
                            break
                elif process.poll() is not None:
                    break

                if saw_result:
                    break

            if process.poll() is None:
                process.wait(timeout=5)

        return_code = process.returncode or 0
        if result_status is None:
            if return_code != 0:
                result_status = "process_error"
            elif not events:
                result_status = "no_output"

        assistant_text = "".join(assistant_parts).strip()
        terminal_scan_text = "\n".join(part for part in assistant_parts if part).strip()
        terminal_label, terminal_payload = extract_terminal_marker(assistant_text)
        if terminal_label is None:
            terminal_label, terminal_payload = extract_terminal_marker(terminal_scan_text)
        return GeminiTurnResult(
            session_id=session_id,
            assistant_text=assistant_text,
            terminal_label=terminal_label,
            terminal_payload=terminal_payload,
            result_status=result_status,
            return_code=return_code,
            stats=stats,
            tool_call_count=tool_call_count,
            invalid_tool_call_count=invalid_tool_call_count,
            tool_error_messages=tool_errors,
            events=events,
        )
