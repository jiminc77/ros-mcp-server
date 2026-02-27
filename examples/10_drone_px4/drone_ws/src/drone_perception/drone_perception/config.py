from dataclasses import dataclass


@dataclass(frozen=True)
class PerceptionConfig:
    rotate_180: bool
    max_depth_history_size: int
    max_sync_gap_sec: float
    min_depth_m: float
    max_depth_m: float
    default_depth_roi_inset_ratio: float
    default_depth_near_percentile: float
    default_depth_near_margin_m: float
    map_frame: str
    camera_frame: str
    gemini_model: str
    gemini_api_key_env: str
    default_gemini_temperature: float
    timeout_request_sec: float
    max_request_retries: int
    timeout_retry_backoff_sec: float
    default_jpeg_quality: int
    default_min_confidence: float
    status_heartbeat_sec: float
    debug_trace: bool


def _param(node, name: str, default, legacy_name: str | None = None):
    if not node.has_parameter(name):
        node.declare_parameter(name, default)
    value = node.get_parameter(name).value
    if legacy_name is None:
        return value

    if not node.has_parameter(legacy_name):
        node.declare_parameter(legacy_name, default)
    legacy_value = node.get_parameter(legacy_name).value
    if value == default and legacy_value != default:
        return legacy_value
    return value


def load_perception_config(node) -> PerceptionConfig:
    return PerceptionConfig(
        rotate_180=bool(_param(node, "rotate_180", True)),
        max_depth_history_size=max(
            1, int(_param(node, "max_depth_history_size", 30, "depth_history_size"))
        ),
        max_sync_gap_sec=float(_param(node, "max_sync_gap_sec", 0.10)),
        min_depth_m=float(_param(node, "min_depth_m", 0.4)),
        max_depth_m=float(_param(node, "max_depth_m", 8.0)),
        default_depth_roi_inset_ratio=float(
            _param(node, "default_depth_roi_inset_ratio", 0.10, "depth_roi_inset_ratio")
        ),
        default_depth_near_percentile=float(
            _param(node, "default_depth_near_percentile", 15.0, "depth_near_percentile")
        ),
        default_depth_near_margin_m=float(
            _param(node, "default_depth_near_margin_m", 0.10, "depth_near_margin_m")
        ),
        map_frame=str(_param(node, "map_frame", "map")),
        camera_frame=str(_param(node, "camera_frame", "")).strip(),
        gemini_model=str(_param(node, "gemini_model", "gemini-3-flash-preview")),
        gemini_api_key_env=str(_param(node, "gemini_api_key_env", "GEMINI_API_KEY")),
        default_gemini_temperature=float(
            _param(node, "default_gemini_temperature", 0.0, "gemini_temperature")
        ),
        timeout_request_sec=float(_param(node, "timeout_request_sec", 30.0, "request_timeout_sec")),
        max_request_retries=max(1, int(_param(node, "max_request_retries", 2, "request_max_retries"))),
        timeout_retry_backoff_sec=max(
            0.0, float(_param(node, "timeout_retry_backoff_sec", 1.0, "request_retry_backoff_sec"))
        ),
        default_jpeg_quality=max(
            40, min(int(_param(node, "default_jpeg_quality", 80, "jpeg_quality")), 95)
        ),
        default_min_confidence=float(_param(node, "default_min_confidence", 0.7, "min_confidence")),
        status_heartbeat_sec=max(0.2, float(_param(node, "status_heartbeat_sec", 1.0))),
        debug_trace=bool(_param(node, "debug_trace", True)),
    )
