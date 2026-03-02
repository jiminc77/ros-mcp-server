import time
from threading import Event


def status_detail(status_code: str, status_message: str) -> str:
    return f"{status_code}: {status_message}"


class CancelToken:
    def __init__(self) -> None:
        self._event = Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def canceled(self) -> bool:
        return self._event.is_set()

    def sleep(self, seconds: float, poll_sec: float = 0.05) -> bool:
        if self.canceled:
            return False
        deadline = time.monotonic() + max(0.0, float(seconds))
        while not self.canceled:
            remain = deadline - time.monotonic()
            if remain <= 0.0:
                return True
            self._event.wait(timeout=min(max(1e-3, poll_sec), remain))
        return False


def log_phase(
    node,
    phase: str,
    *,
    generation: int | None = None,
    goal_id: str = "",
    level: str = "info",
    detail: str = "",
) -> None:
    tag = f"[{node.get_name()}][{phase}]"
    if generation is not None:
        tag += f"[gen={int(generation)}]"
    if goal_id:
        tag += f"[{goal_id}]"
    message = f"{tag} {detail}".strip()
    logger = node.get_logger()
    log_fn = getattr(logger, level, logger.info)
    log_fn(message)
