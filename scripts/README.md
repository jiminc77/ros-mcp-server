## Prompt/Tool Timing Automation

```bash
cd /<ABSOLUTE_PATH>/ros-mcp-server
./scripts/run_gemini_with_timing.sh
```

The wrapper keeps normal Gemini CLI behavior, and only adds telemetry env vars:
- `GEMINI_TELEMETRY=true`
- `GEMINI_TELEMETRY_TARGET=local`
- `GEMINI_TELEMETRY_OUTFILE=<session_raw_log>`

### Generated logs

By default logs are written to:
`~/.gemini/timing_logs/<session_id>/`

Files:
- `telemetry_raw.jsonl` (raw telemetry for analysis)
- `session_report.txt` (human-readable summary)
- `session_report.json` (structured summary)

`session_report.txt` includes:
- Prompt start/end timestamps (`enter` -> `done`)
- Prompt elapsed time
- Tool call name and start/end timestamps
- Tool call elapsed time and status

Environment overrides:
- `GEMINI_TIMING_LOG_DIR` to change log output root directory
- `GEMINI_BIN` to use a non-default Gemini executable