#!/usr/bin/env python3
"""Harvest a complete native-timestamped corpus through public caption frontends.

The harvester first validates public Piped/Invidious instances against a known positive
control, then processes the immutable three-channel inventory sequentially with a fixed
pace. It never treats a transport failure as no-caption. A video is classified as
``asr_required`` only when at least two working frontend responses agree that the video
is playable but exposes no caption tracks. Transcript payloads remain native-timestamped;
plain-text or estimated timing is not introduced by this lane.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

from probe_alt_caption_frontends import (
    INVIDIOUS_INSTANCE_INDEX,
    PIPED_INSTANCES,
    Segment,
    canonical_json,
    invidious_instances,
    probe_invidious_instance,
    probe_piped_instance,
    sha256_bytes,
)

POSITIVE_CONTROL_VIDEO_ID = "F6wDs1HRTSo"
CHANNEL_DISPLAY = {
    "swipalnam": "쉽알남",
    "chartbro": "차트브로",
    "indicator_sensei": "지표센세",
}
USER_AGENT = "SMC-ICT-2-LIVE-native-caption-corpus/1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_inventory(path: Path) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda row: (str(row.get("channel_slug")), str(row.get("video_id"))))
    if not rows:
        raise RuntimeError("inventory is empty")
    ids = [str(row.get("video_id")) for row in rows]
    if any(len(video_id) != 11 for video_id in ids):
        raise RuntimeError("inventory contains malformed video IDs")
    if len(ids) != len(set(ids)):
        raise RuntimeError("inventory contains duplicate video IDs")
    return rows


def select_inventory(
    rows: Sequence[dict[str, Any]],
    channel: str | None,
    video_ids: set[str],
    maximum: int | None,
) -> list[dict[str, Any]]:
    selected = [row for row in rows if channel is None or row.get("channel_slug") == channel]
    if video_ids:
        selected = [row for row in selected if str(row.get("video_id")) in video_ids]
    if maximum is not None:
        selected = selected[: max(maximum, 0)]
    if not selected:
        raise RuntimeError("inventory selection is empty")
    return selected


def bounded_evidence(row: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "provider",
        "instance",
        "http_status",
        "bytes",
        "content_type",
        "track_count",
        "audio_stream_count",
        "title",
        "segment_count",
        "character_count",
        "text_sha256",
        "language_code",
        "auto_generated",
        "error",
        "track_errors",
        "elapsed_seconds",
    )
    return {key: row.get(key) for key in keys if row.get(key) is not None}


def pop_segments(row: dict[str, Any]) -> list[Segment]:
    raw = row.pop("segments", [])
    return [
        value if isinstance(value, Segment) else Segment(int(value["start_ms"]), int(value["duration_ms"]), str(value["text"]))
        for value in raw
    ]


def validate_instances(
    session: requests.Session,
    timeout: float,
    pace_seconds: float,
    max_piped: int,
    max_invidious: int,
    desired_per_provider: int,
) -> tuple[list[tuple[str, str]], dict[str, Any]]:
    selected: list[tuple[str, str]] = []
    evidence: dict[str, Any] = {
        "positive_control_video_id": POSITIVE_CONTROL_VIDEO_ID,
        "piped_attempts": [],
        "invidious_attempts": [],
        "invidious_instance_index": {},
    }

    for base in PIPED_INSTANCES[: max(max_piped, 0)]:
        if evidence["piped_attempts"] and pace_seconds > 0:
            time.sleep(pace_seconds)
        row = probe_piped_instance(session, base, POSITIVE_CONTROL_VIDEO_ID, timeout)
        segments = pop_segments(row)
        evidence["piped_attempts"].append(bounded_evidence(row))
        if segments:
            selected.append(("piped", base))
            if sum(provider == "piped" for provider, _ in selected) >= desired_per_provider:
                break

    dynamic, index_evidence = invidious_instances(session, timeout, max(max_invidious, 0))
    evidence["invidious_instance_index"] = index_evidence
    for base in dynamic:
        if evidence["invidious_attempts"] and pace_seconds > 0:
            time.sleep(pace_seconds)
        row = probe_invidious_instance(session, base, POSITIVE_CONTROL_VIDEO_ID, timeout)
        segments = pop_segments(row)
        evidence["invidious_attempts"].append(bounded_evidence(row))
        if segments:
            selected.append(("invidious", base))
            if sum(provider == "invidious" for provider, _ in selected) >= desired_per_provider:
                break

    # Deduplicate while preserving provider diversity and discovery order.
    unique: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in selected:
        if item not in seen:
            unique.append(item)
            seen.add(item)
    evidence["selected_instances"] = [
        {"provider": provider, "instance": base} for provider, base in unique
    ]
    evidence["selected_count"] = len(unique)
    evidence["positive_control_passed"] = bool(unique)
    return unique, evidence


def probe_instance(
    session: requests.Session,
    provider: str,
    base: str,
    video_id: str,
    timeout: float,
) -> tuple[dict[str, Any], list[Segment]]:
    if provider == "piped":
        row = probe_piped_instance(session, base, video_id, timeout)
    elif provider == "invidious":
        row = probe_invidious_instance(session, base, video_id, timeout)
    else:
        raise ValueError(f"unsupported provider: {provider}")
    segments = pop_segments(row)
    return row, segments


def classify_attempts(attempts: Sequence[Mapping[str, Any]]) -> str:
    working = [row for row in attempts if int(row.get("http_status") or 0) == 200]
    playable_no_caption = [
        row
        for row in working
        if int(row.get("audio_stream_count") or 0) > 0 and int(row.get("track_count") or 0) == 0
    ]
    providers = {str(row.get("provider")) for row in playable_no_caption}
    instances = {str(row.get("instance")) for row in playable_no_caption}
    if len(instances) >= 2 or len(providers) >= 2:
        return "asr_required"
    not_found = [row for row in attempts if int(row.get("http_status") or 0) in {404, 410}]
    if len(not_found) == len(attempts) and attempts:
        return "unavailable"
    return "retry_required"


def transcript_paths(channel: str, video_id: str) -> tuple[str, str]:
    return f"transcripts/{channel}/{video_id}.jsonl", f"transcripts/{channel}/{video_id}.txt"


def write_transcript(output: Path, channel: str, video_id: str, segments: Sequence[Segment]) -> tuple[str, str, int, str]:
    jsonl_path, text_path = transcript_paths(channel, video_id)
    destination_jsonl = output / jsonl_path
    destination_text = output / text_path
    destination_jsonl.parent.mkdir(parents=True, exist_ok=True)
    raw_jsonl = "".join(canonical_json({
        "start_ms": int(segment.start_ms),
        "duration_ms": int(segment.duration_ms),
        "text": str(segment.text),
        "timing_quality": "native_caption",
    }) + "\n" for segment in segments)
    text = " ".join(str(segment.text).strip() for segment in segments if str(segment.text).strip())
    destination_jsonl.write_text(raw_jsonl, encoding="utf-8")
    destination_text.write_text(text + "\n", encoding="utf-8")
    return jsonl_path, text_path, len(text), sha256_bytes(raw_jsonl.encode("utf-8"))


def harvest_video(
    session: requests.Session,
    item: Mapping[str, Any],
    instances: Sequence[tuple[str, str]],
    timeout: float,
    pace_seconds: float,
    output: Path,
) -> dict[str, Any]:
    video_id = str(item["video_id"])
    channel = str(item["channel_slug"])
    attempts: list[dict[str, Any]] = []
    for index, (provider, base) in enumerate(instances):
        if index and pace_seconds > 0:
            time.sleep(pace_seconds)
        row, segments = probe_instance(session, provider, base, video_id, timeout)
        row["provider"] = provider
        row["instance"] = base
        attempts.append(bounded_evidence(row))
        if segments:
            jsonl_path, text_path, character_count, transcript_sha = write_transcript(
                output, channel, video_id, segments
            )
            return {
                **dict(item),
                "channel_display_name": CHANNEL_DISPLAY.get(channel, channel),
                "caption_status": "ok",
                "caption_provider": provider,
                "caption_instance": base,
                "caption_language_code": row.get("language_code"),
                "caption_auto_generated": row.get("auto_generated"),
                "caption_timing_quality": "native_caption",
                "caption_segment_count": len(segments),
                "caption_character_count": character_count,
                "caption_text_sha256": row.get("text_sha256"),
                "transcript_sha256": transcript_sha,
                "transcript_jsonl": jsonl_path,
                "transcript_txt": text_path,
                "transport_attempts": attempts,
            }

    status = classify_attempts(attempts)
    return {
        **dict(item),
        "channel_display_name": CHANNEL_DISPLAY.get(channel, channel),
        "caption_status": status,
        "caption_provider": None,
        "caption_timing_quality": None,
        "caption_segment_count": 0,
        "caption_character_count": 0,
        "caption_error": (
            "playable video exposes no native caption tracks on independent working frontends"
            if status == "asr_required"
            else "video unavailable on all validated frontends"
            if status == "unavailable"
            else "validated frontends did not produce a conclusive caption outcome"
        ),
        "transport_attempts": attempts,
    }


def corpus_digest(output: Path, videos_raw: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(videos_raw)
    transcript_root = output / "transcripts"
    if transcript_root.exists():
        for path in sorted(candidate for candidate in transcript_root.rglob("*") if candidate.is_file()):
            digest.update(path.relative_to(output).as_posix().encode("utf-8"))
            digest.update(path.read_bytes())
    return digest.hexdigest()


def build_manifest(
    output: Path,
    inventory_path: Path,
    inventory_rows: Sequence[Mapping[str, Any]],
    selected_rows: Sequence[Mapping[str, Any]],
    outcomes: Sequence[Mapping[str, Any]],
    validation: Mapping[str, Any],
) -> dict[str, Any]:
    videos_raw = "".join(canonical_json(row) + "\n" for row in outcomes).encode("utf-8")
    (output / "videos.jsonl").write_bytes(videos_raw)
    counts = Counter(str(row.get("caption_status")) for row in outcomes)
    channel_counts: dict[str, dict[str, int]] = {}
    for channel in sorted({str(row.get("channel_slug")) for row in outcomes}):
        channel_counts[channel] = dict(sorted(Counter(
            str(row.get("caption_status")) for row in outcomes if row.get("channel_slug") == channel
        ).items()))
    resolved = {"ok", "asr_required", "unavailable"}
    classification_complete = all(str(row.get("caption_status")) in resolved for row in outcomes)
    content_complete = all(str(row.get("caption_status")) in {"ok", "unavailable"} for row in outcomes)
    if content_complete:
        decision = "PASS_COMPLETE_NATIVE_CAPTION_TEXT"
    elif classification_complete:
        decision = "PARTIAL_ASR_REQUIRED"
    else:
        decision = "PARTIAL_REQUIRES_RETRY"
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "provider_lane": "public_piped_invidious_native_caption_apis",
        "built_at_utc": utc_now(),
        "source_sha": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "inventory_path": str(inventory_path),
        "inventory_count": len(inventory_rows),
        "inventory_sha256": sha256_bytes(inventory_path.read_bytes()),
        "selected_count": len(selected_rows),
        "outcome_count": len(outcomes),
        "status_counts": dict(sorted(counts.items())),
        "channel_status_counts": channel_counts,
        "caption_classification_complete": classification_complete,
        "transcript_content_complete": content_complete,
        "decision": decision,
        "transcript_video_count": counts.get("ok", 0),
        "asr_required_count": counts.get("asr_required", 0),
        "unavailable_count": counts.get("unavailable", 0),
        "retry_required_count": counts.get("retry_required", 0),
        "transcript_segment_count": sum(int(row.get("caption_segment_count") or 0) for row in outcomes),
        "transcript_character_count": sum(int(row.get("caption_character_count") or 0) for row in outcomes),
        "videos_sha256": sha256_bytes(videos_raw),
        "corpus_digest_sha256": corpus_digest(output, videos_raw),
        "instance_validation": dict(validation),
        "native_timing_only": True,
        "known_limitations": [
            "public frontend availability may change after this immutable run",
            "asr_required means no native caption was exposed by at least two validated frontends",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def self_test() -> None:
    rows = [
        {"provider": "piped", "instance": "a", "http_status": 200, "audio_stream_count": 2, "track_count": 0},
        {"provider": "piped", "instance": "b", "http_status": 200, "audio_stream_count": 1, "track_count": 0},
    ]
    assert classify_attempts(rows) == "asr_required"
    assert classify_attempts([{"http_status": 404}, {"http_status": 404}]) == "unavailable"
    assert classify_attempts([{"http_status": 500}, {"http_status": 200, "track_count": 1}]) == "retry_required"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--channel", choices=sorted(CHANNEL_DISPLAY))
    parser.add_argument("--video-id", action="append", default=[])
    parser.add_argument("--max-videos", type=int)
    parser.add_argument("--timeout-seconds", type=float, default=35.0)
    parser.add_argument("--pace-seconds", type=float, default=1.0)
    parser.add_argument("--max-piped-instances", type=int, default=15)
    parser.add_argument("--max-invidious-instances", type=int, default=15)
    parser.add_argument("--desired-instances-per-provider", type=int, default=2)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        print("native caption harvester self-test: ok")
        return 0
    if args.inventory is None or args.output is None:
        parser.error("--inventory and --output are required unless --self-test is used")

    inventory = load_inventory(args.inventory)
    selected = select_inventory(inventory, args.channel, set(args.video_id), args.max_videos)
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5",
    })
    try:
        instances, validation = validate_instances(
            session,
            args.timeout_seconds,
            max(args.pace_seconds, 0.0),
            args.max_piped_instances,
            args.max_invidious_instances,
            max(args.desired_instances_per_provider, 1),
        )
        if not instances:
            raise RuntimeError(
                "no public frontend passed the known positive-caption control; "
                f"index={INVIDIOUS_INSTANCE_INDEX} evidence={canonical_json(validation)}"
            )
        outcomes: list[dict[str, Any]] = []
        for index, item in enumerate(selected):
            if index and args.pace_seconds > 0:
                time.sleep(args.pace_seconds)
            row = harvest_video(
                session,
                item,
                instances,
                args.timeout_seconds,
                max(args.pace_seconds, 0.0),
                args.output,
            )
            outcomes.append(row)
            print(canonical_json({
                "position": index + 1,
                "total": len(selected),
                "channel_slug": row.get("channel_slug"),
                "video_id": row.get("video_id"),
                "caption_status": row.get("caption_status"),
                "caption_segment_count": row.get("caption_segment_count"),
                "caption_character_count": row.get("caption_character_count"),
            }), flush=True)
    finally:
        session.close()

    manifest = build_manifest(args.output, args.inventory, inventory, selected, outcomes, validation)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
