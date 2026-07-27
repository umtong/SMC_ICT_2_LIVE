#!/usr/bin/env python3
"""Select one immutable complete content corpus from independent transports."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping


POINTERS = (
    "COMPLETE_CONTENT_CORPUS_POINTER.json",
    "COBALT_CONTENT_CORPUS_POINTER.json",
    "FULL_CAPTION_CORPUS_POINTER.json",
)


def quality(pointer: Mapping[str, Any]) -> tuple[int, int, int, int, int]:
    manifest = pointer["manifest"]
    providers = manifest.get("caption_provider_counts") or manifest.get("provider_counts") or {}
    native = 0
    asr = 0
    if isinstance(providers, Mapping):
        for name, count in providers.items():
            value = int(count or 0)
            lowered = str(name).lower()
            if "whisper" in lowered or "asr" in lowered or "transient_audio" in lowered:
                asr += value
            else:
                native += value
    total = int(
        manifest.get("unique_public_video_count")
        or manifest.get("inventory_count")
        or manifest.get("transcript_video_count")
        or 0
    )
    characters = int(
        manifest.get("total_caption_characters")
        or manifest.get("transcript_character_count")
        or 0
    )
    segments = int(
        manifest.get("total_caption_segments")
        or manifest.get("transcript_segment_count")
        or 0
    )
    # Every candidate is complete. Prefer native captions, then total coverage and
    # text mass; ASR count is only a tie-breaker because some videos have no native track.
    return native, total, characters, segments, -asr


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for filename in POINTERS:
        path = args.root / filename
        if not path.exists():
            rejected.append({"pointer_file": filename, "reason": "missing"})
            continue
        try:
            pointer = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            rejected.append({"pointer_file": filename, "reason": f"invalid_json:{type(exc).__name__}"})
            continue
        manifest = pointer.get("manifest")
        decision = manifest.get("decision") if isinstance(manifest, Mapping) else None
        complete = (
            isinstance(manifest, Mapping)
            and decision in {"PASS_COMPLETE", "PASS_NATIVE_CAPTION_CLASSIFICATION"}
            and bool(
                manifest.get("content_attempt_complete")
                or manifest.get("caption_attempt_complete")
            )
            and pointer.get("run_id")
            and pointer.get("artifact_name")
        )
        if not complete:
            rejected.append(
                {
                    "pointer_file": filename,
                    "reason": "not_complete",
                    "manifest_decision": decision,
                }
            )
            continue
        row = {
            "pointer_file": filename,
            "pointer_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "run_id": int(pointer["run_id"]),
            "source_sha": pointer.get("source_sha"),
            "artifact_name": pointer.get("artifact_name"),
            "manifest": manifest,
            "manifest_sha256": pointer.get("manifest_sha256"),
            "rule_ontology_sha256": pointer.get("rule_ontology_sha256"),
            "quality_key": list(quality(pointer)),
        }
        candidates.append(row)
    candidates.sort(key=lambda row: tuple(row["quality_key"]), reverse=True)
    selected = candidates[0] if candidates else None
    payload = {
        "schema_version": 1,
        "decision": "COMPLETE_CONTENT_AUTHORITY_SELECTED" if selected else "NO_COMPLETE_CONTENT_AUTHORITY",
        "selected": selected,
        "alternatives": candidates[1:] if candidates else [],
        "rejected": rejected,
        "rankable": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
