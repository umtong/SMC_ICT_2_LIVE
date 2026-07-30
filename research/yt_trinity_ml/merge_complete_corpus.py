#!/usr/bin/env python3
"""Merge the immutable 179-video base corpus with the resolved seven-video retry."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

EXPECTED_INVENTORY_SHA = "4524e2ec92cf05e7fc5dbc61b68c906b30dd4d4fedafa4b0bc861bcdbab604f2"
EXPECTED_COUNTS = {"chartbro": 62, "indicator_sensei": 98, "swipalnam": 26}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def digest_corpus(root: Path, videos_raw: bytes) -> str:
    digest = hashlib.sha256()
    digest.update(videos_raw)
    for path in sorted(item for item in (root / "transcripts").rglob("*") if item.is_file()):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(path.read_bytes())
    return digest.hexdigest()


def merge(base: Path, retry: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    base_manifest = json.loads((base / "manifest.json").read_text(encoding="utf-8"))
    retry_manifest = json.loads((retry / "manifest.json").read_text(encoding="utf-8"))
    if base_manifest.get("inventory_count") != 186:
        raise RuntimeError("base corpus inventory count is not 186")
    inventory = base_manifest.get("inventory") or {}
    if inventory.get("inventory_sha256") != EXPECTED_INVENTORY_SHA:
        raise RuntimeError("base corpus inventory digest mismatch")
    if retry_manifest.get("decision") != "PASS_ALL_SEVEN_RESOLVED":
        raise RuntimeError("retry corpus did not resolve all seven videos")
    if retry_manifest.get("source_corpus_digest_sha256") != base_manifest.get("corpus_digest_sha256"):
        raise RuntimeError("retry corpus is not bound to the selected base corpus")

    base_rows = {row["video_id"]: row for row in read_jsonl(base / "videos.jsonl")}
    retry_rows = {row["video_id"]: row for row in read_jsonl(retry / "videos.jsonl")}
    if len(base_rows) != 186 or len(retry_rows) != 7:
        raise RuntimeError(f"unexpected row counts base={len(base_rows)} retry={len(retry_rows)}")
    unresolved = {video_id for video_id, row in base_rows.items() if row.get("caption_status") != "ok"}
    if unresolved != set(retry_rows):
        raise RuntimeError(f"retry IDs do not exactly match unresolved base IDs: {sorted(unresolved ^ set(retry_rows))}")
    if any(row.get("caption_status") != "ok" for row in retry_rows.values()):
        raise RuntimeError("retry corpus still contains unresolved rows")

    shutil.copytree(base / "transcripts", output / "transcripts")
    for source in sorted((retry / "transcripts").rglob("*")):
        if source.is_file():
            destination = output / "transcripts" / source.relative_to(retry / "transcripts")
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)

    merged = dict(base_rows)
    merged.update(retry_rows)
    rows = [merged[key] for key in sorted(merged, key=lambda item: (merged[item]["channel_slug"], item))]
    if len(rows) != 186 or any(row.get("caption_status") != "ok" for row in rows):
        raise RuntimeError("merged corpus is not complete")
    counts = dict(sorted(Counter(row["channel_slug"] for row in rows).items()))
    if counts != EXPECTED_COUNTS:
        raise RuntimeError(f"channel counts mismatch: {counts}")
    for row in rows:
        for field in ("transcript_jsonl", "transcript_txt"):
            path = output / str(row[field])
            if not path.is_file() or path.stat().st_size == 0:
                raise RuntimeError(f"missing transcript file: {path}")

    videos_raw = "".join(canonical_json(row) + "\n" for row in rows).encode("utf-8")
    (output / "videos.jsonl").write_bytes(videos_raw)
    timing_counts = dict(sorted(Counter(str(row.get("caption_timing_quality")) for row in rows).items()))
    provider_counts = dict(sorted(Counter(str(row.get("caption_provider")) for row in rows).items()))
    manifest = {
        "schema_version": 2,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "decision": "PASS_COMPLETE",
        "built_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "inventory_count": 186,
        "inventory_sha256": EXPECTED_INVENTORY_SHA,
        "channel_counts": counts,
        "status_counts": {"ok": 186},
        "transcript_video_count": 186,
        "transcript_segment_count": sum(int(row.get("caption_segment_count") or 0) for row in rows),
        "transcript_character_count": sum(int(row.get("caption_character_count") or 0) for row in rows),
        "timing_quality_counts": timing_counts,
        "provider_counts": provider_counts,
        "base_corpus": {
            "run_id": base_manifest.get("run_id"),
            "corpus_digest_sha256": base_manifest.get("corpus_digest_sha256"),
            "videos_sha256": base_manifest.get("videos_sha256"),
        },
        "retry_corpus": {
            "run_id": retry_manifest.get("run_id"),
            "manifest_sha256": hashlib.sha256((retry / "manifest.json").read_bytes()).hexdigest(),
            "videos_sha256": retry_manifest.get("videos_sha256"),
        },
        "videos_sha256": hashlib.sha256(videos_raw).hexdigest(),
        "corpus_digest_sha256": digest_corpus(output, videos_raw),
        "known_limitations": [
            "179 transcripts use explicitly labelled proportional-duration evidence anchors rather than native timestamp precision",
            "7 retry transcripts use native-caption API timing",
            "corpus completeness does not by itself establish market profitability",
        ],
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--retry", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    manifest = merge(args.base, args.retry, args.output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
