#!/usr/bin/env python3
"""Build the exact union of public uploads, videos, shorts, and archived streams."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

VERIFIED_CHANNEL_IDS = {
    "swipalnam": "UCBltgdQdT3h004d5cTw-EhQ",
    "chartbro": "UCE6gcmTBZYm-QLisjUjXYKA",
    "indicator_sensei": "UCEeQbR5tgf-ogqhxRQHMlQQ",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def iter_entries(value: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        entries = value.get("entries")
        if entries is not None:
            for item in entries:
                yield from iter_entries(item)
        elif value.get("id"):
            yield value
    elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
        for item in value:
            yield from iter_entries(item)


def load_url(url: str) -> tuple[list[dict[str, Any]], str]:
    import yt_dlp  # type: ignore

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "lazy_playlist": False,
        "socket_timeout": 45,
        "retries": 3,
        "extractor_retries": 3,
        "cachedir": False,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    title = str(info.get("title") or "") if isinstance(info, Mapping) else ""
    rows: list[dict[str, Any]] = []
    for entry in iter_entries(info):
        video_id = str(entry.get("id") or "")
        if len(video_id) != 11:
            continue
        duration = entry.get("duration")
        try:
            duration_s = float(duration) if duration not in (None, "") else None
        except (TypeError, ValueError):
            duration_s = None
        rows.append({
            "video_id": video_id,
            "title": str(entry.get("title") or ""),
            "duration_s": duration_s,
            "upload_date": str(entry.get("upload_date") or ""),
            "timestamp": entry.get("timestamp"),
            "live_status": str(entry.get("live_status") or ""),
            "availability": str(entry.get("availability") or ""),
            "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        })
    return rows, title


def merge(target: dict[str, Any], incoming: Mapping[str, Any], source: str, tab: str | None) -> None:
    for key, value in incoming.items():
        if target.get(key) in (None, "", 0) and value not in (None, "", 0):
            target[key] = value
    target.setdefault("inventory_sources", [])
    if source not in target["inventory_sources"]:
        target["inventory_sources"].append(source)
    target.setdefault("source_tabs", [])
    if tab and tab not in target["source_tabs"]:
        target["source_tabs"].append(tab)


def main() -> int:
    root = Path(__file__).resolve().parent
    config_path = root / "channels.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    all_rows: list[dict[str, Any]] = []
    channel_manifest: list[dict[str, Any]] = []

    for channel in config["channels"]:
        slug = channel["slug"]
        channel_id = VERIFIED_CHANNEL_IDS[slug]
        expected = channel.get("expected_channel_id")
        if expected and expected != channel_id:
            raise RuntimeError(f"channel identity mismatch for {slug}: {expected} != {channel_id}")
        uploads_id = "UU" + channel_id[2:]
        sources = [
            ("uploads", f"https://www.youtube.com/playlist?list={uploads_id}", None),
            ("videos", f"https://www.youtube.com/channel/{channel_id}/videos", "videos"),
            ("shorts", f"https://www.youtube.com/channel/{channel_id}/shorts", "shorts"),
            ("streams", f"https://www.youtube.com/channel/{channel_id}/streams", "streams"),
        ]
        by_id: dict[str, dict[str, Any]] = {}
        source_counts: dict[str, int] = {}
        source_titles: dict[str, str] = {}
        for source_name, url, tab in sources:
            rows, title = load_url(url)
            source_counts[source_name] = len(rows)
            source_titles[source_name] = title
            for row in rows:
                target = by_id.setdefault(row["video_id"], {
                    "channel_slug": slug,
                    "channel_display_name": channel["display_name"],
                    "channel_id": channel_id,
                    "video_id": row["video_id"],
                })
                merge(target, row, source_name, tab)
        if not by_id:
            raise RuntimeError(f"empty public inventory for {slug}")
        tab_only = sorted(video_id for video_id, row in by_id.items() if "uploads" not in row["inventory_sources"])
        rows = sorted(by_id.values(), key=lambda row: row["video_id"])
        all_rows.extend(rows)
        channel_manifest.append({
            "slug": slug,
            "display_name": channel["display_name"],
            "channel_id": channel_id,
            "source_counts": source_counts,
            "source_titles": source_titles,
            "union_count": len(rows),
            "tab_only_count": len(tab_only),
            "tab_only_video_ids": tab_only,
        })

    all_rows.sort(key=lambda row: (row["channel_slug"], row["video_id"]))
    ids = [row["video_id"] for row in all_rows]
    if len(ids) != len(set(ids)):
        duplicates = [video_id for video_id, count in Counter(ids).items() if count > 1]
        raise RuntimeError(f"cross-channel duplicate video ids: {duplicates}")
    raw = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in all_rows)
    output = root / "PUBLIC_VIDEO_INVENTORY_UNION.jsonl"
    output.write_text(raw, encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "work_claim_id": config["work_claim_id"],
        "built_at_utc": utc_now(),
        "config_sha256": hashlib.sha256(config_path.read_bytes()).hexdigest(),
        "inventory_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "total_unique_public_videos": len(all_rows),
        "channels": channel_manifest,
    }
    (root / "PUBLIC_VIDEO_INVENTORY_UNION_MANIFEST.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
