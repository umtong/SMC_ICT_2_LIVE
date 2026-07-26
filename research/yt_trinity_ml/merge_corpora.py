#!/usr/bin/env python3
"""Merge independently harvested channel caption corpora deterministically."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(canonical_json(value) + "\n")


def merge(inputs_root: Path, output: Path, config_path: Path) -> dict[str, Any]:
    config = read_json(config_path)
    expected = [row["slug"] for row in config["channels"]]
    output.mkdir(parents=True, exist_ok=True)
    all_videos: dict[str, dict[str, Any]] = {}
    all_attempts: list[dict[str, Any]] = []
    inventory_attempts: list[dict[str, Any]] = []
    channels: list[dict[str, Any]] = []
    source_manifests: dict[str, dict[str, Any]] = {}
    missing_channels: list[str] = []

    for slug in expected:
        source = inputs_root / slug
        manifest_path = source / "manifest.json"
        if not manifest_path.exists():
            missing_channels.append(slug)
            source_manifests[slug] = {"decision": "MISSING_CHANNEL_ARTIFACT"}
            continue
        manifest = read_json(manifest_path)
        source_manifests[slug] = {
            "decision": manifest.get("decision"),
            "inventory_complete": manifest.get("inventory_complete"),
            "caption_attempt_complete": manifest.get("caption_attempt_complete"),
            "unique_public_video_count": manifest.get("unique_public_video_count"),
            "corpus_digest_sha256": manifest.get("corpus_digest_sha256"),
            "manifest_sha256": sha256_bytes(manifest_path.read_bytes()),
        }
        source_channels = read_json(source / "channels.json") if (source / "channels.json").exists() else []
        channels.extend(row for row in source_channels if isinstance(row, dict))
        for row in read_jsonl(source / "videos.jsonl"):
            video_id = str(row.get("video_id") or "")
            if not video_id:
                continue
            previous = all_videos.get(video_id)
            if previous is not None and canonical_json(previous) != canonical_json(row):
                raise RuntimeError(f"conflicting duplicate video ID: {video_id}")
            all_videos[video_id] = row
        all_attempts.extend(read_jsonl(source / "caption_attempts.jsonl"))
        inventory_attempts.extend(read_jsonl(source / "inventory_attempts.jsonl"))
        transcript_root = source / "transcripts"
        if transcript_root.exists():
            for item in transcript_root.rglob("*"):
                if item.is_file():
                    destination = output / "transcripts" / item.relative_to(transcript_root)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists() and destination.read_bytes() != item.read_bytes():
                        raise RuntimeError(f"conflicting transcript: {destination}")
                    shutil.copy2(item, destination)

    videos = sorted(
        all_videos.values(),
        key=lambda row: (str(row.get("channel_slug")), str(row.get("upload_date") or ""), str(row.get("video_id"))),
    )
    all_attempts.sort(key=lambda row: (str(row.get("channel_slug")), str(row.get("video_id")), str(row.get("provider")), int(row.get("attempt") or 0)))
    inventory_attempts.sort(key=lambda row: (str(row.get("channel_slug")), str(row.get("method"))))
    channels.sort(key=lambda row: str(row.get("slug")))
    write_jsonl(output / "videos.jsonl", videos)
    write_jsonl(output / "caption_attempts.jsonl", all_attempts)
    write_jsonl(output / "inventory_attempts.jsonl", inventory_attempts)
    write_json(output / "channels.json", channels)

    statuses = Counter(str(row.get("caption_status") or "") for row in videos)
    statuses.pop("", None)
    providers = Counter(str(row.get("caption_provider") or "") for row in videos if row.get("caption_status") == "ok")
    providers.pop("", None)
    languages = Counter(str(row.get("caption_language_code") or "") for row in videos if row.get("caption_status") == "ok")
    languages.pop("", None)
    resolved = sum(statuses.get(name, 0) for name in ("ok", "no_caption", "unavailable"))
    channel_by_slug = {str(row.get("slug")): row for row in channels}
    inventory_complete = not missing_channels and all(
        slug in channel_by_slug and bool(channel_by_slug[slug].get("inventory_complete"))
        for slug in expected
    )
    caption_complete = (
        not missing_channels
        and statuses.get("fetch_failed", 0) == 0
        and statuses.get("pending", 0) == 0
        and resolved == len(videos)
        and all(source_manifests[slug].get("caption_attempt_complete") for slug in expected)
    )
    canonical_rows = [
        {
            "video_id": row["video_id"],
            "channel_slug": row["channel_slug"],
            "caption_status": row.get("caption_status"),
            "caption_sha256": row.get("caption_sha256"),
            "title": row.get("title"),
            "upload_date": row.get("upload_date"),
        }
        for row in videos
    ]
    manifest = {
        "schema_version": 2,
        "work_claim_id": config.get("work_claim_id"),
        "snapshot_as_of_utc": config.get("snapshot_as_of_utc"),
        "config_sha256": sha256_bytes(config_path.read_bytes()),
        "inventory_complete": inventory_complete,
        "caption_attempt_complete": caption_complete,
        "decision": "PASS_COMPLETE" if inventory_complete and caption_complete else "PARTIAL_REQUIRES_RETRY",
        "expected_channel_slugs": expected,
        "missing_channel_slugs": missing_channels,
        "channel_count": len(channels),
        "unique_public_video_count": len(videos),
        "caption_status_counts": dict(sorted(statuses.items())),
        "caption_provider_counts": dict(sorted(providers.items())),
        "caption_language_counts": dict(sorted(languages.items())),
        "total_caption_segments": sum(int(row.get("caption_segment_count") or 0) for row in videos),
        "total_caption_characters": sum(int(row.get("caption_char_count") or 0) for row in videos),
        "corpus_digest_sha256": sha256_text(canonical_json(canonical_rows)),
        "source_channel_manifests": source_manifests,
        "channels": channels,
    }
    write_json(output / "manifest.json", manifest)
    hashes: list[tuple[str, str]] = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS":
            hashes.append((sha256_bytes(path.read_bytes()), str(path.relative_to(output))))
    (output / "SHA256SUMS").write_text(
        "".join(f"{digest}  {relative}\n" for digest, relative in hashes),
        encoding="utf-8",
        newline="\n",
    )
    return manifest


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inputs-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args(argv)
    result = merge(args.inputs_root, args.output, args.config)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
