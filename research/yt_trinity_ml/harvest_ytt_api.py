#!/usr/bin/env python3
"""Fetch one channel's complete timestamped caption set through a cloud-safe public API."""

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
from typing import Any

BASE = "https://api.youtubetotext.com"
USER_AGENT = "SMC-ICT-2-LIVE/1.0"
RESOLVED = {"ok", "verified_no_caption", "unavailable"}


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


def request_json(url: str, timeout: float = 50.0) -> tuple[int, Any, dict[str, str]]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
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
        segments.append({
            "index": int(row.get("index", index)),
            "start": round(start, 3),
            "duration": round(max(duration, 0.0), 3),
            "text": text,
        })
    segments.sort(key=lambda row: (row["start"], row["index"]))
    return segments


def fetch_video(video_id: str, attempts: int, pace_seconds: float) -> dict[str, Any]:
    history: list[dict[str, Any]] = []
    consistent_no_caption: list[tuple[str, str]] = []
    for attempt in range(1, attempts + 1):
        if attempt > 1:
            time.sleep(max(pace_seconds, 6.2) + random.random())
        url = f"{BASE}/full_transcript/{urllib.parse.quote(video_id)}?meta=true"
        try:
            status, payload, headers = request_json(url)
        except Exception as exc:
            history.append({"attempt": attempt, "exception": f"{type(exc).__name__}: {exc}"})
            continue
        record = {
            "attempt": attempt,
            "status_code": status,
            "error": payload.get("error") if isinstance(payload, dict) else None,
            "reason": payload.get("reason") if isinstance(payload, dict) else None,
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
                signature = (str(payload.get("error")), str(payload.get("reason")))
                consistent_no_caption.append(signature)
                if len(consistent_no_caption) >= 2 and len(set(consistent_no_caption[-2:])) == 1:
                    reason = signature[1].lower()
                    unavailable_terms = ("private", "unavailable", "removed", "age-restricted", "region")
                    status_name = "unavailable" if any(term in reason for term in unavailable_terms) else "verified_no_caption"
                    return {
                        "status": status_name,
                        "segments": [],
                        "error": signature[0],
                        "reason": signature[1],
                        "can_transcribe_with_ai": payload.get("canTranscribeWithAI"),
                        "attempt_history": history,
                    }
                continue
            history[-1]["error"] = "200 response without transcript or error"
            continue
        if status == 429:
            retry_after = record.get("retry_after")
            try:
                delay = max(float(retry_after), 65.0) if retry_after else 65.0
            except (TypeError, ValueError):
                delay = 65.0
            time.sleep(delay + random.random() * 2)
            continue
        if status in {408, 500, 502, 503, 504}:
            continue
        if status in {401, 403, 404, 410, 451}:
            return {
                "status": "unavailable",
                "segments": [],
                "error": payload.get("error") if isinstance(payload, dict) else f"HTTP {status}",
                "reason": payload.get("reason") if isinstance(payload, dict) else None,
                "attempt_history": history,
            }
    return {
        "status": "retry_required",
        "segments": [],
        "error": "caption API did not produce a stable resolved outcome",
        "attempt_history": history,
    }


def write_checkpoint(output: Path, channel: str, inventory: list[dict[str, Any]], outcomes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    transcript_root = output / "transcripts" / channel
    transcript_root.mkdir(parents=True, exist_ok=True)
    video_rows: list[dict[str, Any]] = []
    for item in inventory:
        video_id = item["video_id"]
        outcome = outcomes.get(video_id, {"status": "pending", "segments": []})
        segments = outcome.get("segments") or []
        row = {
            **item,
            "caption_status": outcome.get("status"),
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
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "provider": "api.youtubetotext.com/full_transcript",
        "channel_slug": channel,
        "updated_at_utc": utc_now(),
        "inventory_count": len(inventory),
        "status_counts": dict(sorted(counts.items())),
        "resolved_count": sum(counts[name] for name in RESOLVED),
        "all_resolved": all(row["caption_status"] in RESOLVED for row in video_rows),
        "videos_sha256": sha256_bytes(videos_raw.encode("utf-8")),
        "transcript_segment_count": sum(row["caption_segment_count"] for row in video_rows),
        "transcript_character_count": sum(row["caption_character_count"] for row in video_rows),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--channel", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--pace-seconds", type=float, default=6.4)
    args = parser.parse_args()

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
        outcomes[video_id] = fetch_video(video_id, args.attempts, args.pace_seconds)
        if index % 5 == 0 or index == len(inventory):
            manifest = write_checkpoint(args.output, args.channel, inventory, outcomes)
            print(json.dumps({"stage": "checkpoint", "completed": index, **manifest}, ensure_ascii=False), flush=True)
    manifest = write_checkpoint(args.output, args.channel, inventory, outcomes)
    print(json.dumps({"stage": "final", **manifest}, ensure_ascii=False, indent=2), flush=True)
    return 0 if manifest["all_resolved"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
