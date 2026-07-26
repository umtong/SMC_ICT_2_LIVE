#!/usr/bin/env python3
"""Persist exact health, registration, keyless, and keyed transcript responses."""

from __future__ import annotations

import json
import traceback
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

BASE = "https://api.youtubetotext.com"
HEADERS = {"User-Agent": "SMC-ICT-2-LIVE/1.0", "Accept": "application/json"}
VIDEO_ID = "F6wDs1HRTSo"
OUTPUT = Path("artifact/probe-result.json")


def decode(raw: bytes) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return {"raw_prefix": raw.decode("utf-8", "replace")[:3000]}


def safe_payload(payload: Any) -> Any:
    if isinstance(payload, dict) and "api_key" in payload:
        return {
            **{key: value for key, value in payload.items() if key != "api_key"},
            "api_key_present": bool(payload.get("api_key")),
        }
    return payload


def call(name: str, request: urllib.request.Request) -> tuple[dict[str, Any], str | None]:
    try:
        with urllib.request.urlopen(request, timeout=50) as response:
            raw = response.read()
            status = int(response.status)
            headers = dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        status = int(exc.code)
        headers = dict(exc.headers)
    except BaseException as exc:
        return {
            "name": name,
            "exception": f"{type(exc).__name__}: {exc}",
            "traceback": traceback.format_exc(),
        }, None
    payload = decode(raw)
    transcript = payload.get("transcript") if isinstance(payload, dict) else None
    key = payload.get("api_key") if isinstance(payload, dict) and isinstance(payload.get("api_key"), str) else None
    return {
        "name": name,
        "status_code": status,
        "content_type": headers.get("Content-Type") or headers.get("content-type"),
        "retry_after": headers.get("Retry-After") or headers.get("retry-after"),
        "segment_count": len(transcript) if isinstance(transcript, list) else 0,
        "payload": safe_payload(payload),
    }, key


def main() -> int:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    output: dict[str, Any] = {
        "schema_version": 2,
        "positive_control_video_id": VIDEO_ID,
        "positive_control_pass": False,
        "results": [],
    }
    try:
        health, _ = call("health", urllib.request.Request(f"{BASE}/health", headers=HEADERS))
        output["results"].append(health)

        registration, api_key = call(
            "free_register",
            urllib.request.Request(
                f"{BASE}/free/register",
                data=b"",
                method="POST",
                headers=HEADERS,
            ),
        )
        output["results"].append(registration)

        keyless, _ = call(
            "known_positive_keyless",
            urllib.request.Request(f"{BASE}/full_transcript/{VIDEO_ID}?meta=true", headers=HEADERS),
        )
        output["results"].append(keyless)

        if api_key:
            keyed, _ = call(
                "known_positive_registered_key",
                urllib.request.Request(
                    f"{BASE}/full_transcript/{VIDEO_ID}?meta=true",
                    headers={**HEADERS, "X-API-Key": api_key},
                ),
            )
        else:
            keyed = {"name": "known_positive_registered_key", "skipped": "registration returned no key"}
        output["results"].append(keyed)
        output["positive_control_pass"] = any(
            isinstance(row, dict) and int(row.get("segment_count", 0)) >= 100
            for row in output["results"]
        )
    except BaseException as exc:
        output["fatal_exception"] = f"{type(exc).__name__}: {exc}"
        output["fatal_traceback"] = traceback.format_exc()
    finally:
        OUTPUT.write_text(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
