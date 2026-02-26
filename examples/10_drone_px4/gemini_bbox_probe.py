#!/usr/bin/env python3
"""
Standalone Gemini bbox probe.

Runs repeated object detection on one fixed image and reports bbox stability.
This helps isolate model bbox behavior without ROS/depth/TF effects.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from urllib import error as url_error
from urllib import request as url_request

try:
    import cv2  # type: ignore
except Exception:
    cv2 = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repeated Gemini bbox test on a single image.")
    parser.add_argument("--image", required=True, help="Path to input image (jpg/png).")
    parser.add_argument("--query", required=True, help="Target object query, e.g. 'white cup'.")
    parser.add_argument("--model", default="gemini-3.1-pro-preview", help="Gemini model name.")
    parser.add_argument("--runs", type=int, default=20, help="Number of repeated requests.")
    parser.add_argument("--temperature", type=float, default=0.0, help="Gemini temperature.")
    parser.add_argument("--timeout-sec", type=float, default=30.0, help="HTTP timeout seconds.")
    parser.add_argument(
        "--api-key-env", default="GEMINI_API_KEY", help="Env var name that stores Gemini API key."
    )
    parser.add_argument(
        "--sleep-sec",
        type=float,
        default=0.0,
        help="Sleep time between requests for rate control.",
    )
    parser.add_argument(
        "--mode",
        choices=("baseline", "full-object"),
        default="full-object",
        help="Prompt style. Use full-object to force whole object extent.",
    )
    parser.add_argument(
        "--out-dir",
        default="./bbox_probe_out",
        help="Directory for JSONL logs and overlay outputs.",
    )
    return parser.parse_args()


def load_image(image_path: Path) -> tuple[bytes, int, int]:
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    image_bytes = image_path.read_bytes()
    if cv2 is None:
        raise RuntimeError("OpenCV (cv2) is required to read image width/height.")

    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"Failed to decode image: {image_path}")
    h, w = img.shape[:2]
    return image_bytes, w, h


def build_prompt(query: str, width: int, height: int, mode: str) -> str:
    common = (
        "You are a robotics vision grounding module. "
        "Detect one object for the query and return strict JSON only. "
        f"Query: {query}. "
        f"Image width={width}, height={height}. "
        "Coordinates must be integer pixel coordinates in this exact image "
        "(top-left origin, x right, y down). "
        "Do not return normalized coordinates."
    )
    if mode == "baseline":
        return common + " If not found, set found=false and bbox to zeros."
    return (
        common
        + " Bounding box must tightly cover the full visible object extent "
        "from leftmost/topmost/rightmost/bottommost object pixels. "
        "Do not box only a part (edge, corner, handle, shadow, highlight, or texture patch). "
        "If multiple objects match, choose the largest visible instance. "
        "If not found, set found=false and bbox to zeros."
    )


def build_schema() -> dict:
    return {
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


def parse_response_json(raw: str):
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


def normalize_bbox(bbox_obj, width: int, height: int):
    if not isinstance(bbox_obj, dict):
        return None, "bbox is missing or not object"

    keys = ("x_min", "y_min", "x_max", "y_max")
    if not all(k in bbox_obj for k in keys):
        return None, "bbox keys missing"

    try:
        x_min = float(bbox_obj["x_min"])
        y_min = float(bbox_obj["y_min"])
        x_max = float(bbox_obj["x_max"])
        y_max = float(bbox_obj["y_max"])
    except Exception:
        return None, "bbox values are not numeric"

    # Guard: some responses still come normalized.
    if all(0.0 <= v <= 1.0 for v in (x_min, y_min, x_max, y_max)):
        x_min *= max(1, width - 1)
        x_max *= max(1, width - 1)
        y_min *= max(1, height - 1)
        y_max *= max(1, height - 1)

    x0 = int(round(min(x_min, x_max)))
    y0 = int(round(min(y_min, y_max)))
    x1 = int(round(max(x_min, x_max)))
    y1 = int(round(max(y_min, y_max)))

    x0 = max(0, min(x0, width - 1))
    x1 = max(0, min(x1, width - 1))
    y0 = max(0, min(y0, height - 1))
    y1 = max(0, min(y1, height - 1))

    if x0 >= x1 or y0 >= y1:
        return None, f"degenerate bbox ({x0},{y0})-({x1},{y1})"

    return {"x_min": x0, "y_min": y0, "x_max": x1, "y_max": y1}, None


def call_gemini(
    *,
    api_key: str,
    model: str,
    prompt: str,
    image_b64: str,
    temperature: float,
    timeout_sec: float,
) -> tuple[dict | None, str | None, str]:
    endpoint = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        f"?key={api_key}"
    )
    body = {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": prompt},
                    {
                        "inline_data": {
                            "mime_type": "image/jpeg",
                            "data": image_b64,
                        }
                    },
                ],
            }
        ],
        "generationConfig": {
            "temperature": float(temperature),
            "responseMimeType": "application/json",
            "responseSchema": build_schema(),
        },
    }

    req = url_request.Request(
        endpoint,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    raw = ""
    try:
        with url_request.urlopen(req, timeout=timeout_sec) as resp:
            raw = resp.read().decode("utf-8")
    except url_error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="ignore")
        return None, f"HTTP {exc.code}: {detail}", raw
    except Exception as exc:
        return None, f"Request failed: {exc}", raw

    parsed = parse_response_json(raw)
    if not isinstance(parsed, dict):
        return None, "output is not a valid JSON object", raw

    return parsed, None, raw


def draw_outputs(image_path: Path, out_dir: Path, valid_results: list[dict]) -> None:
    if cv2 is None:
        return
    img = cv2.imread(str(image_path), cv2.IMREAD_COLOR)
    if img is None:
        return

    overlay = img.copy()
    for idx, r in enumerate(valid_results, start=1):
        b = r["bbox"]
        color = (0, 255, 255)
        cv2.rectangle(overlay, (b["x_min"], b["y_min"]), (b["x_max"], b["y_max"]), color, 2)
        cx = int((b["x_min"] + b["x_max"]) / 2)
        cy = int((b["y_min"] + b["y_max"]) / 2)
        cv2.circle(overlay, (cx, cy), 3, (0, 0, 255), -1)
        cv2.putText(
            overlay,
            f"{idx}",
            (b["x_min"], max(14, b["y_min"] - 6)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            (50, 255, 50),
            1,
            cv2.LINE_AA,
        )
    cv2.imwrite(str(out_dir / "overlay_all_boxes.jpg"), overlay)

    xs0 = [r["bbox"]["x_min"] for r in valid_results]
    ys0 = [r["bbox"]["y_min"] for r in valid_results]
    xs1 = [r["bbox"]["x_max"] for r in valid_results]
    ys1 = [r["bbox"]["y_max"] for r in valid_results]
    median_box = {
        "x_min": int(round(statistics.median(xs0))),
        "y_min": int(round(statistics.median(ys0))),
        "x_max": int(round(statistics.median(xs1))),
        "y_max": int(round(statistics.median(ys1))),
    }
    overlay_med = img.copy()
    cv2.rectangle(
        overlay_med,
        (median_box["x_min"], median_box["y_min"]),
        (median_box["x_max"], median_box["y_max"]),
        (255, 255, 0),
        3,
    )
    cv2.imwrite(str(out_dir / "overlay_median_box.jpg"), overlay_med)


def summarize(width: int, height: int, valid_results: list[dict], total_runs: int) -> dict:
    summary: dict = {
        "total_runs": total_runs,
        "valid_runs": len(valid_results),
        "invalid_runs": total_runs - len(valid_results),
        "image_width": width,
        "image_height": height,
    }
    if not valid_results:
        return summary

    centers_x = []
    centers_y = []
    area_ratios = []
    confidences = []
    for r in valid_results:
        b = r["bbox"]
        cx = (b["x_min"] + b["x_max"]) / 2.0
        cy = (b["y_min"] + b["y_max"]) / 2.0
        area = float((b["x_max"] - b["x_min"]) * (b["y_max"] - b["y_min"]))
        centers_x.append(cx)
        centers_y.append(cy)
        area_ratios.append(area / float(width * height))
        confidences.append(float(r.get("confidence", 0.0)))

    summary.update(
        {
            "center_x_mean_px": statistics.mean(centers_x),
            "center_y_mean_px": statistics.mean(centers_y),
            "center_x_std_px": statistics.pstdev(centers_x),
            "center_y_std_px": statistics.pstdev(centers_y),
            "area_ratio_mean": statistics.mean(area_ratios),
            "area_ratio_std": statistics.pstdev(area_ratios),
            "confidence_mean": statistics.mean(confidences),
            "confidence_std": statistics.pstdev(confidences),
        }
    )

    cx_n = summary["center_x_mean_px"] / float(width)
    cy_n = summary["center_y_mean_px"] / float(height)
    left_bottom_bias = (
        cx_n < 0.45
        and cy_n > 0.55
        and summary["center_x_std_px"] < 25.0
        and summary["center_y_std_px"] < 25.0
    )
    summary["left_bottom_image_bias_suspected"] = bool(left_bottom_bias)
    return summary


def main() -> int:
    args = parse_args()

    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        print(f"ERROR: {args.api_key_env} is not set.", file=sys.stderr)
        return 2

    image_path = Path(args.image).expanduser().resolve()
    out_dir = Path(args.out_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    image_bytes, width, height = load_image(image_path)
    image_b64 = base64.b64encode(image_bytes).decode("ascii")
    prompt = build_prompt(args.query, width, height, args.mode)

    print(f"Image: {image_path}")
    print(f"Resolution: {width}x{height}")
    print(f"Query: {args.query}")
    print(f"Model: {args.model}")
    print(f"Mode: {args.mode}")
    print(f"Runs: {args.runs}")
    print("-" * 60)

    jsonl_path = out_dir / "results.jsonl"
    valid_results: list[dict] = []
    invalid_records: list[dict] = []

    with jsonl_path.open("w", encoding="utf-8") as fp:
        for i in range(1, args.runs + 1):
            t0 = time.monotonic()
            parsed, error_msg, raw = call_gemini(
                api_key=api_key,
                model=args.model,
                prompt=prompt,
                image_b64=image_b64,
                temperature=args.temperature,
                timeout_sec=args.timeout_sec,
            )
            elapsed = time.monotonic() - t0

            record = {"run": i, "elapsed_sec": elapsed}

            if error_msg is not None:
                record["ok"] = False
                record["error"] = error_msg
                fp.write(json.dumps(record, ensure_ascii=True) + "\n")
                invalid_records.append(record)
                print(f"[{i:02d}] ERROR {error_msg}")
            else:
                assert parsed is not None
                found = bool(parsed.get("found", False))
                bbox, bbox_err = normalize_bbox(parsed.get("bbox"), width, height)
                confidence = parsed.get("confidence", 0.0)
                label = str(parsed.get("label", args.query))
                caption = str(parsed.get("caption", ""))

                if not found:
                    record["ok"] = False
                    record["error"] = "found=false"
                    record["parsed"] = parsed
                    fp.write(json.dumps(record, ensure_ascii=True) + "\n")
                    invalid_records.append(record)
                    print(f"[{i:02d}] NOT_FOUND")
                elif bbox is None:
                    record["ok"] = False
                    record["error"] = bbox_err
                    record["parsed"] = parsed
                    fp.write(json.dumps(record, ensure_ascii=True) + "\n")
                    invalid_records.append(record)
                    print(f"[{i:02d}] INVALID_BBOX {bbox_err}")
                else:
                    out = {
                        "run": i,
                        "ok": True,
                        "elapsed_sec": elapsed,
                        "label": label,
                        "confidence": float(confidence),
                        "bbox": bbox,
                        "caption": caption,
                    }
                    fp.write(json.dumps(out, ensure_ascii=True) + "\n")
                    valid_results.append(out)
                    b = bbox
                    print(
                        f"[{i:02d}] OK conf={float(confidence):.3f} "
                        f"bbox=({b['x_min']},{b['y_min']})-({b['x_max']},{b['y_max']})"
                    )

            if args.sleep_sec > 0.0 and i < args.runs:
                time.sleep(args.sleep_sec)

    summary = summarize(width, height, valid_results, args.runs)
    summary["query"] = args.query
    summary["model"] = args.model
    summary["mode"] = args.mode
    summary["image"] = str(image_path)
    summary["output_dir"] = str(out_dir)
    summary["invalid_examples"] = invalid_records[:3]

    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    if valid_results:
        draw_outputs(image_path, out_dir, valid_results)

    print("-" * 60)
    print(json.dumps(summary, indent=2))
    print("-" * 60)
    print(f"Saved: {jsonl_path}")
    print(f"Saved: {out_dir / 'summary.json'}")
    if valid_results and cv2 is not None:
        print(f"Saved: {out_dir / 'overlay_all_boxes.jpg'}")
        print(f"Saved: {out_dir / 'overlay_median_box.jpg'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
