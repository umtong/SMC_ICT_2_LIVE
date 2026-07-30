#!/usr/bin/env python3
"""Harvest complete plain-text transcripts through the validated youtube2text service.

The provider returns full transcript text without native timestamps.  We preserve the
original text and create explicitly labelled proportional time anchors only so the
existing evidence index can address passages.  Those anchors are never represented as
native caption timestamps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

BASE_URL = "https://youtube2text.org"
USER_AGENT = "SMC-ICT-2-LIVE-youtube2text-corpus/1.0"
MAX_CHARS = 150_000
CHANNEL_DISPLAY = {
    "swipalnam": "쉽알남",
    "chartbro": "차트브로",
    "indicator_sensei": "지표센세",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def request_json(
    url: str,
    *,
    headers: Mapping[str, str] | None = None,
    timeout: float = 120.0,
) -> tuple[int | None, Any, dict[str, str], str | None]:
    request_headers = {
        "User-Agent": USER_AGENT,
        "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    }
    request_headers.update(dict(headers or {}))
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"raw": raw.decode("utf-8", "replace")[:8000]}
            selected_headers = {
                key: value
                for key, value in response.headers.items()
                if any(token in key.lower() for token in ("rate", "retry", "request-id", "content-type"))
            }
            return int(response.status), payload, selected_headers, None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw.decode("utf-8", "replace")[:8000]}
        selected_headers = {
            key: value
            for key, value in exc.headers.items()
            if any(token in key.lower() for token in ("rate", "retry", "request-id", "content-type"))
        }
        return int(exc.code), payload, selected_headers, None
    except Exception as exc:  # noqa: BLE001 - exact transport error is evidence
        return None, None, {}, f"{type(exc).__name__}: {exc}"[-4000:]


def register_demo_key() -> tuple[str | None, dict[str, Any]]:
    status, payload, headers, error = request_json(f"{BASE_URL}/api/demo-key", timeout=45.0)
    key = payload.get("apiKey") if isinstance(payload, Mapping) else None
    evidence = {
        "status_code": status,
        "request_error": error,
        "response_headers": headers,
        "success": bool(isinstance(key, str) and key.startswith("yt_")),
    }
    if not evidence["success"]:
        evidence["response"] = payload
        return None, evidence
    return str(key), evidence


def load_inventory(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda row: (str(row.get("channel_slug")), str(row.get("video_id"))))
    ids = [str(row.get("video_id")) for row in rows]
    if not rows:
        raise RuntimeError("inventory is empty")
    if len(ids) != len(set(ids)):
        raise RuntimeError("inventory contains duplicate video ids")
    return rows


def select_shard(rows: Sequence[dict[str, Any]], shard_index: int, shard_count: int) -> list[dict[str, Any]]:
    if shard_count <= 0 or shard_index < 0 or shard_index >= shard_count:
        raise ValueError("invalid shard coordinates")
    selected = [row for position, row in enumerate(rows) if position % shard_count == shard_index]
    if not selected:
        raise RuntimeError(f"empty shard {shard_index}/{shard_count}")
    return selected


def normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def split_passages(text: str, duration_s: float | None, target_chars: int = 460) -> list[dict[str, Any]]:
    normalized = normalize_text(text)
    if not normalized:
        return []
    words = normalized.split(" ")
    chunks: list[str] = []
    current: list[str] = []
    current_chars = 0
    for word in words:
        addition = len(word) + (1 if current else 0)
        current.append(word)
        current_chars += addition
        punctuation_boundary = bool(re.search(r"[.!?。！？]$", word))
        if current_chars >= target_chars and (punctuation_boundary or current_chars >= target_chars * 1.35):
            chunks.append(" ".join(current))
            current = []
            current_chars = 0
    if current:
        chunks.append(" ".join(current))

    total_chars = max(sum(len(chunk) for chunk in chunks), 1)
    duration_ms_total = max(int(round(float(duration_s or 0.0) * 1000)), 0)
    consumed = 0
    passages: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        start_fraction = consumed / total_chars
        consumed += len(chunk)
        end_fraction = consumed / total_chars
        start_ms = int(round(duration_ms_total * start_fraction)) if duration_ms_total else 0
        end_ms = int(round(duration_ms_total * end_fraction)) if duration_ms_total else 0
        passages.append(
            {
                "index": index,
                "start_ms": start_ms,
                "duration_ms": max(end_ms - start_ms, 0),
                "text": chunk,
                "timing_quality": "proportional_duration_estimate" if duration_ms_total else "unavailable",
            }
        )
    return passages


def payload_error(payload: Any) -> tuple[str | None, str | None, int | None]:
    if not isinstance(payload, Mapping):
        return None, None, None
    error = payload.get("error")
    if isinstance(error, Mapping):
        code = error.get("code")
        message = error.get("message") or error.get("details")
        retry = error.get("retryAfterSeconds")
    else:
        code = error
        message = payload.get("message") or payload.get("reason")
        retry = payload.get("retryAfterSeconds")
    try:
        retry_int = int(retry) if retry is not None else None
    except (TypeError, ValueError):
        retry_int = None
    return str(code) if code else None, str(message) if message else None, retry_int


def classify_failure(status: int | None, code: str | None, message: str | None) -> str:
    token = f"{code or ''} {message or ''}".lower()
    if status == 404 and any(term in token for term in ("transcript", "caption", "subtitle")):
        return "asr_required"
    if status == 404 and any(term in token for term in ("video_not_found", "not found", "unavailable", "private", "removed")):
        return "unavailable"
    if status == 429:
        return "rate_limited"
    if status in {401, 403}:
        return "authentication_failed"
    return "retry_required"


def fetch_video(item: Mapping[str, Any], api_key: str | None) -> tuple[dict[str, Any], list[dict[str, Any]], str | None]:
    video_id = str(item["video_id"])
    base_row = {
        **dict(item),
        "channel_display_name": CHANNEL_DISPLAY.get(str(item.get("channel_slug")), str(item.get("channel_slug"))),
        "caption_provider": "youtube2text.org/api/transcribe",
        "caption_timing_quality": "proportional_duration_estimate",
    }
    if not api_key:
        return (
            {
                **base_row,
                "caption_status": "authentication_failed",
                "caption_error": "demo API key registration failed",
                "caption_segment_count": 0,
                "caption_character_count": 0,
            },
            [],
            None,
        )

    video_url = f"https://www.youtube.com/watch?v={video_id}"
    query = urllib.parse.urlencode({"url": video_url, "maxChars": MAX_CHARS})
    status, payload, headers, request_error = request_json(
        f"{BASE_URL}/api/transcribe?{query}",
        headers={"x-api-key": api_key},
    )
    result = payload.get("result") if isinstance(payload, Mapping) else None
    content = normalize_text(result.get("content")) if isinstance(result, Mapping) else ""
    truncated = bool(result.get("truncated")) if isinstance(result, Mapping) else False
    code, message, retry_after = payload_error(payload)
    if content:
        passages = split_passages(content, item.get("duration_s"))
        transcript_path = f"transcripts/{item['channel_slug']}/{video_id}.jsonl"
        text_path = f"transcripts/{item['channel_slug']}/{video_id}.txt"
        row = {
            **base_row,
            "title": result.get("title") or item.get("title"),
            "published_at": result.get("pubDate"),
            "caption_status": "truncated_retry_required" if truncated else "ok",
            "caption_error": "provider response was truncated" if truncated else None,
            "caption_segment_count": len(passages),
            "caption_character_count": len(content),
            "provider_content_size": result.get("contentSize"),
            "provider_truncated": truncated,
            "provider_http_status": status,
            "provider_rate_headers": headers,
            "provider_payload_sha256": sha256_bytes(canonical_json(payload).encode("utf-8")),
            "transcript_jsonl": transcript_path,
            "transcript_txt": text_path,
        }
        return row, passages, content

    failure = classify_failure(status, code, message)
    row = {
        **base_row,
        "caption_status": failure,
        "caption_error_code": code,
        "caption_error": message or request_error or f"HTTP {status}",
        "caption_segment_count": 0,
        "caption_character_count": 0,
        "provider_http_status": status,
        "provider_retry_after_seconds": retry_after,
        "provider_rate_headers": headers,
        "provider_payload_sha256": sha256_bytes(canonical_json(payload).encode("utf-8")) if payload is not None else None,
    }
    return row, [], None


def write_shard(
    output: Path,
    selected: Sequence[dict[str, Any]],
    shard_index: int,
    shard_count: int,
    registration: Mapping[str, Any],
    api_key: str | None,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for item in selected:
        row, passages, content = fetch_video(item, api_key)
        rows.append(row)
        if passages and content is not None:
            transcript_jsonl = output / str(row["transcript_jsonl"])
            transcript_txt = output / str(row["transcript_txt"])
            transcript_jsonl.parent.mkdir(parents=True, exist_ok=True)
            transcript_jsonl.write_text(
                "".join(canonical_json(segment) + "\n" for segment in passages),
                encoding="utf-8",
            )
            transcript_txt.write_text(content + "\n", encoding="utf-8")
        print(
            canonical_json(
                {
                    "video_id": row["video_id"],
                    "channel_slug": row["channel_slug"],
                    "caption_status": row["caption_status"],
                    "caption_character_count": row["caption_character_count"],
                }
            ),
            flush=True,
        )

    videos_raw = "".join(canonical_json(row) + "\n" for row in rows)
    (output / "videos.jsonl").write_text(videos_raw, encoding="utf-8")
    counts = Counter(str(row.get("caption_status")) for row in rows)
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "provider": "youtube2text.org/api/transcribe",
        "built_at_utc": utc_now(),
        "shard_index": shard_index,
        "shard_count": shard_count,
        "inventory_count": len(selected),
        "status_counts": dict(sorted(counts.items())),
        "transcript_video_count": counts.get("ok", 0),
        "transcript_character_count": sum(int(row.get("caption_character_count") or 0) for row in rows),
        "registration": dict(registration),
        "videos_sha256": sha256_bytes(videos_raw.encode("utf-8")),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def self_test() -> None:
    payload = {"result": {"content": "유동성 스윕 후 FVG 리테스트에서 진입합니다.", "truncated": False}}
    result = payload["result"]
    text = normalize_text(result["content"])
    passages = split_passages(text, 120.0, target_chars=8)
    assert text and passages
    assert passages[0]["start_ms"] == 0
    assert passages[-1]["start_ms"] + passages[-1]["duration_ms"] <= 120_000
    assert classify_failure(404, "TRANSCRIPT_UNAVAILABLE", "No transcript") == "asr_required"
    assert classify_failure(404, "VIDEO_NOT_FOUND", "Video not found") == "unavailable"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--shard-index", type=int, default=0)
    parser.add_argument("--shard-count", type=int, default=1)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        print("self-test: PASS")
        return 0
    if args.inventory is None or args.output is None:
        parser.error("--inventory and --output are required")

    inventory = load_inventory(args.inventory)
    selected = select_shard(inventory, args.shard_index, args.shard_count)
    if len(selected) > 3:
        raise SystemExit(f"shard contains {len(selected)} videos; the validated demo quota allows at most 3 with retry headroom")
    api_key, registration = register_demo_key()
    manifest = write_shard(
        args.output,
        selected,
        args.shard_index,
        args.shard_count,
        registration,
        api_key,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
