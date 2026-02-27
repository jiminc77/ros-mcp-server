import asyncio


def status_detail(status_code: str, status_message: str) -> str:
    return f"{status_code}: {status_message}"


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
