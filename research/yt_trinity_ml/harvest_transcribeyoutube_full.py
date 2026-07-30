#!/usr/bin/env python3
"""Harvest the complete YT Trinity inventory through one validated caption API.

The provider was validated independently on a known-caption control and on every
previously unresolved target.  Requests are deliberately sequential and paced at
6.5 seconds, below the provider's documented 10 requests/minute/IP contract.  The
script writes deterministic checkpoints, native timestamped segments, response
hashes, explicit no-caption/unavailable states, and a corpus manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

ENDPOINT = "https://transcribeyoutube.com/api/transcript"
PROVIDER = "transcribeyoutube.com/api/transcript"
POSITIVE_CONTROL_ID = "F6wDs1HRTSo"
FINAL_STATUSES = {"ok", "no_caption", "unavailable"}
NO_CAPTION_ERRORS = {"NO_CAPTIONS", "CAPTIONS_DISABLED"}
UNAVAILABLE_ERRORS = {
    "VIDEO_UNAVAILABLE",
    "PRIVATE_VIDEO",
    "MEMBERS_ONLY",
    "AGE_RESTRICTED",
    "INVALID_URL",
    "NOT_FOUND",
}
RETRYABLE_ERRORS = {"AUTOMATED_ACCESS", "FETCH_ERROR", "INTERNAL_ERROR", "RATE_LIMITED"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    return sha256_bytes(value.encode("utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{number}: expected object")
        rows.append(value)
    return rows


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
    temporary.replace(path)


def validate_inventory(rows: list[dict[str, Any]]) -> None:
    ids = [str(row.get("video_id") or "") for row in rows]
    if not rows:
        raise ValueError("inventory is empty")
    if any(len(video_id) != 11 for video_id in ids):
        raise ValueError("inventory contains invalid video id")
    if len(ids) != len(set(ids)):
        raise ValueError("inventory contains duplicate video ids")
    required = {"video_id", "channel_slug", "channel_display_name", "title"}
    for row in rows:
        missing = required - set(row)
        if missing:
            raise ValueError(f"inventory row missing {sorted(missing)}")


def normalize_segments(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    transcript = payload.get("transcript")
    if not isinstance(transcript, list):
        return []
    rows: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for index, item in enumerate(transcript):
        if not isinstance(item, Mapping):
            continue
        text = " ".join(str(item.get("text") or "").split())
        if not text:
            continue
        try:
            start_ms = max(0, round(float(item.get("start") or 0) * 1000))
            duration_ms = max(0, round(float(item.get("dur") or item.get("duration") or 0) * 1000))
        except (TypeError, ValueError):
            continue
        key = (start_ms, duration_ms, text)
        if key in seen:
            continue
        seen.add(key)
        rows.append(
            {
                "index": index,
                "start_ms": start_ms,
                "duration_ms": duration_ms,
                "text": text,
                "timing_quality": "native_caption_api",
            }
        )
    rows.sort(key=lambda row: (row["start_ms"], row["index"]))
    return rows


class PacedProvider:
    def __init__(self, pace_seconds: float = 6.5, timeout_seconds: float = 90.0) -> None:
        self.pace_seconds = pace_seconds
        self.timeout_seconds = timeout_seconds
        self.last_started = 0.0
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": "https://transcribeyoutube.com",
                "Referer": "https://transcribeyoutube.com/",
                "User-Agent": "SMC-ICT-2-LIVE-transcript-research/1.0",
            }
        )

    def close(self) -> None:
        self.session.close()

    def post(self, video_id: str) -> tuple[requests.Response, bytes, Any]:
        elapsed = time.monotonic() - self.last_started
        if self.last_started and elapsed < self.pace_seconds:
            time.sleep(self.pace_seconds - elapsed)
        self.last_started = time.monotonic()
        response = self.session.post(
            ENDPOINT,
            json={"url": f"https://www.youtube.com/watch?v={video_id}", "lang": "auto"},
            timeout=self.timeout_seconds,
        )
        raw = response.content
        try:
            payload: Any = response.json()
        except Exception:
            payload = None
        return response, raw, payload


def classify(
    item: Mapping[str, Any],
    response: requests.Response,
    raw: bytes,
    payload: Any,
    attempts: list[dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
    video_id = str(item["video_id"])
    evidence: dict[str, Any] = {
        "http_status": response.status_code,
        "content_type": response.headers.get("content-type"),
        "response_bytes": len(raw),
        "response_sha256": sha256_bytes(raw),
        "rate_limit": {
            key: value
            for key, value in response.headers.items()
            if key.lower().startswith(("x-rate", "retry-after"))
        },
    }
    if isinstance(payload, Mapping):
        evidence.update(
            {
                "ok": payload.get("ok"),
                "error": payload.get("error"),
                "message": payload.get("message"),
                "selected_lang": payload.get("selectedLang"),
                "auto_generated": payload.get("isAutoGenerated"),
            }
        )
    attempts.append(evidence)
    segments = normalize_segments(payload) if isinstance(payload, Mapping) else []
    if response.ok and isinstance(payload, Mapping) and payload.get("ok") is True and segments:
        plain = " ".join(segment["text"] for segment in segments)
        row = {
            **item,
            "caption_status": "ok",
            "caption_provider": PROVIDER,
            "caption_timing_quality": "native_caption_api",
            "caption_segment_count": len(segments),
            "caption_character_count": len(plain),
            "caption_language_code": payload.get("selectedLang"),
            "caption_auto_generated": payload.get("isAutoGenerated"),
            "provider_title": payload.get("title"),
            "provider_channel": payload.get("channel"),
            "caption_text_sha256": sha256_text(plain),
            "provider_response_sha256": sha256_bytes(raw),
            "attempts": attempts,
        }
        return row, segments, False

    error = str(payload.get("error") or "") if isinstance(payload, Mapping) else ""
    message = str(payload.get("message") or "") if isinstance(payload, Mapping) else ""
    if error in NO_CAPTION_ERRORS:
        return (
            {
                **item,
                "caption_status": "no_caption",
                "caption_provider": PROVIDER,
                "caption_timing_quality": None,
                "caption_segment_count": 0,
                "caption_character_count": 0,
                "caption_error_code": error,
                "caption_error": message,
                "provider_response_sha256": sha256_bytes(raw),
                "attempts": attempts,
            },
            [],
            False,
        )
    if error in UNAVAILABLE_ERRORS or response.status_code in {404, 410, 451}:
        return (
            {
                **item,
                "caption_status": "unavailable",
                "caption_provider": PROVIDER,
                "caption_timing_quality": None,
                "caption_segment_count": 0,
                "caption_character_count": 0,
                "caption_error_code": error or f"HTTP_{response.status_code}",
                "caption_error": message,
                "provider_response_sha256": sha256_bytes(raw),
                "attempts": attempts,
            },
            [],
            False,
        )
    retryable = error in RETRYABLE_ERRORS or response.status_code in {408, 409, 425, 429} or response.status_code >= 500
    return (
        {
            **item,
            "caption_status": "retry_required",
            "caption_provider": PROVIDER,
            "caption_timing_quality": None,
            "caption_segment_count": 0,
            "caption_character_count": 0,
            "caption_error_code": error or f"HTTP_{response.status_code}",
            "caption_error": message or "provider returned no usable timestamped transcript",
            "provider_response_sha256": sha256_bytes(raw),
            "attempts": attempts,
        },
        [],
        retryable,
    )


def fetch_one(provider: PacedProvider, item: Mapping[str, Any], max_attempts: int) -> tuple[dict[str, Any], list[dict[str, Any]], Any]:
    attempts: list[dict[str, Any]] = []
    final_payload: Any = None
    for attempt in range(1, max_attempts + 1):
        try:
            response, raw, payload = provider.post(str(item["video_id"]))
            final_payload = payload
            row, segments, retryable = classify(item, response, raw, payload, attempts)
            attempts[-1]["attempt"] = attempt
            if row["caption_status"] in FINAL_STATUSES or not retryable:
                return row, segments, final_payload
        except Exception as exc:
            attempts.append(
                {
                    "attempt": attempt,
                    "exception": f"{type(exc).__name__}: {exc}"[-2000:],
                }
            )
        if attempt < max_attempts:
            time.sleep(8.0 * attempt)
    return (
        {
            **item,
            "caption_status": "retry_required",
            "caption_provider": PROVIDER,
            "caption_timing_quality": None,
            "caption_segment_count": 0,
            "caption_character_count": 0,
            "caption_error": "all bounded attempts failed",
            "attempts": attempts,
        },
        [],
        final_payload,
    )


def build_manifest(
    inventory_path: Path,
    rows: list[dict[str, Any]],
    source_inventory_manifest: Mapping[str, Any] | None,
    completed: int,
) -> dict[str, Any]:
    statuses = Counter(str(row.get("caption_status") or "pending") for row in rows)
    channels: dict[str, Counter[str]] = {}
    for row in rows:
        channels.setdefault(str(row["channel_slug"]), Counter())[str(row.get("caption_status") or "pending")] += 1
    classification_complete = completed == len(rows) and set(statuses).issubset(FINAL_STATUSES)
    positive = next((row for row in rows if row["video_id"] == POSITIVE_CONTROL_ID), None)
    canonical = [
        {
            "video_id": row["video_id"],
            "channel_slug": row["channel_slug"],
            "caption_status": row.get("caption_status"),
            "caption_text_sha256": row.get("caption_text_sha256"),
            "caption_segment_count": row.get("caption_segment_count"),
        }
        for row in rows
    ]
    return {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "provider": PROVIDER,
        "provider_contract": {
            "endpoint": "POST /api/transcript",
            "language": "auto",
            "documented_rate_limit": "10 per minute per IP",
            "request_pace_seconds": 6.5,
        },
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "source_sha": os.environ.get("GITHUB_SHA"),
        "built_at_utc": utc_now(),
        "inventory_path": str(inventory_path),
        "inventory_sha256": sha256_bytes(inventory_path.read_bytes()),
        "source_inventory_manifest": source_inventory_manifest,
        "inventory_count": len(rows),
        "completed_count": completed,
        "status_counts": dict(sorted(statuses.items())),
        "channel_status_counts": {
            slug: dict(sorted(counts.items())) for slug, counts in sorted(channels.items())
        },
        "caption_classification_complete": classification_complete,
        "positive_control_passed": bool(
            positive
            and positive.get("caption_status") == "ok"
            and int(positive.get("caption_segment_count") or 0) >= 50
        ),
        "total_caption_segments": sum(int(row.get("caption_segment_count") or 0) for row in rows),
        "total_caption_characters": sum(int(row.get("caption_character_count") or 0) for row in rows),
        "corpus_digest_sha256": sha256_text(canonical_json(canonical)),
        "decision": "PASS_COMPLETE" if classification_complete else "IN_PROGRESS" if completed < len(rows) else "PARTIAL_REQUIRES_RETRY",
    }


def checkpoint(
    output: Path,
    inventory_path: Path,
    rows: list[dict[str, Any]],
    source_inventory_manifest: Mapping[str, Any] | None,
    completed: int,
) -> dict[str, Any]:
    write_jsonl(output / "videos.jsonl", rows)
    manifest = build_manifest(inventory_path, rows, source_inventory_manifest, completed)
    write_json(output / "manifest.json", manifest)
    return manifest


def run(
    inventory_path: Path,
    inventory_manifest_path: Path | None,
    output: Path,
    max_attempts: int,
    checkpoint_every: int,
) -> dict[str, Any]:
    inventory = read_jsonl(inventory_path)
    validate_inventory(inventory)
    source_inventory_manifest = (
        json.loads(inventory_manifest_path.read_text(encoding="utf-8"))
        if inventory_manifest_path and inventory_manifest_path.exists()
        else None
    )
    order = sorted(
        inventory,
        key=lambda row: (
            0 if row["video_id"] == POSITIVE_CONTROL_ID else 1,
            str(row["channel_slug"]),
            str(row["video_id"]),
        ),
    )
    rows = [{**item, "caption_status": "pending"} for item in order]
    by_id = {row["video_id"]: row for row in rows}
    output.mkdir(parents=True, exist_ok=True)
    transcripts = output / "transcripts"
    raw_root = output / "provider_raw"
    transcripts.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    checkpoint(output, inventory_path, rows, source_inventory_manifest, 0)

    provider = PacedProvider()
    completed = 0
    try:
        for item in order:
            row, segments, raw_payload = fetch_one(provider, item, max_attempts)
            if raw_payload is not None:
                write_json(raw_root / f"{item['video_id']}.json", raw_payload)
                row["provider_raw_json"] = str((raw_root / f"{item['video_id']}.json").relative_to(output))
            if segments:
                channel_dir = transcripts / str(item["channel_slug"])
                channel_dir.mkdir(parents=True, exist_ok=True)
                jsonl_path = channel_dir / f"{item['video_id']}.jsonl"
                txt_path = channel_dir / f"{item['video_id']}.txt"
                write_jsonl(jsonl_path, segments)
                txt_path.write_text(" ".join(segment["text"] for segment in segments) + "\n", encoding="utf-8")
                row["transcript_jsonl"] = str(jsonl_path.relative_to(output))
                row["transcript_txt"] = str(txt_path.relative_to(output))
            by_id[item["video_id"]] = row
            completed += 1
            rows = [by_id[value["video_id"]] for value in order]
            print(
                canonical_json(
                    {
                        "completed": completed,
                        "total": len(rows),
                        "video_id": item["video_id"],
                        "channel_slug": item["channel_slug"],
                        "caption_status": row["caption_status"],
                        "caption_segment_count": row.get("caption_segment_count", 0),
                    }
                ),
                flush=True,
            )
            if completed % max(1, checkpoint_every) == 0 or completed == len(rows):
                checkpoint(output, inventory_path, rows, source_inventory_manifest, completed)
    finally:
        provider.close()
        rows = [by_id[value["video_id"]] for value in order]
        manifest = checkpoint(output, inventory_path, rows, source_inventory_manifest, completed)
    return manifest


def self_test() -> None:
    payload = {
        "ok": True,
        "transcript": [
            {"start": 1.25, "dur": 2.5, "text": " hello   world "},
            {"start": 1.25, "dur": 2.5, "text": " hello   world "},
            {"start": 4, "dur": 1, "text": "next"},
        ],
    }
    rows = normalize_segments(payload)
    assert rows == [
        {"index": 0, "start_ms": 1250, "duration_ms": 2500, "text": "hello world", "timing_quality": "native_caption_api"},
        {"index": 2, "start_ms": 4000, "duration_ms": 1000, "text": "next", "timing_quality": "native_caption_api"},
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--inventory-manifest", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--checkpoint-every", type=int, default=10)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        print("self-test: PASS")
        return 0
    if not args.inventory or not args.output:
        parser.error("--inventory and --output are required")
    manifest = run(
        args.inventory,
        args.inventory_manifest,
        args.output,
        max(1, args.max_attempts),
        max(1, args.checkpoint_every),
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["decision"] == "PASS_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
