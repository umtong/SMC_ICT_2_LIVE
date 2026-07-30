#!/usr/bin/env python3
"""Harvest one exact-inventory shard from a validated documented AI operation."""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

import requests

import harvest_public_frontend_content as common
import probe_ai_transcription_api_surface as probe


USER_AGENT = "SMC-ICT-2-LIVE/1.0"


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def load_winner(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    winner = payload.get("winner") if isinstance(payload, Mapping) else None
    operation = winner.get("operation") if isinstance(winner, Mapping) else None
    if not isinstance(operation, Mapping):
        raise RuntimeError("validated AI transcription operation is missing")
    if str(operation.get("method") or "").upper() not in {"GET", "POST"}:
        raise RuntimeError("invalid winning operation method")
    if not str(operation.get("url_template") or "").startswith("http"):
        raise RuntimeError("invalid winning operation URL")
    return {
        "operation": operation,
        "winner_sha256": sha256_bytes(path.read_bytes()),
        "winner_run_id": payload.get("run_id"),
        "winner_source_sha": payload.get("source_sha"),
    }


def find_timed_segments(payload: Any) -> list[dict[str, Any]]:
    candidates: list[list[dict[str, Any]]] = []

    def visit(value: Any) -> None:
        if isinstance(value, list):
            rows: list[dict[str, Any]] = []
            for index, item in enumerate(value):
                if not isinstance(item, Mapping):
                    continue
                text = item.get("text") or item.get("utf8") or item.get("caption") or item.get("sentence")
                start = item.get("start")
                if start is None:
                    for key in ("start_ms", "startTime", "start_time", "offset", "timestamp", "time"):
                        if item.get(key) is not None:
                            start = item.get(key)
                            break
                duration = item.get("duration")
                if duration is None:
                    for key in ("duration_ms", "durationMs", "end", "end_ms", "endTime", "end_time"):
                        if item.get(key) is not None:
                            duration = item.get(key)
                            break
                if text is None or start is None:
                    continue
                try:
                    start_value = float(start)
                except (TypeError, ValueError):
                    continue
                duration_value = 0.0
                try:
                    if duration is not None:
                        duration_value = float(duration)
                except (TypeError, ValueError):
                    duration_value = 0.0
                lowered_keys = {str(key).lower() for key in item}
                start_is_ms = any("ms" in key for key in lowered_keys if "start" in key) or start_value > 1_000_000
                if start_is_ms:
                    start_value /= 1000.0
                if any("duration_ms" in key or "durationms" in key for key in lowered_keys) or duration_value > 100_000:
                    duration_value /= 1000.0
                if any(key in lowered_keys for key in ("end", "end_ms", "endtime", "end_time")) and duration_value >= start_value:
                    duration_value = duration_value - start_value
                clean = " ".join(str(text).split())
                if clean:
                    rows.append({
                        "index": index,
                        "start": round(max(start_value, 0.0), 3),
                        "duration": round(max(duration_value, 0.0), 3),
                        "text": clean,
                    })
            if rows:
                rows.sort(key=lambda row: (row["start"], row["index"]))
                candidates.append(rows)
            for child in value[:300]:
                visit(child)
        elif isinstance(value, Mapping):
            for child in value.values():
                if isinstance(child, (list, Mapping)):
                    visit(child)

    visit(payload)
    candidates.sort(key=lambda rows: (len(rows), sum(len(row["text"]) for row in rows)), reverse=True)
    return candidates[0] if candidates else []


def request(session: requests.Session, method: str, url: str, body: Any):
    if method == "GET":
        return session.get(url, timeout=75, allow_redirects=True)
    return session.post(url, json=body, timeout=75, allow_redirects=True)


def fetch_video(contract: Mapping[str, Any], video_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    operation = contract["operation"]
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    attempts: list[dict[str, Any]] = []
    for method, url, body in probe.request_variants(operation, video_id):
        row: dict[str, Any] = {"method": method, "url": url, "body": body}
        try:
            response = request(session, method, url, body)
            row.update({
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "bytes": len(response.content),
            })
            try:
                payload = response.json()
            except Exception:
                payload = {"raw": response.text[:5000]}
            row["response_sha256"] = sha256_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
            segments = find_timed_segments(payload)
            if segments:
                row["segment_count"] = len(segments)
                attempts.append(row)
                return segments, {"attempts": attempts, "selected": row}
            poll_urls = probe.job_urls(payload, response.url)[:4]
            row["poll_url_count"] = len(poll_urls)
            for poll_url in poll_urls:
                for poll_index in range(60):
                    time.sleep(10.0)
                    polled = session.get(poll_url, timeout=75, allow_redirects=True)
                    try:
                        poll_payload = polled.json()
                    except Exception:
                        poll_payload = {"raw": polled.text[:5000]}
                    segments = find_timed_segments(poll_payload)
                    poll_row = {
                        "poll_url_sha256": sha256_bytes(poll_url.encode("utf-8")),
                        "poll": poll_index + 1,
                        "status_code": polled.status_code,
                        "segment_count": len(segments),
                    }
                    row.setdefault("polls", []).append(poll_row)
                    if segments:
                        row["segment_count"] = len(segments)
                        attempts.append(row)
                        return segments, {"attempts": attempts, "selected": row}
                    status_text = json.dumps(poll_payload, ensure_ascii=False).lower()
                    if any(token in status_text for token in ("failed", "error", "not found", "unavailable")):
                        break
            attempts.append(row)
        except Exception as exc:
            row["exception"] = f"{type(exc).__name__}: {exc}"
            attempts.append(row)
        time.sleep(1.0)
    return [], {"attempts": attempts}


def checkpoint(output: Path, rows: list[dict[str, Any]], contract: Mapping[str, Any], inventory_count: int) -> dict[str, Any]:
    raw = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows)
    (output / "videos.jsonl").write_text(raw, encoding="utf-8")
    counts = Counter(str(row.get("caption_status") or "") for row in rows)
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "provider": "validated_documented_public_ai_transcription_operation",
        "winner_sha256": contract["winner_sha256"],
        "winner_run_id": contract.get("winner_run_id"),
        "winner_source_sha": contract.get("winner_source_sha"),
        "operation": contract["operation"],
        "inventory_count": inventory_count,
        "completed_count": len(rows),
        "status_counts": dict(sorted(counts.items())),
        "transcript_segment_count": sum(int(row.get("caption_segment_count") or 0) for row in rows),
        "transcript_character_count": sum(int(row.get("caption_char_count") or 0) for row in rows),
        "videos_sha256": sha256_bytes(raw.encode("utf-8")),
        "updated_at_utc": utc_now(),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--winner", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--pace-seconds", type=float, default=6.4)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    contract = load_winner(args.winner)
    inventory = common.load_inventory(args.inventory, args.shard_index, args.shard_count)
    rows: list[dict[str, Any]] = []
    for position, item in enumerate(inventory, start=1):
        if position > 1:
            time.sleep(max(args.pace_seconds, 6.2))
        video_id = str(item["video_id"])
        channel = str(item["channel_slug"])
        row = {
            **item,
            "caption_status": "fetch_failed",
            "caption_provider": None,
            "caption_language_code": None,
            "caption_segment_count": 0,
            "caption_char_count": 0,
            "transcript_jsonl": None,
            "caption_sha256": None,
        }
        segments, detail = fetch_video(contract, video_id)
        row["attempt_detail"] = detail
        if segments:
            common_segments = [
                common.Segment(
                    start_ms=int(round(segment["start"] * 1000)),
                    duration_ms=int(round(segment["duration"] * 1000)),
                    text=segment["text"],
                )
                for segment in segments
            ]
            relative, digest = common.write_transcript(args.output, channel, video_id, common_segments)
            row.update({
                "caption_status": "ok",
                "caption_provider": "documented_public_ai_transcription_api",
                "caption_language_code": "ko",
                "caption_segment_count": len(common_segments),
                "caption_char_count": sum(len(segment.text) for segment in common_segments),
                "transcript_jsonl": relative,
                "caption_sha256": digest,
            })
        else:
            row["caption_error"] = "validated operation did not return timestamped transcript"
        rows.append(row)
        manifest = checkpoint(args.output, rows, contract, len(inventory))
        print(json.dumps({"position": position, "count": len(inventory), "video_id": video_id, "status": row["caption_status"], "segments": row["caption_segment_count"], "status_counts": manifest["status_counts"]}, ensure_ascii=False), flush=True)
    manifest = checkpoint(args.output, rows, contract, len(inventory))
    manifest["all_complete"] = len(rows) == len(inventory) and all(row.get("caption_status") == "ok" for row in rows)
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["all_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
