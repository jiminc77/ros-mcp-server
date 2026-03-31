#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/artifacts/imece/runtime"

for name in rosbridge mavros px4; do
  pid_file="${RUNTIME_DIR}/${name}.pid"
  if [[ -f "${pid_file}" ]]; then
    pid="$(cat "${pid_file}")"
    kill "${pid}" 2>/dev/null || true
    pkill -TERM -P "${pid}" 2>/dev/null || true
    rm -f "${pid_file}"
  fi
done

extra_patterns=(
  "make px4_sitl gz_x500"
  "/build/px4_sitl_default/bin/px4"
  "ros2 launch mavros px4.launch"
  "/opt/ros/jazzy/lib/mavros/mavros_node"
  "ros2 launch rosbridge_server rosbridge_websocket_launch.xml"
  "/opt/ros/jazzy/lib/rosbridge_server/rosbridge_websocket"
  "gz sim --verbose=1 -r -s /home/husl-ai/workspace/PX4-Autopilot/Tools/simulation/gz/worlds/default.sdf"
  "gz sim -g"
)

for pattern in "${extra_patterns[@]}"; do
  pkill -TERM -f "${pattern}" 2>/dev/null || true
done

sleep 2

for pattern in "${extra_patterns[@]}"; do
  pkill -KILL -f "${pattern}" 2>/dev/null || true
done

printf 'Requested shutdown for stack processes listed in %s\n' "${RUNTIME_DIR}"
