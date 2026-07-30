#!/usr/bin/env python3
"""Validate independent public transcript services with a known positive control."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

VIDEOS = (
    ("chartbro", "0h9lpMUBSlE"),
    ("swipalnam", "-Tp2fhvVVGM"),
    ("indicator_sensei", "2U0s_i07vMY"),
    ("known_positive_control", "F6wDs1HRTSo"),
)
USER_AGENT = "SMC-ICT-2-LIVE-transcript-validation/1.0"


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    params: Mapping[str, Any] | None = None,
    json_body: Mapping[str, Any] | None = None,
    data: bytes | str | None = None,
    timeout: float = 90.0,
) -> tuple[int | None, Any, dict[str, str], str | None]:
    try:
        response = session.request(
            method,
            url,
            headers=dict(headers or {}),
            params=dict(params or {}),
            json=dict(json_body or {}) if json_body is not None else None,
            data=data,
            timeout=timeout,
        )
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text[:200000]}
        filtered_headers = {
            key: value
            for key, value in response.headers.items()
            if any(token in key.lower() for token in ("rate", "retry", "content-type", "request-id"))
        }
        return response.status_code, payload, filtered_headers, None
    except Exception as exc:  # noqa: BLE001 - exact provider failure is evidence
        return None, None, {}, f"{type(exc).__name__}: {exc}"[-4000:]


def segment_summary(segments: Any) -> tuple[int, int, list[dict[str, Any]], bool]:
    if not isinstance(segments, list):
        return 0, 0, [], False
    normalized: list[dict[str, Any]] = []
    timestamped = True
    characters = 0
    for index, item in enumerate(segments):
        if isinstance(item, Mapping):
            text = str(item.get("text") or item.get("content") or "").strip()
            start = item.get("start")
            duration = item.get("duration")
        else:
            text = str(item).strip()
            start = None
            duration = None
        if not text:
            continue
        characters += len(text)
        if start is None:
            timestamped = False
        if len(normalized) < 3:
            normalized.append({"index": index, "text": text, "start": start, "duration": duration})
    return sum(1 for item in segments if str(item.get("text") or item.get("content") or "").strip()) if all(isinstance(item, Mapping) for item in segments) else len(segments), characters, normalized, timestamped


def youtube_to_text(session: requests.Session, output: Path, delay: float) -> dict[str, Any]:
    status, registration, headers, error = request_json(
        session,
        "POST",
        "https://api.youtubetotext.com/free/register",
        data=b"",
    )
    key = registration.get("api_key") if isinstance(registration, Mapping) else None
    result: dict[str, Any] = {
        "provider": "api.youtubetotext.com",
        "registration_status": status,
        "registration_error": error,
        "registration_tier": registration.get("tier") if isinstance(registration, Mapping) else None,
        "registration_daily_fetch_cap": registration.get("daily_fetch_cap") if isinstance(registration, Mapping) else None,
        "registration_headers": headers,
        "rows": [],
    }
    if not key:
        result["registration_body"] = registration
        return result
    for index, (channel, video_id) in enumerate(VIDEOS):
        if index:
            time.sleep(delay)
        status, payload, headers, error = request_json(
            session,
            "GET",
            f"https://api.youtubetotext.com/full_transcript/{video_id}",
            headers={"X-API-Key": str(key)},
            params={"meta": "true"},
        )
        segments = payload.get("transcript") if isinstance(payload, Mapping) else None
        count, characters, first, timestamped = segment_summary(segments)
        row = {
            "channel": channel,
            "video_id": video_id,
            "status_code": status,
            "segment_count": count,
            "text_chars": characters,
            "timestamped": timestamped and count > 0,
            "language": payload.get("language") if isinstance(payload, Mapping) else None,
            "language_code": payload.get("language_code") if isinstance(payload, Mapping) else None,
            "source_type": payload.get("source_type") if isinstance(payload, Mapping) else None,
            "provider_error": payload.get("error") if isinstance(payload, Mapping) else None,
            "reason": payload.get("reason") if isinstance(payload, Mapping) else None,
            "can_transcribe_with_ai": payload.get("canTranscribeWithAI") if isinstance(payload, Mapping) else None,
            "request_error": error,
            "rate_headers": headers,
            "first_segments": first,
            "payload_sha256": digest(payload),
        }
        result["rows"].append(row)
        (output / f"{channel}-{video_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


def youtube2text(session: requests.Session, output: Path, delay: float) -> dict[str, Any]:
    status, registration, headers, error = request_json(session, "GET", "https://youtube2text.org/api/demo-key")
    key = registration.get("apiKey") if isinstance(registration, Mapping) else None
    result: dict[str, Any] = {
        "provider": "youtube2text.org",
        "registration_status": status,
        "registration_error": error,
        "registration_headers": headers,
        "rows": [],
    }
    if not key:
        result["registration_body"] = registration
        return result
    for index, (channel, video_id) in enumerate(VIDEOS):
        if index:
            time.sleep(delay)
        status, payload, headers, error = request_json(
            session,
            "GET",
            "https://youtube2text.org/api/transcribe",
            headers={"x-api-key": str(key)},
            params={
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "maxChars": 200000,
            },
            timeout=120.0,
        )
        transcript = None
        if isinstance(payload, Mapping):
            transcript = payload.get("transcript") or payload.get("text") or payload.get("content")
        if transcript is None and isinstance(payload, str):
            transcript = payload
        text = transcript if isinstance(transcript, str) else ""
        row = {
            "channel": channel,
            "video_id": video_id,
            "status_code": status,
            "text_chars": len(text),
            "timestamped": False,
            "success": bool(text.strip()),
            "request_error": error,
            "rate_headers": headers,
            "payload_sha256": digest(payload),
            "payload_keys": sorted(payload) if isinstance(payload, Mapping) else [],
            "error_code": payload.get("code") if isinstance(payload, Mapping) else None,
            "error": payload.get("error") if isinstance(payload, Mapping) else None,
            "text_prefix": text[:500],
        }
        result["rows"].append(row)
        (output / f"{channel}-{video_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


def get_video_transcript(session: requests.Session, output: Path, delay: float) -> dict[str, Any]:
    result: dict[str, Any] = {"provider": "getvideotranscript.com", "rows": []}
    health_status, health, health_headers, health_error = request_json(
        session,
        "GET",
        "https://getvideotranscript.com/api/health",
    )
    result.update(
        {
            "health_status": health_status,
            "health": health,
            "health_headers": health_headers,
            "health_error": health_error,
        }
    )
    for index, (channel, video_id) in enumerate(VIDEOS):
        if index:
            time.sleep(delay)
        status, payload, headers, error = request_json(
            session,
            "GET",
            "https://getvideotranscript.com/api/youtube",
            params={"video_id": video_id},
            timeout=120.0,
        )
        segments = payload.get("transcript") if isinstance(payload, Mapping) else None
        count, characters, first, timestamped = segment_summary(segments)
        row = {
            "channel": channel,
            "video_id": video_id,
            "status_code": status,
            "success": bool(payload.get("success")) if isinstance(payload, Mapping) else False,
            "segment_count": count,
            "text_chars": characters,
            "timestamped": timestamped and count > 0,
            "request_error": error,
            "provider_error": payload.get("error") if isinstance(payload, Mapping) else None,
            "rate_headers": headers,
            "first_segments": first,
            "payload_sha256": digest(payload),
        }
        result["rows"].append(row)
        (output / f"{channel}-{video_id}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return result


PROVIDERS = {
    "youtube_to_text": youtube_to_text,
    "youtube2text": youtube2text,
    "get_video_transcript": get_video_transcript,
}


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", choices=sorted(PROVIDERS), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--delay-seconds", type=float, default=7.0)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.6"})
    try:
        result = PROVIDERS[args.provider](session, args.output, max(0.0, args.delay_seconds))
    finally:
        session.close()
    rows = result.get("rows") or []
    successful = [
        row
        for row in rows
        if int(row.get("segment_count") or 0) > 0 or int(row.get("text_chars") or 0) > 0
    ]
    positive = [row for row in successful if row.get("channel") == "known_positive_control"]
    failed_samples = [row for row in successful if row.get("channel") != "known_positive_control"]
    result.update(
        {
            "schema_version": 1,
            "run_id": os.environ.get("GITHUB_RUN_ID"),
            "source_sha": os.environ.get("GITHUB_SHA"),
            "runner": {"platform": platform.platform(), "python": platform.python_version()},
            "successful_video_count": len(successful),
            "positive_control_passed": bool(positive),
            "failed_sample_recovered_count": len(failed_samples),
        }
    )
    result["result_sha256_before_field"] = digest(result)
    (args.output / "probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
