"""Non-semantic C2 helper implementations."""

from __future__ import annotations

import json
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
from .rosbridge import RosbridgeRequester, RosbridgeSubscriber


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
        target = self._coerce_mapping(target, field_name="target")
        if not isinstance(target, dict):
            raise ValueError("target must be a PoseStamped-like dictionary")

        header = self._coerce_mapping(target.get("header") or {}, field_name="target.header")
        pose = self._coerce_mapping(target.get("pose") or {}, field_name="target.pose")
        position = self._coerce_mapping(
            pose.get("position") or {},
            field_name="target.pose.position",
        )
        orientation = self._coerce_mapping(
            pose.get("orientation") or {},
            field_name="target.pose.orientation",
        )

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

    @staticmethod
    def _normalize_mapping_keys(mapping: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in mapping.items():
            normalized_key = str(key).strip().strip('"').strip("'")
            if isinstance(value, dict):
                normalized[normalized_key] = PoseRelay._normalize_mapping_keys(value)
            else:
                normalized[normalized_key] = value
        return normalized

    @staticmethod
    def _coerce_mapping(value: Any, *, field_name: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return PoseRelay._normalize_mapping_keys(dict(value))
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return {}
            try:
                decoded = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{field_name} must be a mapping or JSON object string") from exc
            if not isinstance(decoded, dict):
                raise ValueError(f"{field_name} must decode to a mapping")
            return PoseRelay._normalize_mapping_keys(dict(decoded))
        if value is None:
            return {}
        raise ValueError(f"{field_name} must be a mapping")

    def set_target(self, target: dict[str, Any]) -> dict[str, Any]:
        try:
            normalized = self._normalize_target(target)
        except ValueError as exc:
            self.last_error = str(exc)
            status = self.status()
            status["error"] = self.last_error
            return status
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

    @staticmethod
    def _service_values(response: dict[str, Any] | None) -> dict[str, Any]:
        if not isinstance(response, dict):
            return {}
        values = response.get("values")
        return values if isinstance(values, dict) else {}

    def _wait_for_mode(self, expected_mode: str, *, timeout_s: float = 3.0) -> bool:
        observed = {"mode": None}
        subscriber = RosbridgeSubscriber(self.requester.host, self.requester.port, timeout=1.0)

        def on_state(message: dict[str, Any]) -> None:
            observed["mode"] = message.get("mode")

        try:
            subscriber.subscribe("/mavros/state", "mavros_msgs/msg/State", on_state)
            deadline = time.monotonic() + timeout_s
            while time.monotonic() < deadline:
                if observed.get("mode") == expected_mode:
                    return True
                time.sleep(0.1)
        finally:
            subscriber.stop()
        return False

    def engage_offboard(self, *, arm: bool = True, prestream_seconds: float = 2.0) -> dict[str, Any]:
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
        mode_sent = bool(self._service_values(mode_result).get("mode_sent"))
        if not mode_sent:
            return {
                "action": "engage_offboard",
                "prestream_publishes": self.relay.publish_count,
                "mode_result": mode_result,
                "arming_result": None,
                "arming_attempts": 0,
                "error": "OFFBOARD mode change was not accepted",
            }
        if not self._wait_for_mode(OFFBOARD_MODE):
            return {
                "action": "engage_offboard",
                "prestream_publishes": self.relay.publish_count,
                "mode_result": mode_result,
                "arming_result": None,
                "arming_attempts": 0,
                "error": "Vehicle did not report OFFBOARD state before arming",
            }

        arming_result = None
        arming_attempts = 0
        if arm:
            for _ in range(2):
                arming_attempts += 1
                arming_result = self.requester.call_service(
                    ARMING_SERVICE,
                    ARMING_SERVICE_TYPE,
                    {"value": True},
                    timeout=5.0,
                )
                if bool(self._service_values(arming_result).get("success")):
                    break
                time.sleep(0.5)
        result = {
            "action": "engage_offboard",
            "prestream_publishes": self.relay.publish_count,
            "mode_result": mode_result,
            "arming_result": arming_result,
            "arming_attempts": arming_attempts,
        }
        if arm and not bool(self._service_values(arming_result).get("success")):
            result["error"] = "Vehicle did not arm after OFFBOARD engage"
        return result

    def land(self) -> dict[str, Any]:
        self.relay.stop()
        mode_result = self.requester.call_service(
            SET_MODE_SERVICE,
            SET_MODE_SERVICE_TYPE,
            {"base_mode": 0, "custom_mode": LAND_MODE},
            timeout=5.0,
        )

        landing_state: dict[str, Any] = {"armed": None, "z": None}
        subscriber = RosbridgeSubscriber(self.requester.host, self.requester.port, timeout=1.0)

        def on_state(message: dict[str, Any]) -> None:
            landing_state["armed"] = message.get("armed")

        def on_pose(message: dict[str, Any]) -> None:
            pose = message.get("pose", {})
            position = pose.get("position", {}) if isinstance(pose, dict) else {}
            try:
                landing_state["z"] = float(position.get("z"))
            except (TypeError, ValueError):
                return

        landed = False
        try:
            subscriber.subscribe("/mavros/state", "mavros_msgs/msg/State", on_state)
            subscriber.subscribe(
                "/mavros/local_position/pose",
                "geometry_msgs/msg/PoseStamped",
                on_pose,
            )

            deadline = time.monotonic() + 20.0
            while time.monotonic() < deadline:
                armed = landing_state.get("armed")
                altitude = landing_state.get("z")
                if armed is False and altitude is not None and altitude <= 0.2:
                    landed = True
                    break
                time.sleep(0.1)
        finally:
            subscriber.stop()

        result = {
            "action": "land",
            "mode_result": mode_result,
            "landing_complete": landed,
            "latest_armed": landing_state.get("armed"),
            "latest_z": landing_state.get("z"),
        }
        if not bool(self._service_values(mode_result).get("mode_sent")):
            result["error"] = "AUTO.LAND mode change was not accepted"
        elif not landed:
            result["error"] = "Vehicle did not confirm a safe landing before timeout"
        return result


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
