import unittest

from drone_perception.config import PerceptionConfig
from drone_perception.gemini_client import GeminiClient


def _cfg() -> PerceptionConfig:
    return PerceptionConfig(
        rotate_180=True,
        max_depth_history_size=30,
        max_sync_gap_sec=0.1,
        min_depth_m=0.4,
        max_depth_m=8.0,
        default_depth_roi_inset_ratio=0.1,
        default_depth_near_percentile=15.0,
        default_depth_near_margin_m=0.1,
        map_frame="map",
        camera_frame="",
        gemini_model="gemini-3-flash-preview",
        gemini_api_key_env="GEMINI_API_KEY",
        default_gemini_temperature=0.0,
        timeout_request_sec=30.0,
        max_request_retries=2,
        timeout_retry_backoff_sec=1.0,
        default_jpeg_quality=80,
        default_min_confidence=0.7,
        status_heartbeat_sec=1.0,
        debug_trace=False,
    )


class GeminiParseTests(unittest.TestCase):
    def test_parse_response_json_code_fence(self):
        client = GeminiClient(_cfg(), lambda _msg: None)
        raw = '{"candidates":[{"content":{"parts":[{"text":"```json\\n{\\"found\\":true,\\"label\\":\\"cup\\",\\"confidence\\":0.9,\\"bbox\\":{\\"x_min\\":100,\\"y_min\\":100,\\"x_max\\":200,\\"y_max\\":200},\\"caption\\":\\"white cup\\"}\\n```"}]}}]}'
        parsed = client._parse_response_json(raw)
        self.assertIsInstance(parsed, dict)
        self.assertTrue(parsed["found"])
        self.assertEqual(parsed["label"], "cup")


if __name__ == "__main__":
    unittest.main()
