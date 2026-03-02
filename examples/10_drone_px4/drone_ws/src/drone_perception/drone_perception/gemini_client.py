import base64
import json
import re
import socket
from urllib import error as url_error
from urllib import request as url_request

from drone_perception.config import PerceptionConfig
from drone_perception.runtime import CancelToken


class GeminiClient:
    def __init__(self, config: PerceptionConfig, trace):
        self._config = config
        self._trace = trace

    async def detect_bbox_and_caption(
        self,
        *,
        api_key: str,
        query: str,
        image,
        cancel_token: CancelToken,
    ) -> dict:
        if cancel_token.canceled:
            return {"ok": False, "error": "Canceled"}

        import cv2

        ok, jpg = cv2.imencode(
            ".jpg",
            image,
            [int(cv2.IMWRITE_JPEG_QUALITY), int(self._config.default_jpeg_quality)],
        )
        if not ok:
            return {"ok": False, "error": "Failed to encode image"}

        image_b64 = base64.b64encode(jpg.tobytes()).decode("ascii")
        h, w = image.shape[:2]

        prompt = (
            "You are a vision grounding module. "
            "Detect one object for the query and return strict JSON. "
            f"Query: {query}. "
            f"Image width={w}, height={h}. "
            "Coordinates must be integer coordinates in range [0,1000] for this image "
            "(top-left origin, x to right, y to bottom; 0 means min edge, 1000 means max edge). "
            "If not found, set found=false and bbox to zeros."
        )

        schema = {
            "type": "OBJECT",
            "properties": {
                "found": {"type": "BOOLEAN"},
                "label": {"type": "STRING"},
                "confidence": {"type": "NUMBER"},
                "bbox": {
                    "type": "OBJECT",
                    "properties": {
                        "x_min": {"type": "INTEGER"},
                        "y_min": {"type": "INTEGER"},
                        "x_max": {"type": "INTEGER"},
                        "y_max": {"type": "INTEGER"},
                    },
                    "required": ["x_min", "y_min", "x_max", "y_max"],
                },
                "caption": {"type": "STRING"},
            },
            "required": ["found", "label", "confidence", "bbox", "caption"],
        }

        body = {
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": "image/jpeg", "data": image_b64}},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": self._config.default_gemini_temperature,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }

        endpoint = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self._config.gemini_model}"
            f":generateContent?key={api_key}"
        )
        req = url_request.Request(
            endpoint,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        raw = None
        for attempt in range(1, self._config.max_request_retries + 1):
            if cancel_token.canceled:
                return {"ok": False, "error": "Canceled"}
            try:
                raw = self._request_once(req, self._config.timeout_request_sec)
                self._trace(
                    "gemini request success"
                    f" attempt={attempt}/{self._config.max_request_retries}"
                    f" response_chars={len(raw)}"
                )
                break
            except url_error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                return {"ok": False, "error": f"Gemini HTTP {exc.code}: {detail}"}
            except Exception as exc:
                timeout_error = self._is_timeout_error(exc)
                self._trace(
                    "gemini request exception"
                    f" attempt={attempt}/{self._config.max_request_retries}"
                    f" timeout={timeout_error} type={type(exc).__name__} error={exc}"
                )
                if timeout_error and attempt < self._config.max_request_retries:
                    if not cancel_token.sleep(self._config.timeout_retry_backoff_sec):
                        return {"ok": False, "error": "Canceled"}
                    continue
                if timeout_error:
                    return {
                        "ok": False,
                        "error": (
                            f"Gemini request timed out after {attempt} attempt(s) "
                            f"(timeout={self._config.timeout_request_sec:.1f}s)"
                        ),
                    }
                return {"ok": False, "error": f"Gemini request failed: {exc}"}

        if raw is None:
            return {"ok": False, "error": "Gemini request failed: empty response"}

        parsed = self._parse_response_json(raw)
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "Gemini output is not a JSON object"}
        if not bool(parsed.get("found", False)):
            return {"ok": False, "error": "Target object not found"}

        bbox_obj = parsed.get("bbox")
        if not isinstance(bbox_obj, dict):
            return {"ok": False, "error": "bbox is missing"}

        try:
            x_min_raw = float(bbox_obj["x_min"])
            y_min_raw = float(bbox_obj["y_min"])
            x_max_raw = float(bbox_obj["x_max"])
            y_max_raw = float(bbox_obj["y_max"])
            confidence = float(parsed.get("confidence", 0.0))
        except Exception:
            return {"ok": False, "error": "Invalid bbox/confidence fields"}

        x_min = int(round((x_min_raw / 1000.0) * max(1, w - 1)))
        y_min = int(round((y_min_raw / 1000.0) * max(1, h - 1)))
        x_max = int(round((x_max_raw / 1000.0) * max(1, w - 1)))
        y_max = int(round((y_max_raw / 1000.0) * max(1, h - 1)))

        if x_min > x_max:
            x_min, x_max = x_max, x_min
        if y_min > y_max:
            y_min, y_max = y_max, y_min

        x_min = max(0, min(x_min, w - 1))
        x_max = max(0, min(x_max, w - 1))
        y_min = max(0, min(y_min, h - 1))
        y_max = max(0, min(y_max, h - 1))
        if x_min >= x_max or y_min >= y_max:
            return {"ok": False, "error": "Degenerate bbox"}

        return {
            "ok": True,
            "label": str(parsed.get("label", query)),
            "confidence": confidence,
            "bbox": {
                "x_min": x_min,
                "y_min": y_min,
                "x_max": x_max,
                "y_max": y_max,
            },
            "caption": str(parsed.get("caption", "")),
        }

    @staticmethod
    def _request_once(req, timeout_sec: float) -> str:
        with url_request.urlopen(req, timeout=timeout_sec) as resp:
            return resp.read().decode("utf-8")

    def _parse_response_json(self, raw: str):
        try:
            response_json = json.loads(raw)
        except Exception:
            return None

        candidates = response_json.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            return None

        parts = candidates[0].get("content", {}).get("parts", [])
        text_chunks = []
        for part in parts:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                text_chunks.append(part["text"])

        text = "\n".join(text_chunks).strip()
        if not text:
            return None

        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*", "", text)
            text = re.sub(r"\s*```$", "", text)

        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"\{.*\}", text, flags=re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(0))
            except Exception:
                return None

    @staticmethod
    def _is_timeout_error(exc: Exception) -> bool:
        if isinstance(exc, (TimeoutError, socket.timeout)):
            return True
        if isinstance(exc, url_error.URLError):
            reason = getattr(exc, "reason", None)
            if isinstance(reason, (TimeoutError, socket.timeout)):
                return True
            if reason is not None and "timed out" in str(reason).lower():
                return True
        return "timed out" in str(exc).lower()
