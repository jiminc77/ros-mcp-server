import os

from ros_mcp.imece.gemini import GeminiRunner, extract_terminal_marker, parse_stream_event


def test_parse_stream_event_reads_json_object():
    event = parse_stream_event('{"type":"init","session_id":"abc"}\n')
    assert event == {"type": "init", "session_id": "abc"}


def test_parse_stream_event_rejects_non_json():
    assert parse_stream_event("not json") is None


def test_extract_terminal_marker_uses_last_tag():
    text = "Working\nCLARIFY: which side?\nMore\nDONE: complete"
    label, payload = extract_terminal_marker(text)
    assert label == "DONE"
    assert payload == "complete"


def test_gemini_runner_keeps_result_status_when_process_exits_late(tmp_path):
    script = tmp_path / "fake_gemini.sh"
    script.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "printf '%s\\n' '{\"type\":\"init\",\"session_id\":\"sess-1\"}'",
                "printf '%s\\n' '{\"type\":\"message\",\"role\":\"assistant\",\"content\":\"DONE: ok\"}'",
                "printf '%s\\n' '{\"type\":\"result\",\"status\":\"success\",\"stats\":{\"tool_calls\":0}}'",
                "sleep 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    os.chmod(script, 0o755)
    policy = tmp_path / "policy.toml"
    policy.write_text("", encoding="utf-8")

    runner = GeminiRunner(binary=str(script), cwd=tmp_path, base_env=os.environ.copy())
    result = runner.run_turn(
        prompt="test",
        trace_path=tmp_path / "trace.jsonl",
        stderr_path=tmp_path / "stderr.log",
        policy_path=policy,
        turn_index=1,
        timeout_s=0.6,
    )

    assert result.result_status == "success"
    assert result.terminal_label == "DONE"
    assert result.terminal_payload == "ok"
