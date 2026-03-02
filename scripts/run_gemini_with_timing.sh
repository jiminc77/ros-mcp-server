#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PARSER="${SCRIPT_DIR}/summarize_gemini_telemetry.py"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

GEMINI_BIN="${GEMINI_BIN:-gemini}"
LOG_ROOT="${GEMINI_TIMING_LOG_DIR:-$HOME/.gemini/timing_logs}"
SESSION_ID="${GEMINI_TIMING_SESSION_ID:-$(date '+%Y%m%d-%H%M%S')}"
SESSION_DIR="${LOG_ROOT}/${SESSION_ID}"
RAW_LOG="${SESSION_DIR}/telemetry_raw.jsonl"
TEXT_REPORT="${SESSION_DIR}/session_report.txt"
JSON_REPORT="${SESSION_DIR}/session_report.json"

if ! command -v "${GEMINI_BIN}" >/dev/null 2>&1; then
  echo "[gemini-timing] error: '${GEMINI_BIN}' command not found" >&2
  exit 127
fi

mkdir -p "${SESSION_DIR}"

# Keep default Gemini CLI UI and behavior while enabling local telemetry export.
# New telemetry env key (current docs) + legacy key (backward compatibility).
export GEMINI_TELEMETRY_ENABLED=true
export GEMINI_TELEMETRY=true
export GEMINI_TELEMETRY_TARGET=local
export GEMINI_TELEMETRY_OUTFILE="${RAW_LOG}"
export GEMINI_TELEMETRY_LOG_PROMPTS=true

echo "[gemini-timing] session_id=${SESSION_ID}" >&2
echo "[gemini-timing] raw_log=${RAW_LOG}" >&2
echo "[gemini-timing] workspace_root=${PROJECT_ROOT}" >&2

TELEMETRY_ARGS=()
if "${GEMINI_BIN}" --help 2>&1 | grep -q -- "--telemetry"; then
  TELEMETRY_ARGS=(
    --telemetry
    --telemetry-target local
    --telemetry-outfile "${RAW_LOG}"
    --telemetry-log-prompts
  )
fi

set +e
(
  cd "${PROJECT_ROOT}"
  "${GEMINI_BIN}" "${TELEMETRY_ARGS[@]}" "$@"
)
EXIT_CODE=$?
set -e

if [[ -s "${RAW_LOG}" ]]; then
  if command -v python3 >/dev/null 2>&1; then
    set +e
    python3 "${PARSER}" \
      --input "${RAW_LOG}" \
      --output-text "${TEXT_REPORT}" \
      --output-json "${JSON_REPORT}" \
      --session-id "${SESSION_ID}"
    PARSE_CODE=$?
    set -e

    if [[ ${PARSE_CODE} -eq 0 ]]; then
      echo "[gemini-timing] text_report=${TEXT_REPORT}" >&2
      echo "[gemini-timing] json_report=${JSON_REPORT}" >&2
    else
      echo "[gemini-timing] warning: summary generation failed (exit=${PARSE_CODE})" >&2
    fi
  else
    echo "[gemini-timing] warning: python3 not found, skipped summary generation" >&2
  fi
else
  echo "[gemini-timing] warning: telemetry raw log is empty (${RAW_LOG})" >&2
  echo "[gemini-timing] hint: check ~/.gemini/settings.json telemetry.enabled/target and Gemini CLI version." >&2
fi

exit ${EXIT_CODE}
