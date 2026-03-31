"""Non-semantic C2 helper implementations."""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path
from typing import Any

from .constants import (
    ARMING_SERVICE,
    ARMING_SERVICE_TYPE,
    LAND_MODE,
    OFFBOARD_MODE,
    SET_MODE_SERVICE,
    SET_MODE_SERVICE_TYPE,
)
from .rosbridge import RosbridgeRequester


class PoseRelay:
    """Maintains a last-valid local PoseStamped target at a fixed rate."""

    def __init__(
        self,
        requester: RosbridgeRequester,
        *,
        topic: str = "/mavros/setpoint_position/local",
        msg_type: str = "geometry_msgs/msg/PoseStamped",
        rate_hz: float = 20.0,
        frame_guard_enabled: bool = False,
    ) -> None:
        self.requester = requester
        self.topic = topic
        self.msg_type = msg_type
        self.rate_hz = rate_hz
        self.frame_guard_enabled = frame_guard_enabled
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._target: dict[str, Any] | None = None
        self.publish_count = 0
        self.last_publish_monotonic: float | None = None
        self.last_error: str | None = None

    def _normalize_target(self, target: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(target, dict):
            raise ValueError("target must be a PoseStamped-like dictionary")

        header = dict(target.get("header") or {})
        pose = dict(target.get("pose") or {})
        position = dict(pose.get("position") or {})
        orientation = dict(pose.get("orientation") or {})

        try:
            x = float(position["x"])
            y = float(position["y"])
            z = float(position["z"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("target.pose.position.{x,y,z} must be present and numeric") from exc

        if any(not math.isfinite(value) for value in (x, y, z)):
            raise ValueError("target pose values must be finite")

        frame_id = str(header.get("frame_id") or "map").strip() or "map"
        if self.frame_guard_enabled:
            if frame_id.lower() in {"base_link", "body", "frd", "ned"}:
                raise ValueError(f"frame_guard rejected body/NED-like frame_id: {frame_id}")
            if z < 0.0:
                raise ValueError("frame_guard rejected negative local ENU altitude")

        return {
            "header": {
                "stamp": {"sec": 0, "nanosec": 0},
                "frame_id": frame_id,
            },
            "pose": {
                "position": {"x": x, "y": y, "z": z},
                "orientation": {
                    "x": float(orientation.get("x", 0.0)),
                    "y": float(orientation.get("y", 0.0)),
                    "z": float(orientation.get("z", 0.0)),
                    "w": float(orientation.get("w", 1.0)),
                },
            },
        }

    def set_target(self, target: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_target(target)
        with self._lock:
            self._target = normalized
            self.last_error = None
            if self._thread is None or not self._thread.is_alive():
                self._stop.clear()
                self._thread = threading.Thread(target=self._run, daemon=True)
                self._thread.start()
        return self.status()

    def _run(self) -> None:
        period = 1.0 / self.rate_hz
        while not self._stop.is_set():
            with self._lock:
                target = self._target
            if target is not None:
                try:
                    self.requester.publish(self.topic, self.msg_type, target)
                    self.publish_count += 1
                    self.last_publish_monotonic = time.monotonic()
                except Exception as exc:  # pragma: no cover - depends on live rosbridge
                    self.last_error = str(exc)
            time.sleep(period)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "active": self._thread is not None and self._thread.is_alive(),
                "publish_count": self.publish_count,
                "last_publish_monotonic": self.last_publish_monotonic,
                "last_error": self.last_error,
                "target": self._target,
            }


class ModeGuard:
    """Guarded OFFBOARD engage and LAND mode helper."""

    def __init__(self, requester: RosbridgeRequester, relay: PoseRelay) -> None:
        self.requester = requester
        self.relay = relay

    def engage_offboard(self, *, arm: bool = True, prestream_seconds: float = 1.0) -> dict[str, Any]:
        required_publishes = max(1, int(self.relay.rate_hz * prestream_seconds))
        deadline = time.monotonic() + max(2.0, prestream_seconds + 2.0)
        while self.relay.publish_count < required_publishes and time.monotonic() < deadline:
            time.sleep(0.05)

        if self.relay.publish_count < required_publishes:
            return {
                "error": "setpoint_relay did not accumulate enough prestream before OFFBOARD",
                "required_publishes": required_publishes,
                "observed_publishes": self.relay.publish_count,
            }

        mode_result = self.requester.call_service(
            SET_MODE_SERVICE,
            SET_MODE_SERVICE_TYPE,
            {"base_mode": 0, "custom_mode": OFFBOARD_MODE},
            timeout=5.0,
        )
        arming_result = None
        if arm:
            arming_result = self.requester.call_service(
                ARMING_SERVICE,
                ARMING_SERVICE_TYPE,
                {"value": True},
                timeout=5.0,
            )
        return {
            "action": "engage_offboard",
            "prestream_publishes": self.relay.publish_count,
            "mode_result": mode_result,
            "arming_result": arming_result,
        }

    def land(self) -> dict[str, Any]:
        return {
            "action": "land",
            "mode_result": self.requester.call_service(
                SET_MODE_SERVICE,
                SET_MODE_SERVICE_TYPE,
                {"base_mode": 0, "custom_mode": LAND_MODE},
                timeout=5.0,
            ),
        }


class AbortWatchdog:
    """Runner-controlled LAND fallback for timeout or abort."""

    def __init__(
        self,
        mode_guard: ModeGuard,
        *,
        heartbeat_file: Path | None,
        timeout_s: float,
        enabled: bool,
    ) -> None:
        self.mode_guard = mode_guard
        self.heartbeat_file = heartbeat_file
        self.timeout_s = timeout_s
        self.enabled = enabled and heartbeat_file is not None
        self.triggered = False
        self.trigger_reason: str | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled or self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        assert self.heartbeat_file is not None
        while not self._stop.is_set() and not self.triggered:
            if not self.heartbeat_file.exists():
                time.sleep(0.25)
                continue
            payload = self.heartbeat_file.read_text(encoding="utf-8").strip()
            if payload == "abort":
                self.trigger_reason = "abort_flag"
                self.mode_guard.land()
                self.triggered = True
                return
            age = time.time() - self.heartbeat_file.stat().st_mtime
            if age > self.timeout_s:
                self.trigger_reason = "stale_heartbeat"
                self.mode_guard.land()
                self.triggered = True
                return
            time.sleep(0.25)

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
