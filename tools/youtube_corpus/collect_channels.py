#!/usr/bin/env python3
"""Collect a reproducible, auditable corpus of public YouTube captions.

The collector is intentionally conservative about completeness claims:
- it enumerates Videos, Shorts, and Streams tabs;
- it deduplicates by video id;
- every discovered item receives either a transcript record or an explicit
  failure record;
- it never treats a missing caption as a missing video.

Raw transcripts are emitted only to a compressed run artifact, not committed
by this script.  Downstream research should cite channel/video ids and derive
compact, non-verbatim notes instead of republishing full captions.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import gzip
import hashlib
import json
import logging
import os
import random
import re
import time
import traceback
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import yt_dlp
except ImportError as exc:
    raise SystemExit("yt-dlp is required: pip install yt-dlp") from exc

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    YouTubeTranscriptApi = None


LOGGER = logging.getLogger("youtube_corpus")
UTC = dt.timezone.utc
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
WHITESPACE_RE = re.compile(r"\s+")

DEFAULT_CHANNELS: tuple[dict[str, str], ...] = (
    {"name": "쉽알남", "channel_id": "UCBltgdQdT3h004d5cTw-EhQ", "handle": "@쉽.알.남"},
    {"name": "차트브로", "channel_id": "UCE6gcmTBZYm-QLisjUjXYKA", "handle": "@chartbro"},
    {"name": "지표센세", "channel_id": "UCEeQbR5tgf-ogqhxRQHMlQQ", "handle": "@지표센세"},
)

PREFERRED_LANGUAGES: tuple[str, ...] = ("ko", "ko-KR", "ko-orig", "en", "en-US", "en-GB")
PIPED_API_BASES: tuple[str, ...] = (
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
    "https://pipedapi.ducks.party",
    "https://api.piped.private.coffee",
)

SMC_TERM_PATTERNS: Mapping[str, re.Pattern[str]] = {
    "liquidity": re.compile(r"유동성|liquidity|liquidation|청산", re.I),
    "sweep": re.compile(r"스윕|sweep|stop\s*hunt|헌팅", re.I),
    "structure": re.compile(r"시장\s*구조|구조\s*전환|market\s*structure|BOS|CHOCH|MSS", re.I),
    "displacement": re.compile(r"디스플레이스먼트|displacement|impulse|충격파", re.I),
    "imbalance_fvg": re.compile(r"불균형|imbalance|fair\s*value\s*gap|\bFVG\b", re.I),
    "order_block": re.compile(r"오더\s*블록|order\s*block|\bOB\b", re.I),
    "breaker_mitigation": re.compile(r"브레이커|breaker|mitigation|미티게이션", re.I),
    "premium_discount": re.compile(r"프리미엄|디스카운트|premium|discount|equilibrium", re.I),
    "time_session": re.compile(r"킬존|kill\s*zone|세션|session|런던|뉴욕|아시아", re.I),
    "multi_timeframe": re.compile(r"멀티\s*타임|다중\s*시간|multi.?timeframe|상위\s*시간", re.I),
    "risk_execution": re.compile(r"손절|익절|리스크|risk|stop\s*loss|position\s*size|포지션\s*사이즈", re.I),
    "indicator": re.compile(r"지표|indicator|오실레이터|oscillator|다이버전스|divergence", re.I),
}


@dataclasses.dataclass(frozen=True)
class VideoSeed:
    channel_name: str
    channel_id: str
    video_id: str
    title: str | None
    webpage_url: str
    tab: str
    enumeration_source: str
    availability: str | None = None
    duration: float | None = None
    timestamp: int | None = None
    live_status: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class CorpusError(RuntimeError):
    def __init__(self, stage: str, reason: str, detail: str = "") -> None:
        super().__init__(f"{stage}:{reason}: {detail}")
        self.stage = stage
        self.reason = reason
        self.detail = detail


def utc_now_iso() -> str:
    return dt.datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def compact_text(text: str) -> str:
    return WHITESPACE_RE.sub(" ", text).strip()


def safe_error(exc: BaseException, limit: int = 1200) -> str:
    return compact_text(f"{exc.__class__.__name__}: {exc}")[:limit]


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def append_jsonl(handle: Any, payload: Mapping[str, Any]) -> None:
    handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")


def build_http_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.2,
        status_forcelist=(408, 425, 429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET", "HEAD"}),
        respect_retry_after_header=True,
    )
    session = requests.Session()
    session.headers.update({"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"})
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.mount("http://", HTTPAdapter(max_retries=retry))
    return session


def ydl_options(*, flat: bool) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "ignoreerrors": True,
        "skip_download": True,
        "extractor_retries": 4,
        "fragment_retries": 4,
        "retries": 4,
        "socket_timeout": 30,
        "sleep_interval_requests": 0.35,
        "noplaylist": False,
        "geo_bypass": True,
        "cachedir": False,
    }
    if flat:
        opts.update({"extract_flat": "in_playlist", "lazy_playlist": False})
    return opts


def normalize_video_id(entry: Mapping[str, Any]) -> str | None:
    for raw in (entry.get("id"), entry.get("url"), entry.get("webpage_url")):
        if not raw:
            continue
        value = str(raw)
        if VIDEO_ID_RE.fullmatch(value):
            return value
        match = re.search(r"(?:v=|youtu\.be/|shorts/|live/)([A-Za-z0-9_-]{11})", value)
        if match:
            return match.group(1)
    return None


def enumerate_tab(channel: Mapping[str, str], tab: str) -> list[VideoSeed]:
    channel_id = channel["channel_id"]
    url = f"https://www.youtube.com/channel/{channel_id}/{tab}"
    LOGGER.info("Enumerating %s/%s", channel["name"], tab)
    with yt_dlp.YoutubeDL(ydl_options(flat=True)) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise CorpusError("enumeration", "empty_tab", f"{channel['name']} {tab}")
    seeds: list[VideoSeed] = []
    for raw in info.get("entries") or []:
        if not raw or not isinstance(raw, Mapping):
            continue
        video_id = normalize_video_id(raw)
        if not video_id:
            continue
        duration = raw.get("duration")
        timestamp = raw.get("timestamp")
        seeds.append(
            VideoSeed(
                channel_name=channel["name"],
                channel_id=channel_id,
                video_id=video_id,
                title=raw.get("title"),
                webpage_url=f"https://www.youtube.com/watch?v={video_id}",
                tab=tab,
                enumeration_source="yt-dlp",
                availability=raw.get("availability"),
                duration=float(duration) if isinstance(duration, (int, float)) else None,
                timestamp=int(timestamp) if isinstance(timestamp, (int, float)) else None,
                live_status=raw.get("live_status"),
            )
        )
    return seeds


def enumerate_channel_with_ytdlp(channel: Mapping[str, str]) -> tuple[list[VideoSeed], list[dict[str, Any]]]:
    all_seeds: MutableMapping[str, VideoSeed] = {}
    tab_reports: list[dict[str, Any]] = []
    for tab in ("videos", "shorts", "streams"):
        try:
            seeds = enumerate_tab(channel, tab)
            tab_reports.append({"tab": tab, "status": "ok", "count": len(seeds), "source": "yt-dlp"})
            for seed in seeds:
                incumbent = all_seeds.get(seed.video_id)
                if incumbent is None or (incumbent.tab != "videos" and seed.tab == "videos"):
                    all_seeds[seed.video_id] = seed
        except Exception as exc:
            tab_reports.append({"tab": tab, "status": "error", "count": 0, "source": "yt-dlp", "error": safe_error(exc)})
            LOGGER.warning("Tab enumeration failed: %s/%s: %s", channel["name"], tab, safe_error(exc))
    if not all_seeds:
        raise CorpusError("enumeration", "all_tabs_failed", channel["name"])
    return list(all_seeds.values()), tab_reports


def piped_get(session: requests.Session, path: str, params: Mapping[str, Any] | None = None) -> tuple[Any, str]:
    errors: list[str] = []
    bases = list(PIPED_API_BASES)
    random.shuffle(bases)
    for base in bases:
        try:
            response = session.get(f"{base.rstrip('/')}{path}", params=params, timeout=35)
            response.raise_for_status()
            return response.json(), base
        except Exception as exc:
            errors.append(f"{base}: {safe_error(exc, 300)}")
    raise CorpusError("piped", "all_instances_failed", " | ".join(errors)[:1500])


def extract_piped_video_id(item: Mapping[str, Any]) -> str | None:
    raw_url = item.get("url") or item.get("videoId") or item.get("id")
    if raw_url:
        value = str(raw_url)
        if VIDEO_ID_RE.fullmatch(value):
            return value
        match = re.search(r"(?:watch\?v=|shorts/|/)([A-Za-z0-9_-]{11})(?:$|[?&#/])", value)
        if match:
            return match.group(1)
    return None


def enumerate_channel_with_piped(channel: Mapping[str, str], session: requests.Session, max_pages: int = 200) -> tuple[list[VideoSeed], list[dict[str, Any]]]:
    channel_id = channel["channel_id"]
    payload, base = piped_get(session, f"/channel/{channel_id}")
    items: list[Mapping[str, Any]] = []
    nextpage: str | None = None
    if isinstance(payload, Mapping):
        items.extend(x for x in (payload.get("relatedStreams") or payload.get("items") or []) if isinstance(x, Mapping))
        raw_next = payload.get("nextpage")
        nextpage = str(raw_next) if raw_next else None
    page = 1
    seen_tokens: set[str] = set()
    while nextpage and page < max_pages and nextpage not in seen_tokens:
        seen_tokens.add(nextpage)
        page += 1
        next_payload, used_base = piped_get(session, f"/nextpage/channel/{channel_id}", params={"nextpage": nextpage})
        base = used_base
        if not isinstance(next_payload, Mapping):
            break
        items.extend(x for x in (next_payload.get("relatedStreams") or next_payload.get("items") or []) if isinstance(x, Mapping))
        raw_next = next_payload.get("nextpage")
        nextpage = str(raw_next) if raw_next else None
    seeds: MutableMapping[str, VideoSeed] = {}
    for item in items:
        video_id = extract_piped_video_id(item)
        if not video_id:
            continue
        duration = item.get("duration")
        uploaded = item.get("uploaded")
        timestamp = None
        if isinstance(uploaded, (int, float)):
            timestamp = int(uploaded / 1000) if uploaded > 10_000_000_000 else int(uploaded)
        seeds[video_id] = VideoSeed(
            channel_name=channel["name"],
            channel_id=channel_id,
            video_id=video_id,
            title=item.get("title"),
            webpage_url=f"https://www.youtube.com/watch?v={video_id}",
            tab="unknown",
            enumeration_source=f"piped:{base}",
            duration=float(duration) if isinstance(duration, (int, float)) else None,
            timestamp=timestamp,
        )
    if not seeds:
        raise CorpusError("enumeration", "piped_empty", channel["name"])
    return list(seeds.values()), [{"tab": "all", "status": "ok", "count": len(seeds), "source": f"piped:{base}", "pages": page}]


def enumerate_channel(channel: Mapping[str, str], session: requests.Session) -> tuple[list[VideoSeed], list[dict[str, Any]]]:
    try:
        return enumerate_channel_with_ytdlp(channel)
    except Exception as primary_exc:
        LOGGER.warning("yt-dlp enumeration failed for %s; trying Piped: %s", channel["name"], safe_error(primary_exc))
        try:
            seeds, reports = enumerate_channel_with_piped(channel, session)
            reports.insert(0, {"tab": "all", "status": "error", "count": 0, "source": "yt-dlp", "error": safe_error(primary_exc)})
            return seeds, reports
        except Exception as fallback_exc:
            raise CorpusError("enumeration", "all_methods_failed", f"yt-dlp={safe_error(primary_exc)}; piped={safe_error(fallback_exc)}") from fallback_exc


def fetch_video_metadata(video_id: str) -> dict[str, Any]:
    url = f"https://www.youtube.com/watch?v={video_id}"
    opts = ydl_options(flat=False)
    opts.update({"noplaylist": True})
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise CorpusError("metadata", "unavailable", video_id)
    keep = (
        "id", "title", "description", "channel", "channel_id", "uploader", "uploader_id",
        "upload_date", "timestamp", "duration", "availability", "live_status", "was_live",
        "view_count", "like_count", "comment_count", "categories", "tags", "webpage_url", "original_url",
    )
    result = {key: info.get(key) for key in keep}
    result["subtitles"] = info.get("subtitles") or {}
    result["automatic_captions"] = info.get("automatic_captions") or {}
    return result


def language_rank(language_code: str) -> tuple[int, str]:
    normalized = language_code.lower()
    for idx, preferred in enumerate(PREFERRED_LANGUAGES):
        if normalized == preferred.lower():
            return idx, normalized
    if normalized.startswith("ko"):
        return len(PREFERRED_LANGUAGES), normalized
    if normalized.startswith("en"):
        return len(PREFERRED_LANGUAGES) + 1, normalized
    return len(PREFERRED_LANGUAGES) + 10, normalized


def choose_caption_track(metadata: Mapping[str, Any]) -> tuple[str, Mapping[str, Any], bool] | None:
    candidates: list[tuple[tuple[int, str], bool, str, Mapping[str, Any]]] = []
    for generated, key in ((False, "subtitles"), (True, "automatic_captions")):
        tracks = metadata.get(key) or {}
        if not isinstance(tracks, Mapping):
            continue
        for language, formats in tracks.items():
            if not isinstance(formats, Sequence):
                continue
            for fmt in formats:
                if not isinstance(fmt, Mapping) or not fmt.get("url"):
                    continue
                ext = str(fmt.get("ext") or "")
                format_rank = {"json3": 0, "srv3": 1, "ttml": 2, "vtt": 3, "srv1": 4}.get(ext, 8)
                rank = language_rank(str(language))
                candidates.append(((rank[0] * 10 + format_rank, rank[1]), generated, str(language), fmt))
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1]))
    _, generated, language, fmt = candidates[0]
    return language, fmt, generated


def parse_json3(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    for event in payload.get("events") or []:
        if not isinstance(event, Mapping):
            continue
        segs = event.get("segs") or []
        text = compact_text("".join(str(seg.get("utf8") or "") for seg in segs if isinstance(seg, Mapping)).replace("\n", " "))
        if not text:
            continue
        start_ms = event.get("tStartMs") or 0
        duration_ms = event.get("dDurationMs") or 0
        segments.append({"start": float(start_ms) / 1000.0, "duration": float(duration_ms) / 1000.0, "text": text})
    return segments


def strip_caption_markup(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\{\\.*?\}", " ", text)
    return compact_text(text.replace("&nbsp;", " ").replace("&amp;", "&"))


def parse_vtt(payload: str) -> list[dict[str, Any]]:
    def parse_clock(raw: str) -> float:
        bits = raw.replace(",", ".").split(":")
        try:
            if len(bits) == 3:
                return int(bits[0]) * 3600 + int(bits[1]) * 60 + float(bits[2])
            if len(bits) == 2:
                return int(bits[0]) * 60 + float(bits[1])
        except ValueError:
            return 0.0
        return 0.0
    segments: list[dict[str, Any]] = []
    for block in re.split(r"\n\s*\n", payload.replace("\r\n", "\n")):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((idx for idx, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        timing = lines[timing_index].split("-->")
        start = parse_clock(timing[0].strip().split()[0])
        end = parse_clock(timing[1].strip().split()[0]) if len(timing) > 1 else start
        text = strip_caption_markup(" ".join(lines[timing_index + 1:]))
        if text:
            segments.append({"start": start, "duration": max(0.0, end - start), "text": text})
    return dedupe_segments(segments)


def dedupe_segments(segments: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    previous_text = ""
    for segment in segments:
        text = compact_text(str(segment.get("text") or ""))
        if not text or text == previous_text:
            continue
        if previous_text and text.startswith(previous_text) and len(text) > len(previous_text):
            text = compact_text(text[len(previous_text):])
        if not text:
            continue
        result.append({"start": float(segment.get("start") or 0.0), "duration": float(segment.get("duration") or 0.0), "text": text})
        previous_text = compact_text(str(segment.get("text") or ""))
    return result


def fetch_caption_from_ytdlp_track(session: requests.Session, metadata: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    selected = choose_caption_track(metadata)
    if selected is None:
        raise CorpusError("caption", "no_track_in_metadata")
    language, track, generated = selected
    response = session.get(str(track["url"]), timeout=45)
    response.raise_for_status()
    ext = str(track.get("ext") or "")
    content_type = response.headers.get("content-type", "")
    segments = parse_json3(response.json()) if ext == "json3" or "json" in content_type else parse_vtt(response.text)
    if not segments:
        raise CorpusError("caption", "empty_track", f"lang={language}; ext={ext}")
    return segments, {"provider": "youtube-caption-track", "language_code": language, "is_generated": generated, "format": ext}


def transcript_api_instance() -> Any:
    if YouTubeTranscriptApi is None:
        raise CorpusError("caption", "youtube_transcript_api_not_installed")
    try:
        return YouTubeTranscriptApi()
    except Exception:
        return YouTubeTranscriptApi


def fetch_caption_from_transcript_api(video_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    api = transcript_api_instance()
    languages = list(PREFERRED_LANGUAGES)
    transcript_meta: Any = None
    if hasattr(api, "list"):
        transcript_list = api.list(video_id)
        chosen = None
        try:
            chosen = transcript_list.find_manually_created_transcript(languages)
        except Exception:
            pass
        if chosen is None:
            try:
                chosen = transcript_list.find_generated_transcript(languages)
            except Exception:
                pass
        if chosen is None:
            available = list(transcript_list)
            if not available:
                raise CorpusError("caption", "api_no_transcript", video_id)
            available.sort(key=lambda item: (language_rank(getattr(item, "language_code", "")), bool(getattr(item, "is_generated", True))))
            chosen = available[0]
        transcript_meta = chosen
        fetched = chosen.fetch()
    elif hasattr(api, "get_transcript"):
        fetched = api.get_transcript(video_id, languages=languages)
    else:
        raise CorpusError("caption", "api_unsupported_version")
    raw_rows = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else list(fetched)
    segments = dedupe_segments([{"start": row.get("start", 0.0), "duration": row.get("duration", 0.0), "text": row.get("text", "")} for row in raw_rows if isinstance(row, Mapping)])
    if not segments:
        raise CorpusError("caption", "api_empty_transcript")
    return segments, {"provider": "youtube-transcript-api", "language_code": getattr(transcript_meta, "language_code", None), "is_generated": getattr(transcript_meta, "is_generated", None), "format": "segments"}


def parse_transcript_ai_markdown(payload: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    language: str | None = None
    for line in payload.splitlines():
        if line.lower().startswith("language:"):
            language = compact_text(line.split(":", 1)[1])
        match = re.match(r"\s*\[(?:(\d+):)?(\d{1,2}):(\d{2}(?:\.\d+)?)\]\s*(.+?)\s*$", line)
        if not match:
            continue
        hours = int(match.group(1) or 0)
        minutes = int(match.group(2))
        seconds = float(match.group(3))
        text = compact_text(match.group(4))
        if text:
            segments.append({"start": hours * 3600 + minutes * 60 + seconds, "duration": 0.0, "text": text})
    segments = dedupe_segments(segments)
    if not segments:
        raise CorpusError("caption", "transcript_ai_unparseable")
    for idx in range(len(segments) - 1):
        segments[idx]["duration"] = max(0.0, segments[idx + 1]["start"] - segments[idx]["start"])
    return segments, {"provider": "youtube-transcript.ai", "language_code": language, "is_generated": None, "format": "markdown"}


def fetch_caption_from_transcript_ai(session: requests.Session, video_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    response = session.get(f"https://youtube-transcript.ai/transcript/{video_id}.txt", params={"lang": "ko"}, timeout=60)
    response.raise_for_status()
    return parse_transcript_ai_markdown(response.text)


def fetch_transcript(session: requests.Session, video_id: str, metadata: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, str]]]:
    attempts: list[dict[str, str]] = []
    methods = (
        ("youtube-caption-track", lambda: fetch_caption_from_ytdlp_track(session, metadata)),
        ("youtube-transcript-api", lambda: fetch_caption_from_transcript_api(video_id)),
        ("youtube-transcript.ai", lambda: fetch_caption_from_transcript_ai(session, video_id)),
    )
    for name, method in methods:
        try:
            segments, source = method()
            attempts.append({"provider": name, "status": "ok"})
            return segments, source, attempts
        except Exception as exc:
            attempts.append({"provider": name, "status": "error", "error": safe_error(exc, 500)})
            LOGGER.debug("Caption attempt failed %s %s: %s", video_id, name, safe_error(exc))
    raise CorpusError("caption", "all_methods_failed", json.dumps(attempts, ensure_ascii=False))


def term_counts(text: str) -> dict[str, int]:
    return {name: len(pattern.findall(text)) for name, pattern in SMC_TERM_PATTERNS.items()}


def derive_video_record(seed: VideoSeed, metadata: Mapping[str, Any], segments: Sequence[Mapping[str, Any]], caption_source: Mapping[str, Any], attempts: Sequence[Mapping[str, str]]) -> dict[str, Any]:
    text = compact_text(" ".join(str(segment.get("text") or "") for segment in segments))
    upload_date = metadata.get("upload_date")
    published_at = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:8]}" if isinstance(upload_date, str) and re.fullmatch(r"\d{8}", upload_date) else None
    return {
        "schema_version": 1,
        "collected_at": utc_now_iso(),
        "channel_name": seed.channel_name,
        "channel_id": seed.channel_id,
        "video_id": seed.video_id,
        "url": seed.webpage_url,
        "title": metadata.get("title") or seed.title,
        "published_at": published_at,
        "timestamp": metadata.get("timestamp") or seed.timestamp,
        "duration": metadata.get("duration") or seed.duration,
        "availability": metadata.get("availability") or seed.availability,
        "live_status": metadata.get("live_status") or seed.live_status,
        "enumeration_source": seed.enumeration_source,
        "enumeration_tab": seed.tab,
        "caption_source": dict(caption_source),
        "caption_attempts": list(attempts),
        "segment_count": len(segments),
        "character_count": len(text),
        "word_count_approx": len(text.split()),
        "transcript_sha256": sha256_bytes(text.encode("utf-8")),
        "smc_term_counts": term_counts(text),
        "segments": list(segments),
        "text": text,
    }


def failure_record(seed: VideoSeed, stage: str, reason: str, detail: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "collected_at": utc_now_iso(),
        "channel_name": seed.channel_name,
        "channel_id": seed.channel_id,
        "video_id": seed.video_id,
        "url": seed.webpage_url,
        "title": seed.title,
        "enumeration_source": seed.enumeration_source,
        "enumeration_tab": seed.tab,
        "stage": stage,
        "reason": reason,
        "detail": detail[:2000],
    }


def classify_exception(exc: BaseException, default_stage: str) -> tuple[str, str, str]:
    if isinstance(exc, CorpusError):
        return exc.stage, exc.reason, exc.detail
    detail = safe_error(exc)
    low = detail.lower()
    if "transcriptsdisabled" in low or "subtitles are disabled" in low:
        return "caption", "captions_disabled", detail
    if "notranscriptfound" in low or "no transcript" in low:
        return "caption", "no_transcript_found", detail
    if "videounavailable" in low or "unavailable" in low:
        return default_stage, "video_unavailable", detail
    if "private video" in low:
        return default_stage, "private_video", detail
    if "members-only" in low or "members only" in low:
        return default_stage, "members_only", detail
    if "sign in" in low or "confirm you’re not a bot" in low or "confirm you're not a bot" in low:
        return default_stage, "anti_bot", detail
    return default_stage, exc.__class__.__name__, detail


def load_channels(path: Path | None) -> list[dict[str, str]]:
    if path is None:
        return [dict(item) for item in DEFAULT_CHANNELS]
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise SystemExit("Channel config must be a JSON list")
    result: list[dict[str, str]] = []
    for row in payload:
        if not isinstance(row, Mapping):
            raise SystemExit("Each channel config row must be an object")
        name = str(row.get("name") or "").strip()
        channel_id = str(row.get("channel_id") or "").strip()
        handle = str(row.get("handle") or "").strip()
        if not name or not channel_id:
            raise SystemExit(f"Invalid channel row: {row!r}")
        result.append({"name": name, "channel_id": channel_id, "handle": handle})
    return result


def compile_summary(channels: Sequence[Mapping[str, str]], enumeration_reports: Sequence[Mapping[str, Any]], discovered: Sequence[VideoSeed], successes: Sequence[Mapping[str, Any]], failures: Sequence[Mapping[str, Any]], started_at: str, finished_at: str) -> dict[str, Any]:
    success_by_channel = Counter(str(row["channel_name"]) for row in successes)
    failure_by_channel = Counter(str(row["channel_name"]) for row in failures)
    discovered_by_channel = Counter(seed.channel_name for seed in discovered)
    provider_counts = Counter(str((row.get("caption_source") or {}).get("provider") or "unknown") for row in successes)
    failure_reasons = Counter(str(row.get("reason") or "unknown") for row in failures)
    term_totals: Counter[str] = Counter()
    for row in successes:
        term_totals.update({str(k): int(v) for k, v in (row.get("smc_term_counts") or {}).items()})
    return {
        "schema_version": 1,
        "started_at": started_at,
        "finished_at": finished_at,
        "channels": list(channels),
        "enumeration_reports": list(enumeration_reports),
        "discovered_video_count": len(discovered),
        "transcript_success_count": len(successes),
        "transcript_failure_count": len(failures),
        "coverage_ratio": (len(successes) / len(discovered)) if discovered else 0.0,
        "discovered_by_channel": dict(discovered_by_channel),
        "success_by_channel": dict(success_by_channel),
        "failure_by_channel": dict(failure_by_channel),
        "caption_provider_counts": dict(provider_counts),
        "failure_reason_counts": dict(failure_reasons),
        "smc_term_totals": dict(term_totals),
    }


def render_markdown_summary(summary: Mapping[str, Any]) -> str:
    lines = [
        "# YouTube SMC/ICT caption corpus run", "",
        f"- Started (UTC): `{summary['started_at']}`",
        f"- Finished (UTC): `{summary['finished_at']}`",
        f"- Discovered public video IDs: **{summary['discovered_video_count']}**",
        f"- Transcript success: **{summary['transcript_success_count']}**",
        f"- Explicit failures: **{summary['transcript_failure_count']}**",
        f"- Caption coverage: **{float(summary['coverage_ratio']):.2%}**", "",
        "## Per channel", "", "| Channel | Discovered | Transcript | Failure |", "|---|---:|---:|---:|",
    ]
    discovered = summary.get("discovered_by_channel") or {}
    success = summary.get("success_by_channel") or {}
    failure = summary.get("failure_by_channel") or {}
    for channel in summary.get("channels") or []:
        name = channel["name"]
        lines.append(f"| {name} | {discovered.get(name, 0)} | {success.get(name, 0)} | {failure.get(name, 0)} |")
    lines.extend(["", "## Caption providers", ""])
    for provider, count in sorted((summary.get("caption_provider_counts") or {}).items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- `{provider}`: {count}")
    lines.extend(["", "## Failure reasons", ""])
    reasons = summary.get("failure_reason_counts") or {}
    if reasons:
        for reason, count in sorted(reasons.items(), key=lambda x: (-x[1], x[0])):
            lines.append(f"- `{reason}`: {count}")
    else:
        lines.append("- none")
    lines.extend(["", "## Enumeration tabs", ""])
    for report in summary.get("enumeration_reports") or []:
        lines.append(f"- {report.get('channel_name')} / `{report.get('tab')}` / {report.get('source')}: {report.get('status')} ({report.get('count', 0)})")
    return "\n".join(lines) + "\n"


def run(args: argparse.Namespace) -> int:
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    channels = load_channels(Path(args.channels) if args.channels else None)
    session = build_http_session()
    started_at = utc_now_iso()
    discovered_map: MutableMapping[str, VideoSeed] = {}
    enumeration_reports: list[dict[str, Any]] = []
    channel_errors: list[dict[str, Any]] = []
    for channel in channels:
        try:
            seeds, reports = enumerate_channel(channel, session)
            for report in reports:
                enumeration_reports.append({"channel_name": channel["name"], **report})
            for seed in seeds:
                incumbent = discovered_map.get(seed.video_id)
                if incumbent and incumbent.channel_id != seed.channel_id:
                    channel_errors.append({"channel_name": channel["name"], "stage": "enumeration", "reason": "cross_channel_video_id_collision", "detail": f"{seed.video_id}: {incumbent.channel_id} vs {seed.channel_id}"})
                    continue
                discovered_map[seed.video_id] = seed
        except Exception as exc:
            stage, reason, detail = classify_exception(exc, "enumeration")
            channel_errors.append({"channel_name": channel["name"], "channel_id": channel["channel_id"], "stage": stage, "reason": reason, "detail": detail})
            LOGGER.error("Channel enumeration failed: %s: %s", channel["name"], detail)
    discovered = sorted(discovered_map.values(), key=lambda item: (item.channel_name, item.timestamp or 0, item.video_id))
    if not discovered:
        write_json(output / "channel_errors.json", channel_errors)
        raise SystemExit("No videos discovered from any channel")
    with (output / "videos.jsonl").open("w", encoding="utf-8") as handle:
        for seed in discovered:
            append_jsonl(handle, seed.to_dict())
    successes: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    with gzip.open(output / "transcripts.jsonl.gz", "wt", encoding="utf-8", compresslevel=6) as transcript_handle, (output / "failures.jsonl").open("w", encoding="utf-8") as failure_handle:
        for index, seed in enumerate(discovered, start=1):
            LOGGER.info("[%d/%d] %s %s", index, len(discovered), seed.channel_name, seed.video_id)
            try:
                metadata = fetch_video_metadata(seed.video_id)
                segments, source, attempts = fetch_transcript(session, seed.video_id, metadata)
                row = derive_video_record(seed, metadata, segments, source, attempts)
                append_jsonl(transcript_handle, row)
                successes.append({key: value for key, value in row.items() if key not in {"segments", "text"}})
                LOGGER.info("  transcript ok: %s / %s chars", source.get("provider"), row["character_count"])
            except Exception as exc:
                stage, reason, detail = classify_exception(exc, "video")
                row = failure_record(seed, stage, reason, detail)
                append_jsonl(failure_handle, row)
                failures.append(row)
                LOGGER.warning("  failed: %s/%s", stage, reason)
            if args.sleep > 0:
                time.sleep(args.sleep)
    finished_at = utc_now_iso()
    summary = compile_summary(channels, enumeration_reports, discovered, successes, failures, started_at, finished_at)
    summary["channel_errors"] = channel_errors
    summary["files"] = {"videos": "videos.jsonl", "transcripts": "transcripts.jsonl.gz", "failures": "failures.jsonl"}
    write_json(output / "manifest.json", summary)
    write_json(output / "channel_errors.json", channel_errors)
    (output / "summary.md").write_text(render_markdown_summary(summary), encoding="utf-8")
    checksums: list[str] = []
    for path in sorted(output.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS":
            checksums.append(f"{sha256_bytes(path.read_bytes())}  {path.name}")
    (output / "SHA256SUMS").write_text("\n".join(checksums) + "\n", encoding="utf-8")
    LOGGER.info("Done: %d discovered, %d transcripts, %d failures", len(discovered), len(successes), len(failures))
    if channel_errors and any(error.get("reason") == "all_methods_failed" for error in channel_errors):
        return 2
    if args.min_coverage > 0 and summary["coverage_ratio"] < args.min_coverage:
        LOGGER.error("Coverage %.2f is below required %.2f", summary["coverage_ratio"], args.min_coverage)
        return 3
    return 0


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="artifacts/youtube_corpus", help="Output directory")
    parser.add_argument("--channels", help="Optional JSON channel list")
    parser.add_argument("--sleep", type=float, default=0.45, help="Delay between videos")
    parser.add_argument("--min-coverage", type=float, default=0.0, help="Return non-zero if transcript coverage is lower than this ratio")
    parser.add_argument("--log-level", default=os.getenv("LOG_LEVEL", "INFO"))
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=getattr(logging, str(args.log_level).upper(), logging.INFO), format="%(asctime)s %(levelname)s %(message)s")
    try:
        return run(args)
    except KeyboardInterrupt:
        LOGGER.error("Interrupted")
        return 130
    except Exception as exc:
        LOGGER.error("Fatal collector error: %s", safe_error(exc))
        LOGGER.debug("%s", traceback.format_exc())
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
