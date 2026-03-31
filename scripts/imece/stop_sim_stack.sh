#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/artifacts/imece/runtime"

for name in rosbridge mavros px4; do
  pid_file="${RUNTIME_DIR}/${name}.pid"
  if [[ -f "${pid_file}" ]]; then
    pid="$(cat "${pid_file}")"
    kill "${pid}" 2>/dev/null || true
    rm -f "${pid_file}"
  fi
done

printf 'Requested shutdown for stack processes listed in %s\n' "${RUNTIME_DIR}"
