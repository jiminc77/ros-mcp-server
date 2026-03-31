#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GEMINI_DIR="${ROOT_DIR}/.gemini"
SETTINGS_PATH="${GEMINI_DIR}/settings.json"

mkdir -p "${GEMINI_DIR}"

cat > "${SETTINGS_PATH}" <<EOF
{
  "mcpServers": {
    "ros-mcp-imece": {
      "command": "${HOME}/.local/bin/uv",
      "args": [
        "run",
        "--project",
        "${ROOT_DIR}",
        "python",
        "-m",
        "ros_mcp.imece.server"
      ],
      "cwd": "${ROOT_DIR}",
      "trust": true
    }
  }
}
EOF

printf 'Wrote %s\n' "${SETTINGS_PATH}"
