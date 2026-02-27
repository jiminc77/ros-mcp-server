from drone_perception.runtime import status_detail


def build_status_payload(
    *,
    query: str,
    generation: int,
    status: str,
    status_code: str,
    status_message: str,
    source: str,
    extra: dict | None = None,
) -> dict:
    payload = {
        "query": query,
        "generation": int(generation),
        "status": status,
        "status_code": status_code,
        "status_message": status_message,
        "status_detail": status_detail(status_code, status_message),
        "source": source,
    }
    if extra:
        payload.update(extra)
    return payload


def initial_idle_payload(*, source: str) -> dict:
    return build_status_payload(
        query="",
        generation=0,
        status="idle",
        status_code="IDLE",
        status_message="No active query",
        source=source,
    )
