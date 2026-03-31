"""Live ROS monitoring for IMECE episodes."""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .constants import LAND_MODE, MONITOR_TOPICS
from .rosbridge import RosbridgeSubscriber


def _stamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + f".{int((time.time() % 1) * 1000):03d}Z"


@dataclass
class FlightMonitorSnapshot:
    first_setpoint_latency_s: float | None
    max_setpoint_gap_s: float
    setpoint_count: int
    max_altitude_m: float
    final_position: dict[str, float] | None
    horizontal_displacement_m: float | None
    offboard_drop_count: int
    latest_mode: str | None
    latest_armed: bool | None
    actuation_seen: bool
    state_errors: list[str] = field(default_factory=list)


class FlightMonitor:
    """Subscribe to the few MAVROS topics needed for IMECE metrics."""

    def __init__(self, host: str, port: int, log_path: Path) -> None:
        self.log_path = log_path
        self._subscriber = RosbridgeSubscriber(host, port)
        self._lock = threading.RLock()
        self._start_monotonic = time.monotonic()
        self._start_position: dict[str, float] | None = None
        self._latest_position: dict[str, float] | None = None
        self._latest_mode: str | None = None
        self._latest_armed: bool | None = None
        self._max_altitude = 0.0
        self._first_setpoint_at: float | None = None
        self._last_setpoint_at: float | None = None
        self._max_setpoint_gap = 0.0
        self._setpoint_count = 0
        self._offboard_drop_count = 0

    def start(self) -> None:
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._subscriber.subscribe(*MONITOR_TOPICS["state"], callback=self._on_state)
        self._subscriber.subscribe(*MONITOR_TOPICS["pose"], callback=self._on_pose)
        self._subscriber.subscribe(*MONITOR_TOPICS["setpoint"], callback=self._on_setpoint)

    def _write_sample(self, kind: str, payload: dict[str, Any]) -> None:
        record = {
            "timestamp": _stamp(),
            "relative_s": time.monotonic() - self._start_monotonic,
            "kind": kind,
            "payload": payload,
        }
        with self.log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=True) + "\n")

    def _on_state(self, msg: dict[str, Any]) -> None:
        mode = msg.get("mode")
        armed = msg.get("armed")
        with self._lock:
            if self._latest_mode == "OFFBOARD" and isinstance(mode, str) and mode != "OFFBOARD":
                if mode != LAND_MODE and self._latest_position is not None and self._latest_position["z"] > 0.3:
                    self._offboard_drop_count += 1
            if isinstance(mode, str):
                self._latest_mode = mode
            if isinstance(armed, bool):
                self._latest_armed = armed
        self._write_sample("state", msg)

    def _on_pose(self, msg: dict[str, Any]) -> None:
        pose = dict(msg.get("pose") or {})
        position = dict(pose.get("position") or {})
        try:
            current = {
                "x": float(position["x"]),
                "y": float(position["y"]),
                "z": float(position["z"]),
            }
        except (KeyError, TypeError, ValueError):
            return
        with self._lock:
            if self._start_position is None:
                self._start_position = current
            self._latest_position = current
            self._max_altitude = max(self._max_altitude, current["z"])
        self._write_sample("pose", msg)

    def _on_setpoint(self, msg: dict[str, Any]) -> None:
        now = time.monotonic()
        with self._lock:
            if self._first_setpoint_at is None:
                self._first_setpoint_at = now
            if self._last_setpoint_at is not None:
                self._max_setpoint_gap = max(self._max_setpoint_gap, now - self._last_setpoint_at)
            self._last_setpoint_at = now
            self._setpoint_count += 1
        self._write_sample("setpoint", msg)

    def snapshot(self) -> FlightMonitorSnapshot:
        with self._lock:
            if self._start_position is not None and self._latest_position is not None:
                dx = self._latest_position["x"] - self._start_position["x"]
                dy = self._latest_position["y"] - self._start_position["y"]
                horizontal = math.hypot(dx, dy)
            else:
                horizontal = None
            return FlightMonitorSnapshot(
                first_setpoint_latency_s=(
                    None
                    if self._first_setpoint_at is None
                    else self._first_setpoint_at - self._start_monotonic
                ),
                max_setpoint_gap_s=self._max_setpoint_gap,
                setpoint_count=self._setpoint_count,
                max_altitude_m=self._max_altitude,
                final_position=self._latest_position,
                horizontal_displacement_m=horizontal,
                offboard_drop_count=self._offboard_drop_count,
                latest_mode=self._latest_mode,
                latest_armed=self._latest_armed,
                actuation_seen=self._first_setpoint_at is not None,
                state_errors=list(self._subscriber.status_errors),
            )

    def stop(self) -> None:
        self._subscriber.stop()
