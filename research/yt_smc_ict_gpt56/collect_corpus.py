from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import html
import json
import random
import re
import sys
import time
import traceback
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import requests
import yt_dlp


CHANNELS: tuple[dict[str, str], ...] = (
    {
        "channel_key": "easy_chart_man",
        "display_name": "쉽알남",
        "url": "https://www.youtube.com/@%EC%89%BD.%EC%95%8C.%EB%82%A8",
    },
    {
        "channel_key": "chartbro",
        "display_name": "차트브로",
        "url": "https://www.youtube.com/@chartbro",
    },
    {
        "channel_key": "indicator_sensei",
        "display_name": "지표센세",
        "url": "https://www.youtube.com/channel/UCEeQbR5tgf-ogqhxRQHMlQQ",
    },
)

TAB_NAMES: tuple[str, ...] = ("videos", "shorts", "streams")
LANG_PRIORITY: tuple[str, ...] = (
    "ko",
    "ko-KR",
    "ko-orig",
    "ko-en",
    "en",
    "en-US",
    "en-orig",
)
FORMAT_PRIORITY: tuple[str, ...] = ("json3", "srv3", "srv2", "srv1", "vtt", "ttml")


@dataclass
class VideoRecord:
    channel_key: str
    channel_name: str
    video_id: str
    title: str
    webpage_url: str
    tabs: list[str] = field(default_factory=list)
    duration_seconds: float | None = None
    upload_date: str | None = None
    timestamp: int | None = None
    live_status: str | None = None
    availability: str | None = None
    view_count: int | None = None
    description: str | None = None
    transcript_status: str = "pending"
    transcript_source: str | None = None
    transcript_language: str | None = None
    transcript_kind: str | None = None
    transcript_segments: int = 0
    transcript_characters: int = 0
    transcript_sha256: str | None = None
    transcript_path: str | None = None
    error: str | None = None


