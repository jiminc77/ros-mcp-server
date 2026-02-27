import json
import time
from dataclasses import dataclass
from threading import Event


def status_detail(status_code: str, status_message: str) -> str:
    return f"{status_code}: {status_message}"


@dataclass(frozen=True)
class StatusEnvelope:
    status: str
    status_code: str
    status_message: str
    source: str
    generation: int = 0
    goal_id: str = ""

    def to_json(self) -> str:
        payload = {
            "status": self.status,
            "status_code": self.status_code,
            "status_message": self.status_message,
            "status_detail": status_detail(self.status_code, self.status_message),
            "source": self.source,
            "generation": int(self.generation),
        }
        if self.goal_id:
            payload["goal_id"] = self.goal_id
        return json.dumps(payload, separators=(",", ":"))


class CancelToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def canceled(self) -> bool:
        return self._event.is_set()

    def sleep(self, seconds: float, poll_sec: float = 0.02) -> bool:
        if self.canceled:
            return False
        deadline = time.monotonic() + max(0.0, float(seconds))
        while not self.canceled:
            remain = deadline - time.monotonic()
            if remain <= 0.0:
                return True
            self._event.wait(timeout=min(max(1e-3, poll_sec), remain))
        return False


def extract_goal_id(goal_handle) -> str:
    goal_id = getattr(goal_handle, "goal_id", None)
    raw_uuid = getattr(goal_id, "uuid", None)
    if raw_uuid is not None:
        try:
            return bytes(int(v) & 0xFF for v in raw_uuid).hex()
        except Exception:
            pass
    return f"goal_{id(goal_handle):x}"


def log_phase(node, phase: str, *, goal_id: str = "", level: str = "info", detail: str = "") -> None:
    tag = f"[{node.get_name()}][{phase}]"
    if goal_id:
        tag += f"[{goal_id}]"
    message = f"{tag} {detail}".strip()
    logger = node.get_logger()
    log_fn = getattr(logger, level, logger.info)
    log_fn(message)
