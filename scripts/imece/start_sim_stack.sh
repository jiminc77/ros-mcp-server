#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME_DIR="${ROOT_DIR}/artifacts/imece/runtime"
PX4_DIR="${PX4_DIR:-/home/husl-ai/workspace/PX4-Autopilot}"

mkdir -p "${RUNTIME_DIR}"
KEEP_PX4_LOG="${IMECE_KEEP_PX4_LOG:-0}"

start_service() {
  local name="$1"
  local command="$2"
  local keep_log="${3:-1}"
  local log_path="${RUNTIME_DIR}/${name}.log"
  if [[ "${keep_log}" == "1" ]]; then
    : > "${log_path}"
    nohup bash -lc "${command}" > "${log_path}" 2>&1 < /dev/null &
  else
    rm -f "${log_path}"
    nohup bash -lc "${command}" > /dev/null 2>&1 < /dev/null &
  fi
  echo $! > "${RUNTIME_DIR}/${name}.pid"
}

start_ros_service() {
  local name="$1"
  local command="$2"
  local log_path="${RUNTIME_DIR}/${name}.log"
  : > "${log_path}"
  nohup env \
    -u VIRTUAL_ENV \
    -u PYTHONHOME \
    -u PYTHONPATH \
    -u UV_ACTIVE \
    -u UV_PROJECT_ENVIRONMENT \
    -u UV_PYTHON \
    HOME="${HOME}" \
    USER="${USER:-husl-ai}" \
    PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
    bash -lc "${command}" > "${log_path}" 2>&1 < /dev/null &
  echo $! > "${RUNTIME_DIR}/${name}.pid"
}

start_service px4 "cd '${PX4_DIR}' && exec make px4_sitl gz_x500" "${KEEP_PX4_LOG}"
start_ros_service mavros "source /opt/ros/jazzy/setup.bash && exec ros2 launch mavros px4.launch fcu_url:=udp://:14540@127.0.0.1:14557"
start_ros_service rosbridge "source /opt/ros/jazzy/setup.bash && exec ros2 launch rosbridge_server rosbridge_websocket_launch.xml port:=9090"

printf 'Started PX4, MAVROS, and rosbridge. PID files are in %s\n' "${RUNTIME_DIR}"