class QuietLogger:
    def debug(self, msg: str) -> None:
        if msg.startswith("[debug]"):
            return

    def warning(self, msg: str) -> None:
        print(f"yt-dlp warning: {msg}", file=sys.stderr)

    def error(self, msg: str) -> None:
        print(f"yt-dlp error: {msg}", file=sys.stderr)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_text(text: str) -> str:
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = text.replace("\u200b", " ").replace("\ufeff", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def canonical_video_id(entry: dict[str, Any]) -> str | None:
    raw = entry.get("id") or entry.get("url")
    if not raw:
        return None
    raw = str(raw)
    match = re.search(r"(?:v=|/shorts/|/live/|youtu\.be/)([A-Za-z0-9_-]{11})", raw)
    if match:
        return match.group(1)
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", raw):
        return raw
    return None


def walk_entries(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        entries = value.get("entries")
        if isinstance(entries, list):
            for item in entries:
                if item is None:
                    continue
                yield from walk_entries(item)
            return
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from walk_entries(item)


def ydl_base_opts() -> dict[str, Any]:
    return {
        "quiet": True,
        "no_warnings": False,
        "ignoreerrors": True,
        "skip_download": True,
        "socket_timeout": 30,
        "retries": 5,
        "fragment_retries": 5,
        "extractor_retries": 5,
        "logger": QuietLogger(),
        "extractor_args": {
            "youtube": {
                "player_client": ["android", "web", "ios"],
                "player_skip": ["configs"],
            }
        },
        "http_headers": {
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.5",
        },
    }


def enumerate_tab(channel: dict[str, str], tab: str) -> list[VideoRecord]:
    url = f"{channel['url'].rstrip('/')}/{tab}"
    opts = {
        **ydl_base_opts(),
        "extract_flat": "in_playlist",
        "lazy_playlist": False,
        "playlistreverse": False,
    }
    print(f"[{utc_now()}] enumerate {channel['display_name']} {tab}: {url}", flush=True)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        return []
    records: list[VideoRecord] = []
    for entry in walk_entries(info):
        video_id = canonical_video_id(entry)
        if not video_id:
            continue
        title = str(entry.get("title") or entry.get("fulltitle") or video_id)
        webpage_url = str(entry.get("webpage_url") or f"https://www.youtube.com/watch?v={video_id}")
        record = VideoRecord(
            channel_key=channel["channel_key"],
            channel_name=channel["display_name"],
            video_id=video_id,
            title=title,
            webpage_url=webpage_url,
            tabs=[tab],
            duration_seconds=_as_float(entry.get("duration")),
            upload_date=_as_str(entry.get("upload_date")),
            timestamp=_as_int(entry.get("timestamp")),
            live_status=_as_str(entry.get("live_status")),
            availability=_as_str(entry.get("availability")),
            view_count=_as_int(entry.get("view_count")),
            description=_as_str(entry.get("description")),
        )
        records.append(record)
    return records


def _as_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def merge_records(records: Iterable[VideoRecord]) -> list[VideoRecord]:
    merged: dict[tuple[str, str], VideoRecord] = {}
    for record in records:
        key = (record.channel_key, record.video_id)
        prior = merged.get(key)
        if prior is None:
            merged[key] = record
            continue
        prior.tabs = sorted(set(prior.tabs).union(record.tabs))
        for attr in (
            "title",
            "webpage_url",
            "duration_seconds",
            "upload_date",
            "timestamp",
            "live_status",
            "availability",
            "view_count",
            "description",
        ):
            old = getattr(prior, attr)
            new = getattr(record, attr)
            if (old is None or old == "") and new not in (None, ""):
                setattr(prior, attr, new)
    return sorted(
        merged.values(),
        key=lambda item: (item.channel_key, item.timestamp or 0, item.upload_date or "", item.video_id),
    )


def choose_track(info: dict[str, Any]) -> tuple[str, str, dict[str, Any]] | None:
    pools: tuple[tuple[str, dict[str, Any]], ...] = (
        ("manual", info.get("subtitles") or {}),
        ("automatic", info.get("automatic_captions") or {}),
    )
    for kind, pool in pools:
        if not isinstance(pool, dict):
            continue
        ordered_languages = list(LANG_PRIORITY)
        ordered_languages.extend(
            language for language in sorted(pool) if language not in ordered_languages and language.startswith("ko")
        )
        ordered_languages.extend(
            language for language in sorted(pool) if language not in ordered_languages and language.startswith("en")
        )
        ordered_languages.extend(language for language in sorted(pool) if language not in ordered_languages)
        for language in ordered_languages:
            formats = pool.get(language)
            if not isinstance(formats, list) or not formats:
                continue
            candidates = sorted(
                (item for item in formats if isinstance(item, dict) and item.get("url")),
                key=lambda item: FORMAT_PRIORITY.index(item.get("ext"))
                if item.get("ext") in FORMAT_PRIORITY
                else len(FORMAT_PRIORITY),
            )
            if candidates:
                return kind, language, candidates[0]
    return None


def parse_json3(payload: dict[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        if not isinstance(event, dict):
            continue
        pieces = event.get("segs") or []
        text = "".join(str(piece.get("utf8") or "") for piece in pieces if isinstance(piece, dict))
        text = normalized_text(text)
        if not text or text == "\n":
            continue
        start_ms = _as_int(event.get("tStartMs")) or 0
        duration_ms = _as_int(event.get("dDurationMs")) or 0
        segments.append(
            {
                "start": start_ms / 1000.0,
                "duration": duration_ms / 1000.0,
                "text": text,
            }
        )
    return segments


def parse_xmlish(text: str) -> list[dict[str, Any]]:
    import xml.etree.ElementTree as ET

    root = ET.fromstring(text)
    segments: list[dict[str, Any]] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag not in {"text", "p"}:
            continue
        raw = "".join(node.itertext())
        clean = normalized_text(raw)
        if not clean:
            continue
        start = node.attrib.get("start") or node.attrib.get("begin") or "0"
        duration = node.attrib.get("dur") or "0"
        segments.append(
            {
                "start": parse_time_value(start),
                "duration": parse_time_value(duration),
                "text": clean,
            }
        )
    return segments


def parse_time_value(value: str) -> float:
    value = value.strip()
    if value.endswith("ms"):
        try:
            return float(value[:-2]) / 1000.0
        except ValueError:
            return 0.0
    if value.endswith("s"):
        try:
            return float(value[:-1])
        except ValueError:
            return 0.0
    if ":" in value:
        parts = value.split(":")
        try:
            total = 0.0
            for part in parts:
                total = total * 60.0 + float(part)
            return total
        except ValueError:
            return 0.0
    try:
        return float(value)
    except ValueError:
        return 0.0


def parse_vtt(text: str) -> list[dict[str, Any]]:
    timestamp = re.compile(
        r"(?P<sh>\d{1,2}:)?(?P<sm>\d{2}):(?P<ss>\d{2}\.\d{3})\s+-->\s+"
        r"(?P<eh>\d{1,2}:)?(?P<em>\d{2}):(?P<es>\d{2}\.\d{3})"
    )
    lines = text.replace("\r\n", "\n").split("\n")
    segments: list[dict[str, Any]] = []
    idx = 0
    while idx < len(lines):
        match = timestamp.search(lines[idx])
        if not match:
            idx += 1
            continue
        start = _vtt_clock(match.group("sh"), match.group("sm"), match.group("ss"))
        end = _vtt_clock(match.group("eh"), match.group("em"), match.group("es"))
        idx += 1
        body: list[str] = []
        while idx < len(lines) and lines[idx].strip():
            body.append(lines[idx])
            idx += 1
        clean = normalized_text(" ".join(body))
        clean = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", clean)
        clean = normalized_text(clean)
        if clean:
            segments.append({"start": start, "duration": max(0.0, end - start), "text": clean})
        idx += 1
    collapsed: list[dict[str, Any]] = []
    for segment in segments:
        if collapsed and collapsed[-1]["text"] == segment["text"]:
            collapsed[-1]["duration"] = max(
                float(collapsed[-1]["duration"]),
                float(segment["start"]) + float(segment["duration"]) - float(collapsed[-1]["start"]),
            )
        else:
            collapsed.append(segment)
    return collapsed


def _vtt_clock(hour_token: str | None, minute: str, second: str) -> float:
    hours = int(hour_token[:-1]) if hour_token else 0
    return hours * 3600.0 + int(minute) * 60.0 + float(second)


def download_track(track: dict[str, Any], *, timeout: int = 45) -> list[dict[str, Any]]:
    url = str(track["url"])
    ext = str(track.get("ext") or "")
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        ),
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.5",
    }
    response = requests.get(url, headers=headers, timeout=timeout)
    response.raise_for_status()
    if ext == "json3" or response.headers.get("content-type", "").startswith("application/json"):
        return parse_json3(response.json())
    text = response.text
    if ext == "vtt" or text.lstrip().startswith("WEBVTT"):
        return parse_vtt(text)
    return parse_xmlish(text)


def transcript_api_fallback(video_id: str) -> tuple[list[dict[str, Any]], str] | None:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        if hasattr(api, "fetch"):
            fetched = api.fetch(video_id, languages=list(LANG_PRIORITY))
            raw = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
        else:
            raw = YouTubeTranscriptApi.get_transcript(video_id, languages=list(LANG_PRIORITY))
        segments = [
            {
                "start": float(item.get("start") or 0.0),
                "duration": float(item.get("duration") or 0.0),
                "text": normalized_text(str(item.get("text") or "")),
            }
            for item in raw
            if normalized_text(str(item.get("text") or ""))
        ]
        if segments:
            return segments, "youtube-transcript-api"
    except Exception as exc:
        print(f"transcript-api fallback failed for {video_id}: {type(exc).__name__}: {exc}", file=sys.stderr)
    return None


def enrich_and_transcribe(record: VideoRecord, output_root: Path) -> VideoRecord:
    time.sleep(random.uniform(0.05, 0.35))
    opts = {
        **ydl_base_opts(),
        "noplaylist": True,
        "extract_flat": False,
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(record.webpage_url, download=False)
        if not info:
            raise RuntimeError("yt-dlp returned no metadata")
        record.title = str(info.get("title") or record.title)
        record.webpage_url = str(info.get("webpage_url") or record.webpage_url)
        record.duration_seconds = _as_float(info.get("duration")) or record.duration_seconds
        record.upload_date = _as_str(info.get("upload_date")) or record.upload_date
        record.timestamp = _as_int(info.get("timestamp")) or record.timestamp
        record.live_status = _as_str(info.get("live_status")) or record.live_status
        record.availability = _as_str(info.get("availability")) or record.availability
        record.view_count = _as_int(info.get("view_count")) or record.view_count
        description = _as_str(info.get("description"))
        if description:
            record.description = description[:20000]

        chosen = choose_track(info)
        segments: list[dict[str, Any]] = []
        source: str | None = None
        language: str | None = None
        kind: str | None = None
        errors: list[str] = []
        if chosen is not None:
            kind, language, track = chosen
            try:
                segments = download_track(track)
                source = f"yt-dlp-caption-url:{track.get('ext') or 'unknown'}"
            except Exception as exc:
                errors.append(f"caption-url {type(exc).__name__}: {exc}")

        if not segments:
            fallback = transcript_api_fallback(record.video_id)
            if fallback is not None:
                segments, source = fallback
                language = language or "unknown"
                kind = kind or "fallback"

        if not segments:
            record.transcript_status = "missing"
            record.error = "; ".join(errors) or "no public caption track"
            return record

        clean_segments: list[dict[str, Any]] = []
        for item in segments:
            text = normalized_text(str(item.get("text") or ""))
            if not text:
                continue
            clean_segments.append(
                {
                    "start": round(float(item.get("start") or 0.0), 3),
                    "duration": round(max(0.0, float(item.get("duration") or 0.0)), 3),
                    "text": text,
                }
            )
        transcript_text = "\n".join(item["text"] for item in clean_segments).strip()
        if not transcript_text:
            record.transcript_status = "missing"
            record.error = "; ".join(errors) or "caption track parsed to empty text"
            return record

        channel_dir = output_root / "transcripts" / record.channel_key
        channel_dir.mkdir(parents=True, exist_ok=True)
        json_path = channel_dir / f"{record.video_id}.json"
        txt_path = channel_dir / f"{record.video_id}.txt"
        payload = {
            "schema_version": 1,
            "channel_key": record.channel_key,
            "channel_name": record.channel_name,
            "video_id": record.video_id,
            "title": record.title,
            "webpage_url": record.webpage_url,
            "upload_date": record.upload_date,
            "duration_seconds": record.duration_seconds,
            "source": source,
            "language": language,
            "kind": kind,
            "segments": clean_segments,
        }
        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        txt_path.write_text(transcript_text + "\n", encoding="utf-8")
        record.transcript_status = "ok"
        record.transcript_source = source
        record.transcript_language = language
        record.transcript_kind = kind
        record.transcript_segments = len(clean_segments)
        record.transcript_characters = len(transcript_text)
        record.transcript_sha256 = hashlib.sha256(transcript_text.encode("utf-8")).hexdigest()
        record.transcript_path = str(txt_path.relative_to(output_root))
        if errors:
            record.error = "; ".join(errors)
        return record
    except Exception as exc:
        record.transcript_status = "error"
        record.error = f"{type(exc).__name__}: {exc}"
        print(f"fatal extraction error {record.channel_name} {record.video_id}: {record.error}", file=sys.stderr)
        traceback.print_exc()
        return record


def write_outputs(records: list[VideoRecord], output_root: Path, started_at: str) -> dict[str, Any]:
    output_root.mkdir(parents=True, exist_ok=True)
    records_payload = [asdict(record) for record in records]
    (output_root / "VIDEO_INDEX.json").write_text(
        json.dumps(records_payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    with (output_root / "VIDEO_INDEX.jsonl").open("w", encoding="utf-8") as handle:
        for item in records_payload:
            handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")

    by_channel: dict[str, dict[str, Any]] = {}
    for channel in CHANNELS:
        channel_records = [record for record in records if record.channel_key == channel["channel_key"]]
        by_channel[channel["channel_key"]] = {
            "display_name": channel["display_name"],
            "listed": len(channel_records),
            "transcript_ok": sum(record.transcript_status == "ok" for record in channel_records),
            "transcript_missing": sum(record.transcript_status == "missing" for record in channel_records),
            "transcript_error": sum(record.transcript_status == "error" for record in channel_records),
            "total_transcript_characters": sum(record.transcript_characters for record in channel_records),
            "tabs": {tab: sum(tab in record.tabs for record in channel_records) for tab in TAB_NAMES},
        }

    failures = [
        {
            "channel_name": record.channel_name,
            "video_id": record.video_id,
            "title": record.title,
            "status": record.transcript_status,
            "error": record.error,
            "url": record.webpage_url,
        }
        for record in records
        if record.transcript_status != "ok"
    ]
    (output_root / "TRANSCRIPT_FAILURES.json").write_text(
        json.dumps(failures, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    summary = {
        "schema_version": 1,
        "started_at": started_at,
        "completed_at": utc_now(),
        "channels": by_channel,
        "listed_total": len(records),
        "transcript_ok_total": sum(record.transcript_status == "ok" for record in records),
        "transcript_missing_total": sum(record.transcript_status == "missing" for record in records),
        "transcript_error_total": sum(record.transcript_status == "error" for record in records),
        "total_transcript_characters": sum(record.transcript_characters for record in records),
        "failure_count": len(failures),
    }
    (output_root / "CORPUS_SUMMARY.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return summary


def self_test() -> None:
    sample_json = {
        "events": [
            {"tStartMs": 1000, "dDurationMs": 2500, "segs": [{"utf8": "안녕"}, {"utf8": "하세요"}]},
            {"tStartMs": 4000, "dDurationMs": 1000, "segs": [{"utf8": "<b>테스트</b>"}]},
        ]
    }
    parsed = parse_json3(sample_json)
    assert parsed[0]["text"] == "안녕하세요"
    assert parsed[1]["text"] == "테스트"
    sample_vtt = "WEBVTT\n\n00:00:01.000 --> 00:00:03.000\n첫 줄\n\n00:00:03.000 --> 00:00:04.500\n둘째 줄\n"
    parsed_vtt = parse_vtt(sample_vtt)
    assert len(parsed_vtt) == 2 and parsed_vtt[1]["text"] == "둘째 줄"
    assert canonical_video_id({"id": "CxVUB0E9OJU"}) == "CxVUB0E9OJU"
    assert abs(parse_time_value("00:01:02.500") - 62.5) < 1e-9
    print("self-test: ok")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Collect complete public YouTube transcript corpus for three Korean trading channels.")
    parser.add_argument("--output", type=Path, default=Path("artifact/corpus"))
    parser.add_argument("--workers", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="Optional per-channel test limit after deduplication.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        self_test()
        return 0
    started_at = utc_now()
    output_root: Path = args.output
    output_root.mkdir(parents=True, exist_ok=True)

    enumerated: list[VideoRecord] = []
    enumeration_errors: list[dict[str, str]] = []
    for channel in CHANNELS:
        for tab in TAB_NAMES:
            try:
                enumerated.extend(enumerate_tab(channel, tab))
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                enumeration_errors.append(
                    {"channel_key": channel["channel_key"], "channel_name": channel["display_name"], "tab": tab, "error": message}
                )
                print(f"enumeration failed {channel['display_name']} {tab}: {message}", file=sys.stderr)

    records = merge_records(enumerated)
    if args.limit > 0:
        limited: list[VideoRecord] = []
        for channel in CHANNELS:
            channel_records = [record for record in records if record.channel_key == channel["channel_key"]]
            limited.extend(channel_records[-args.limit :])
        records = limited
    (output_root / "ENUMERATION_ERRORS.json").write_text(
        json.dumps(enumeration_errors, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if not records:
        write_outputs([], output_root, started_at)
        print("No videos were enumerated", file=sys.stderr)
        return 2

    print(f"[{utc_now()}] unique videos enumerated: {len(records)}", flush=True)
    processed: list[VideoRecord] = []
    workers = max(1, min(args.workers, 8))
    with cf.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(enrich_and_transcribe, record, output_root): record for record in records}
        for index, future in enumerate(cf.as_completed(futures), start=1):
            result = future.result()
            processed.append(result)
            print(
                f"[{utc_now()}] {index}/{len(records)} {result.channel_name} {result.video_id} "
                f"{result.transcript_status} chars={result.transcript_characters} {result.title[:80]}",
                flush=True,
            )

    processed.sort(key=lambda item: (item.channel_key, item.timestamp or 0, item.upload_date or "", item.video_id))
    summary = write_outputs(processed, output_root, started_at)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), flush=True)
    if enumeration_errors:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
