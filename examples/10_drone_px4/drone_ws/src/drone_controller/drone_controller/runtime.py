import asyncio
import json
from dataclasses import dataclass


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
        self._event = asyncio.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def canceled(self) -> bool:
        return self._event.is_set()

    async def sleep(self, seconds: float) -> bool:
        if self.canceled:
            return False
        timeout = max(0.0, float(seconds))
        if timeout == 0.0:
            await asyncio.sleep(0)
            return not self.canceled
        try:
            await asyncio.wait_for(self._event.wait(), timeout=timeout)
            return False
        except asyncio.TimeoutError:
            return not self.canceled


def extract_goal_id(goal_handle) -> str:
    goal_id = getattr(goal_handle, "goal_id", None)
    raw_uuid = getattr(goal_id, "uuid", None)
    if raw_uuid:
        try:
            return bytes(raw_uuid).hex()
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
