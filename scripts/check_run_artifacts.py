#!/usr/bin/env python3
"""Validate experiment artifacts for one run/attempt."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


REQUIRED_FILES = (
    ("rosbag", "metadata.yaml"),
    ("gemini", "session_report.json"),
    ("gemini", "session_report.txt"),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate experiment run artifacts")
    parser.add_argument("--run-dir", help="Run directory (contains status.json)", default=None)
    parser.add_argument(
        "--attempt-dir",
        help="Attempt directory (contains rosbag/ and gemini/)",
        default=None,
    )
    return parser.parse_args()


def read_status(run_dir: Path) -> dict:
    status_path = run_dir / "status.json"
    if not status_path.exists():
        return {}
    try:
        return json.loads(status_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def resolve_attempt_dir(run_dir: Path | None, attempt_dir: Path | None) -> Path | None:
    if attempt_dir is not None:
        return attempt_dir.resolve()
    if run_dir is None:
        return None
    status = read_status(run_dir)
    raw = status.get("attempt_dir")
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    if not path.is_absolute():
        path = (run_dir / path).resolve()
    return path


def validate_attempt_dir(attempt_dir: Path) -> tuple[bool, list[str]]:
    errors: list[str] = []
    if not attempt_dir.exists():
        errors.append(f"attempt_dir_missing: {attempt_dir}")
        return False, errors

    for parent, filename in REQUIRED_FILES:
        path = attempt_dir / parent / filename
        if not path.exists():
            errors.append(f"missing: {path}")
            continue
        if path.is_file() and path.stat().st_size == 0:
            errors.append(f"empty: {path}")

    return len(errors) == 0, errors


def main() -> int:
    args = parse_args()
    run_dir = Path(args.run_dir).resolve() if args.run_dir else None
    attempt_dir = Path(args.attempt_dir).resolve() if args.attempt_dir else None

    resolved = resolve_attempt_dir(run_dir, attempt_dir)
    if resolved is None:
        payload = {
            "ok": False,
            "errors": ["attempt directory is not resolvable from arguments"],
        }
        print(json.dumps(payload, ensure_ascii=True, indent=2))
        return 1

    ok, errors = validate_attempt_dir(resolved)
    payload = {"ok": ok, "attempt_dir": str(resolved), "errors": errors}
    print(json.dumps(payload, ensure_ascii=True, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
