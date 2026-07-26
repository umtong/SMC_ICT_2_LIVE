#!/usr/bin/env python3
"""Merge rate-safe transcript shards against the exact public-video inventory."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

RESOLVED = {"ok", "verified_no_caption", "unavailable"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--shards-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()

    inventory = [json.loads(line) for line in args.inventory.read_text(encoding="utf-8").splitlines() if line.strip()]
    expected = {row["video_id"]: row for row in inventory}
    outcomes: dict[str, dict] = {}
    args.output.mkdir(parents=True, exist_ok=True)
    transcript_root = args.output / "transcripts"
    transcript_root.mkdir(parents=True, exist_ok=True)
    shard_manifests: list[dict] = []

    for videos_path in sorted(args.shards_root.rglob("videos.jsonl")):
        root = videos_path.parent
        manifest_path = root / "manifest.json"
        if manifest_path.exists():
            shard_manifests.append(json.loads(manifest_path.read_text(encoding="utf-8")))
        for line in videos_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            video_id = row["video_id"]
            if video_id in outcomes:
                raise RuntimeError(f"duplicate shard outcome for {video_id}")
            outcomes[video_id] = row
        source = root / "transcripts"
        if source.exists():
            for file in source.rglob("*"):
                if file.is_file():
                    destination = transcript_root / file.relative_to(source)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(file, destination)

    extra = sorted(set(outcomes) - set(expected))
    if extra:
        raise RuntimeError(f"unexpected shard outcomes: {extra}")
    for video_id in sorted(set(expected) - set(outcomes)):
        outcomes[video_id] = {
            **expected[video_id],
            "caption_status": "retry_required",
            "caption_error": "missing shard outcome",
            "caption_segment_count": 0,
            "caption_character_count": 0,
        }

    rows = [
        outcomes[row["video_id"]]
        for row in sorted(inventory, key=lambda item: (item["channel_slug"], item["video_id"]))
    ]
    videos_raw = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    (args.output / "videos.jsonl").write_text(videos_raw, encoding="utf-8")
    counts = Counter(row.get("caption_status") for row in rows)
    channel_counts = {
        channel: dict(
            sorted(Counter(row.get("caption_status") for row in rows if row["channel_slug"] == channel).items())
        )
        for channel in sorted({row["channel_slug"] for row in rows})
    }
    all_resolved = all(row.get("caption_status") in RESOLVED for row in rows)
    manifest = {
        "schema_version": 2,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "provider": "api.youtubetotext.com/full_transcript",
        "run_id": int(args.run_id),
        "source_sha": args.source_sha,
        "built_at_utc": utc_now(),
        "inventory_count": len(inventory),
        "inventory_sha256": hashlib.sha256(args.inventory.read_bytes()).hexdigest(),
        "status_counts": dict(sorted(counts.items())),
        "channel_status_counts": channel_counts,
        "caption_attempt_complete": all_resolved,
        "decision": "PASS_NATIVE_CAPTION_CLASSIFICATION" if all_resolved else "PARTIAL_REQUIRES_RETRY",
        "transcript_video_count": counts.get("ok", 0),
        "verified_no_caption_count": counts.get("verified_no_caption", 0),
        "unavailable_count": counts.get("unavailable", 0),
        "retry_required_count": counts.get("retry_required", 0),
        "transcript_segment_count": sum(int(row.get("caption_segment_count") or 0) for row in rows),
        "transcript_character_count": sum(int(row.get("caption_character_count") or 0) for row in rows),
        "videos_sha256": hashlib.sha256(videos_raw.encode("utf-8")).hexdigest(),
        "shard_manifests": shard_manifests,
    }
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all_resolved else 2


if __name__ == "__main__":
    raise SystemExit(main())
