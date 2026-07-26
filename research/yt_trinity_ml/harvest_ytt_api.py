#!/usr/bin/env python3
"""Fetch one channel's timestamped native captions through a public cloud API.

Native-caption classification is not content completeness: a public video with no
native caption remains ASR_REQUIRED until an audio transcription is attached.
Transport/authentication failures must never be reclassified as unavailable videos.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

BASE = "https://api.youtubetotext.com"
USER_AGENT = "SMC-ICT-2-LIVE/1.0"
NATIVE_RESOLVED = {"ok", "native_no_caption", "unavailable"}
CONTENT_RESOLVED = {"ok", "unavailable"}
UNAVAILABLE_TERMS = (
    "private",
    "unavailable",
    "removed",
    "deleted",
    "age-restricted",
    "age restricted",
    "region",
    "not found",
    "does not exist",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_inventory(path: Path, channel: str) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = [row for row in rows if row.get("channel_slug") == channel]
    selected.sort(key=lambda row: row["video_id"])
    ids = [row["video_id"] for row in selected]
    if not selected:
        raise RuntimeError(f"no inventory rows for {channel}")
    if len(ids) != len(set(ids)):
        raise RuntimeError(f"duplicate video ids for {channel}")
    return selected


def request_json(
    url: str,
    timeout: float = 50.0,
    headers: Mapping[str, str] | None = None,
) -> tuple[int, Any, dict[str, str]]:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    request_headers.update(dict(headers or {}))
    request = urllib.request.Request(url, headers=request_headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
            try:
                payload = json.loads(raw)
            except Exception:
                payload = {"raw": raw.decode("utf-8", "replace")[:4000]}
            return int(response.status), payload, dict(response.headers)
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw.decode("utf-8", "replace")[:4000]}
        return int(exc.code), payload, dict(exc.headers)


def normalize_transcript(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw = payload.get("transcript")
    if not isinstance(raw, list):
        return []
    segments: list[dict[str, Any]] = []
    for index, row in enumerate(raw):
        if not isinstance(row, dict):
            continue
        text = " ".join(str(row.get("text") or "").split())
        if not text:
            continue
        try:
            start = float(row.get("start") or 0.0)
            duration = float(row.get("duration") or 0.0)
        except (TypeError, ValueError):
            continue
        segments.append(
            {
                "index": int(row.get("index", index)),
                "start": round(start, 3),
                "duration": round(max(duration, 0.0), 3),
                "text": text,
            }
        )
    segments.sort(key=lambda row: (row["start"], row["index"]))
    return segments


def _payload_error(payload: Any) -> tuple[str, str]:
    if not isinstance(payload, Mapping):
        return "", ""
    return str(payload.get("error") or ""), str(payload.get("reason") or "")


def _explicitly_unavailable(error: str, reason: str) -> bool:
    text = f"{error} {reason}".lower()
    return any(term in text for term in UNAVAILABLE_TERMS)


def fetch_video(
    video_id: str,
    attempts: int,
    pace_seconds: float,
    api_key: str | None = None,
) -> dict[str, Any]:
    history: list[dict[str, Any]] = []
    consistent_native_absence: list[tuple[str, str]] = []
    request_headers = {"X-API-Key": api_key} if api_key else {}
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(max(pace_seconds, 6.2) + random.random())
        url = f"{BASE}/full_transcript/{urllib.parse.quote(video_id)}?meta=true"
        try:
            status, payload, headers = request_json(url, headers=request_headers)
        except Exception as exc:  # noqa: BLE001 - exact transport failure is evidence
            history.append({"attempt": attempt, "exception": f"{type(exc).__name__}: {exc}"})
            continue
        error, reason = _payload_error(payload)
        record = {
            "attempt": attempt,
            "status_code": status,
            "error": error or None,
            "reason": reason or None,
            "retry_after": headers.get("Retry-After") or headers.get("retry-after"),
        }
        history.append(record)

        if status == 200 and isinstance(payload, dict):
            segments = normalize_transcript(payload)
            if segments:
                return {
                    "status": "ok",
                    "segments": segments,
                    "language": payload.get("language"),
                    "language_code": payload.get("language_code"),
                    "source_type": payload.get("source_type"),
                    "attempt_history": history,
                }
            if payload.get("error"):
                signature = (error, reason)
                consistent_native_absence.append(signature)
                if len(consistent_native_absence) >= 2 and len(set(consistent_native_absence[-2:])) == 1:
                    if _explicitly_unavailable(error, reason):
                        return {
                            "status": "unavailable",
                            "segments": [],
                            "error": error,
                            "reason": reason,
                            "can_transcribe_with_ai": payload.get("canTranscribeWithAI"),
                            "attempt_history": history,
                        }
                    return {
                        "status": "native_no_caption",
                        "segments": [],
                        "error": error,
                        "reason": reason,
                        "can_transcribe_with_ai": payload.get("canTranscribeWithAI"),
                        "attempt_history": history,
                    }
                continue
            history[-1]["error"] = "200 response without transcript or explicit native-caption classification"
            continue

        if status == 429:
            retry_after = record.get("retry_after")
            try:
                delay = max(float(retry_after), 65.0) if retry_after else 65.0
            except (TypeError, ValueError):
                delay = 65.0
            time.sleep(delay + random.random() * 2)
            continue
        if status in {401, 403}:
            history[-1]["classification"] = "transport_authentication_failure"
            continue
        if status in {408, 500, 502, 503, 504}:
            history[-1]["classification"] = "transient_upstream_failure"
            continue
        if status in {404, 410, 451}:
            if _explicitly_unavailable(error, reason):
                return {
                    "status": "unavailable",
                    "segments": [],
                    "error": error or f"HTTP {status}",
                    "reason": reason or None,
                    "attempt_history": history,
                }
            history[-1]["classification"] = "ambiguous_http_failure"
            continue

    return {
        "status": "retry_required",
        "segments": [],
        "error": "caption API did not produce a stable resolved outcome",
        "attempt_history": history,
    }


def write_checkpoint(
    output: Path,
    channel: str,
    inventory: list[dict[str, Any]],
    outcomes: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    transcript_root = output / "transcripts" / channel
    transcript_root.mkdir(parents=True, exist_ok=True)
    video_rows: list[dict[str, Any]] = []
    for item in inventory:
        video_id = item["video_id"]
        outcome = outcomes.get(video_id, {"status": "pending", "segments": []})
        segments = outcome.get("segments") or []
        status = outcome.get("status")
        row = {
            **item,
            "caption_status": status,
            "content_status": (
                "timestamped_transcript"
                if status == "ok"
                else "asr_required"
                if status == "native_no_caption"
                else status
            ),
            "caption_language": outcome.get("language"),
            "caption_language_code": outcome.get("language_code"),
            "caption_source_type": outcome.get("source_type"),
            "caption_segment_count": len(segments),
            "caption_character_count": sum(len(segment["text"]) for segment in segments),
            "caption_error": outcome.get("error"),
            "caption_reason": outcome.get("reason"),
            "can_transcribe_with_ai": outcome.get("can_transcribe_with_ai"),
            "attempt_history": outcome.get("attempt_history", []),
        }
        video_rows.append(row)
        if segments:
            jsonl = "".join(json.dumps(segment, ensure_ascii=False, sort_keys=True) + "\n" for segment in segments)
            text = "\n".join(f"[{segment['start']:.3f}] {segment['text']}" for segment in segments) + "\n"
            (transcript_root / f"{video_id}.jsonl").write_text(jsonl, encoding="utf-8")
            (transcript_root / f"{video_id}.txt").write_text(text, encoding="utf-8")
    videos_raw = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in video_rows)
    (output / "videos.jsonl").write_text(videos_raw, encoding="utf-8")
    counts = Counter(row["caption_status"] for row in video_rows)
    native_complete = all(row["caption_status"] in NATIVE_RESOLVED for row in video_rows)
    content_complete = all(row["caption_status"] in CONTENT_RESOLVED for row in video_rows)
    manifest = {
        "schema_version": 2,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "provider": "api.youtubetotext.com/full_transcript",
        "channel_slug": channel,
        "updated_at_utc": utc_now(),
        "inventory_count": len(inventory),
        "status_counts": dict(sorted(counts.items())),
        "native_resolved_count": sum(counts[name] for name in NATIVE_RESOLVED),
        "content_resolved_count": sum(counts[name] for name in CONTENT_RESOLVED),
        "native_caption_classification_complete": native_complete,
        "transcript_content_complete": content_complete,
        "asr_required_count": counts.get("native_no_caption", 0),
        "videos_sha256": sha256_bytes(videos_raw.encode("utf-8")),
        "transcript_segment_count": sum(row["caption_segment_count"] for row in video_rows),
        "transcript_character_count": sum(row["caption_character_count"] for row in video_rows),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--pace-seconds", type=float, default=6.4)
    parser.add_argument("--api-key-env", default="")
    args = parser.parse_args()

    api_key = os.environ.get(args.api_key_env) if args.api_key_env else None
    if args.api_key_env and not api_key:
        raise SystemExit(f"API key environment variable is missing: {args.api_key_env}")
    health_status, health, _ = request_json(f"{BASE}/health")
    if health_status != 200 or not isinstance(health, dict) or health.get("status") != "ok":
        raise SystemExit(f"transcript API health failed: {health_status} {health}")

    inventory = load_inventory(args.inventory, args.channel)
    outcomes: dict[str, dict[str, Any]] = {}
    manifest = write_checkpoint(args.output, args.channel, inventory, outcomes)
    print(json.dumps({"stage": "start", **manifest}, ensure_ascii=False), flush=True)
    for index, item in enumerate(inventory, start=1):
        if index > 1:
            time.sleep(max(args.pace_seconds, 6.2))
        video_id = item["video_id"]
        outcomes[video_id] = fetch_video(video_id, args.attempts, args.pace_seconds, api_key)
        if index % 5 == 0 or index == len(inventory):
            manifest = write_checkpoint(args.output, args.channel, inventory, outcomes)
            print(json.dumps({"stage": "checkpoint", "completed": index, **manifest}, ensure_ascii=False), flush=True)
    manifest = write_checkpoint(args.output, args.channel, inventory, outcomes)
    print(json.dumps({"stage": "final", **manifest}, ensure_ascii=False, indent=2), flush=True)
    return 0 if manifest["native_caption_classification_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
