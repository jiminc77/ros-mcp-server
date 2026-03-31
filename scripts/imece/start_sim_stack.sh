#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/artifacts/imece/runtime"
PX4_DIR="${PX4_DIR:-/home/husl-ai/workspace/PX4-Autopilot}"

mkdir -p "${RUNTIME_DIR}"

nohup bash -lc "cd '${PX4_DIR}' && make px4_sitl gz_x500" \
  > "${RUNTIME_DIR}/px4.stdout.log" 2> "${RUNTIME_DIR}/px4.stderr.log" &
echo $! > "${RUNTIME_DIR}/px4.pid"

nohup bash -lc "source /opt/ros/jazzy/setup.bash && ros2 launch mavros px4.launch fcu_url:=udp://:14540@127.0.0.1:14557" \
  > "${RUNTIME_DIR}/mavros.stdout.log" 2> "${RUNTIME_DIR}/mavros.stderr.log" &
echo $! > "${RUNTIME_DIR}/mavros.pid"

nohup bash -lc "source /opt/ros/jazzy/setup.bash && ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=9090" \
  > "${RUNTIME_DIR}/rosbridge.stdout.log" 2> "${RUNTIME_DIR}/rosbridge.stderr.log" &
echo $! > "${RUNTIME_DIR}/rosbridge.pid"

printf 'Started PX4, MAVROS, and rosbridge. PID files are in %s\n' "${RUNTIME_DIR}"
