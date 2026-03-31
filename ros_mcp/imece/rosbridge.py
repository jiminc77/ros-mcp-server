"""Minimal rosbridge clients for IMECE monitoring and helpers."""

from __future__ import annotations

import json
import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import websocket


class RosbridgeRequester:
    """Synchronous rosbridge helper for service calls and simple publishes."""

    def __init__(self, host: str, port: int, timeout: float = 2.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._ws = None
        self._lock = threading.RLock()
        self._advertised: set[str] = set()

    def _url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    def connect(self) -> None:
        with self._lock:
            if self._ws is None or not self._ws.connected:
                self._ws = websocket.create_connection(self._url(), timeout=self.timeout)
                self._ws.settimeout(self.timeout)

    def close(self) -> None:
        with self._lock:
            if self._ws is not None:
                try:
                    self._ws.close()
                finally:
                    self._ws = None
                    self._advertised.clear()

    def _send(self, payload: dict[str, Any]) -> None:
        self.connect()
        assert self._ws is not None
        self._ws.send(json.dumps(payload))

    def call_service(
        self,
        service: str,
        service_type: str,
        args: dict[str, Any],
        timeout: float | None = None,
    ) -> dict[str, Any]:
        request_id = f"imece_{uuid.uuid4().hex}"
        deadline = time.monotonic() + (timeout or self.timeout)
        with self._lock:
            self._send(
                {
                    "op": "call_service",
                    "service": service,
                    "type": service_type,
                    "args": args,
                    "id": request_id,
                }
            )
            while time.monotonic() < deadline:
                assert self._ws is not None
                self._ws.settimeout(max(0.1, deadline - time.monotonic()))
                try:
                    raw = self._ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                message = json.loads(raw)
                if isinstance(message, dict) and message.get("id") == request_id:
                    return message
        return {"error": "timeout waiting for rosbridge service response"}

    def advertise(self, topic: str, msg_type: str) -> None:
        with self._lock:
            if topic in self._advertised:
                return
            self._send({"op": "advertise", "topic": topic, "type": msg_type})
            self._advertised.add(topic)

    def publish(self, topic: str, msg_type: str, msg: dict[str, Any]) -> None:
        with self._lock:
            self.advertise(topic, msg_type)
            self._send({"op": "publish", "topic": topic, "msg": msg})


class RosbridgeSubscriber:
    """Background subscriber for a small set of topics."""

    def __init__(self, host: str, port: int, timeout: float = 1.0) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self._ws = None
        self._callbacks: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self.status_errors: list[str] = []

    def _url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._ws = websocket.create_connection(self._url(), timeout=self.timeout)
            self._ws.settimeout(self.timeout)
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, daemon=True)
            self._thread.start()

    def subscribe(
        self,
        topic: str,
        msg_type: str,
        callback: Callable[[dict[str, Any]], None],
        *,
        queue_length: int = 1,
        throttle_rate_ms: int = 0,
    ) -> None:
        self.start()
        with self._lock:
            self._callbacks[topic] = callback
            assert self._ws is not None
            self._ws.send(
                json.dumps(
                    {
                        "op": "subscribe",
                        "topic": topic,
                        "type": msg_type,
                        "queue_length": queue_length,
                        "throttle_rate": throttle_rate_ms,
                    }
                )
            )

    def _run(self) -> None:
        assert self._ws is not None
        while not self._stop.is_set():
            try:
                raw = self._ws.recv()
            except websocket.WebSocketTimeoutException:
                continue
            except Exception as exc:  # pragma: no cover - connection failures are environment-specific
                self.status_errors.append(str(exc))
                break

            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue

            if not isinstance(message, dict):
                continue

            if message.get("op") == "status" and message.get("level") == "error":
                msg = message.get("msg")
                if isinstance(msg, str):
                    self.status_errors.append(msg)
                continue

            if message.get("op") != "publish":
                continue

            topic = message.get("topic")
            msg = message.get("msg")
            if not isinstance(topic, str) or not isinstance(msg, dict):
                continue

            callback = self._callbacks.get(topic)
            if callback is not None:
                callback(msg)

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            if self._ws is not None:
                try:
                    for topic in list(self._callbacks):
                        self._ws.send(json.dumps({"op": "unsubscribe", "topic": topic}))
                    self._ws.close()
                finally:
                    self._ws = None
                    self._callbacks.clear()
        if self._thread is not None:
            self._thread.join(timeout=2)
