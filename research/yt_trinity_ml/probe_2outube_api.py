#!/usr/bin/env python3
"""Probe the documented-in-page 2outube transcript JSON endpoint.

The public page embeds the exact browser call: GET /api/transcript?v=VIDEO_ID
with a per-device header.  This probe reproduces only that ordinary client call;
it does not solve, forge, or bypass Cloudflare Turnstile.  Cached transcripts may
load directly, while uncached videos may legitimately return needs_verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

VIDEOS = (
    ("known_positive_control", "F6wDs1HRTSo"),
    ("chartbro", "0h9lpMUBSlE"),
    ("swipalnam", "-Tp2fhvVVGM"),
    ("indicator_sensei", "2U0s_i07vMY"),
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def summarize(payload: Any) -> dict[str, Any]:
    transcript = payload.get("transcript") if isinstance(payload, Mapping) else None
    segments = transcript if isinstance(transcript, list) else []
    normalized = []
    chars = 0
    for item in segments:
        if not isinstance(item, Mapping):
            continue
        text = " ".join(str(item.get("text") or "").split())
        start = item.get("start")
        if not text or not isinstance(start, (int, float)):
            continue
        chars += len(text)
        if len(normalized) < 5:
            normalized.append(
                {
                    "start": start,
                    "duration": item.get("duration"),
                    "text": text[:500],
                }
            )
    return {
        "available": bool(payload.get("available")) if isinstance(payload, Mapping) else False,
        "from_cache": bool(payload.get("fromCache")) if isinstance(payload, Mapping) else False,
        "grace": bool(payload.get("grace")) if isinstance(payload, Mapping) else False,
        "failure_reason": payload.get("failureReason") if isinstance(payload, Mapping) else None,
        "segment_count": len(segments),
        "valid_timestamped_segment_count": sum(
            isinstance(item, Mapping)
            and bool(str(item.get("text") or "").strip())
            and isinstance(item.get("start"), (int, float))
            for item in segments
        ),
        "text_chars": chars,
        "first_segments": normalized,
        "payload_keys": sorted(payload) if isinstance(payload, Mapping) else [],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--delay-seconds", type=float, default=4.0)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)

    device_id = str(uuid.uuid4())
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132 Safari/537.36",
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
            "x-2outube-device": device_id,
            "x-2outube-ref": "chatgpt",
        }
    )
    rows: list[dict[str, Any]] = []
    try:
        for index, (channel, video_id) in enumerate(VIDEOS):
            if index:
                time.sleep(max(0.0, args.delay_seconds))
            page_url = f"https://2outube.com/watch?v={video_id}&src=chatgpt_plugin"
            api_url = f"https://2outube.com/api/transcript?v={video_id}"
            started = time.monotonic()
            row: dict[str, Any] = {
                "channel": channel,
                "video_id": video_id,
                "page_url": page_url,
                "api_url": api_url,
            }
            try:
                page = session.get(page_url, timeout=45)
                row.update(
                    {
                        "page_status": page.status_code,
                        "page_sha256": sha256_bytes(page.content),
                        "page_bytes": len(page.content),
                    }
                )
                headers = {
                    "Referer": page_url,
                    "Origin": "https://2outube.com",
                    "x-2outube-attempt": str(uuid.uuid4()),
                    "x-2outube-retry": "0",
                }
                response = session.get(api_url, headers=headers, timeout=180)
                raw = response.content
                try:
                    payload = response.json()
                except Exception:
                    payload = {"raw": response.text[:10000]}
                row.update(
                    {
                        "api_status": response.status_code,
                        "api_content_type": response.headers.get("content-type"),
                        "api_sha256": sha256_bytes(raw),
                        "api_bytes": len(raw),
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        **summarize(payload),
                    }
                )
                (args.output / f"{channel}-{video_id}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                    encoding="utf-8",
                )
            except Exception as exc:
                row.update(
                    {
                        "elapsed_seconds": round(time.monotonic() - started, 3),
                        "request_error": f"{type(exc).__name__}: {exc}"[-4000:],
                        "segment_count": 0,
                        "valid_timestamped_segment_count": 0,
                    }
                )
            rows.append(row)
    finally:
        session.close()

    positive = any(
        row["channel"] == "known_positive_control"
        and int(row.get("valid_timestamped_segment_count") or 0) >= 100
        for row in rows
    )
    recovered = [
        row
        for row in rows
        if row["channel"] != "known_positive_control"
        and int(row.get("valid_timestamped_segment_count") or 0) > 0
    ]
    result = {
        "schema_version": 1,
        "workflow": "YT Trinity 2outube JSON endpoint probe",
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "source_sha": os.environ.get("GITHUB_SHA"),
        "runner": {"platform": platform.platform(), "python": platform.python_version()},
        "device_id_sha256": sha256_bytes(device_id.encode("utf-8")),
        "positive_control_passed": positive,
        "target_recovered_count": len(recovered),
        "decision": "VALIDATED_PROVIDER" if positive and recovered else "FAIL",
        "rows": rows,
    }
    result["payload_sha256_before_field"] = sha256_bytes(canonical_json(result).encode("utf-8"))
    (args.output / "probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
