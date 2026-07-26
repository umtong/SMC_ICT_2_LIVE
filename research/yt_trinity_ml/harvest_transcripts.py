#!/usr/bin/env python3
"""Build an immutable public-caption corpus for three Korean trading channels.

The script deliberately separates inventory completeness from caption availability:
- the YouTube uploads playlist is the canonical public-video inventory;
- every listed video receives a caption attempt;
- a verified no-caption state is retained, not silently dropped;
- network or parser uncertainty makes the corpus partial rather than pretending success.

No video media is downloaded. Only public metadata and caption tracks are retained.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html
import json
import random
import re
import time
import traceback
import urllib.parse
import xml.etree.ElementTree as ET
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, MutableMapping, Sequence


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
CHANNEL_ID_RE = re.compile(r"UC[A-Za-z0-9_-]{22}")
TIMING_RE = re.compile(
    r"(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})"
)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


@dataclasses.dataclass(frozen=True)
class Segment:
    start_ms: int
    duration_ms: int
    text: str

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


@dataclasses.dataclass
class InventoryAttempt:
    method: str
    status: str
    detail: str = ""
    item_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


class HarvestError(RuntimeError):
    pass


class VerifiedNoCaption(HarvestError):
    pass


class VideoUnavailable(HarvestError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def safe_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def clean_caption_text(value: str) -> str:
    text = html.unescape(value or "")
    text = TAG_RE.sub("", text)
    text = text.replace("\u200b", " ").replace("\ufeff", " ")
    text = WS_RE.sub(" ", text).strip()
    return text


def parse_timestamp_ms(value: str) -> int:
    parts = value.replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes = int(parts[0])
        seconds = float(parts[1])
    elif len(parts) == 3:
        hours = int(parts[0])
        minutes = int(parts[1])
        seconds = float(parts[2])
    else:
        raise ValueError(f"invalid timestamp: {value!r}")
    return int(round((hours * 3600 + minutes * 60 + seconds) * 1000))


def parse_vtt(text: str) -> list[Segment]:
    """Parse WebVTT without requiring a third-party parser."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    result: list[Segment] = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        match = TIMING_RE.search(line)
        if not match and i + 1 < len(lines):
            maybe = lines[i + 1].strip()
            match = TIMING_RE.search(maybe)
            if match:
                i += 1
        if not match:
            i += 1
            continue
        start_ms = parse_timestamp_ms(match.group("start"))
        end_ms = parse_timestamp_ms(match.group("end"))
        i += 1
        cue: list[str] = []
        while i < len(lines) and lines[i].strip():
            cue.append(lines[i].strip())
            i += 1
        caption = clean_caption_text(" ".join(cue))
        if caption:
            result.append(Segment(start_ms, max(0, end_ms - start_ms), caption))
        i += 1
    return normalize_segments(result)


def parse_json3(payload: Mapping[str, Any]) -> list[Segment]:
    result: list[Segment] = []
    for event in payload.get("events", []) or []:
        if not isinstance(event, Mapping):
            continue
        text = "".join(
            str(seg.get("utf8") or "")
            for seg in (event.get("segs", []) or [])
            if isinstance(seg, Mapping)
        )
        text = clean_caption_text(text)
        if not text:
            continue
        result.append(
            Segment(
                int(event.get("tStartMs") or 0),
                int(event.get("dDurationMs") or 0),
                text,
            )
        )
    return normalize_segments(result)


def parse_srv_xml(text: str) -> list[Segment]:
    root = ET.fromstring(text)
    result: list[Segment] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in {"text", "p"}:
            continue
        raw = "".join(node.itertext())
        caption = clean_caption_text(raw)
        if not caption:
            continue
        if "start" in node.attrib:
            start_ms = int(round(float(node.attrib.get("start", "0")) * 1000))
            duration_ms = int(round(float(node.attrib.get("dur", "0")) * 1000))
        else:
            start_ms = int(node.attrib.get("t", "0"))
            duration_ms = int(node.attrib.get("d", "0"))
        result.append(Segment(start_ms, duration_ms, caption))
    return normalize_segments(result)


def normalize_segments(segments: Iterable[Segment]) -> list[Segment]:
    ordered = sorted(segments, key=lambda item: (item.start_ms, item.duration_ms, item.text))
    result: list[Segment] = []
    seen_exact: set[tuple[int, int, str]] = set()
    for segment in ordered:
        text = clean_caption_text(segment.text)
        if not text:
            continue
        key = (max(0, int(segment.start_ms)), max(0, int(segment.duration_ms)), text)
        if key in seen_exact:
            continue
        seen_exact.add(key)
        candidate = Segment(*key)
        if result and candidate.text == result[-1].text and abs(candidate.start_ms - result[-1].start_ms) <= 40:
            continue
        result.append(candidate)
    return result


def format_timestamp(ms: int) -> str:
    total_seconds, millis = divmod(max(0, ms), 1000)
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}"


def iter_entries(info: Any) -> Iterator[Mapping[str, Any]]:
    if isinstance(info, Mapping):
        entries = info.get("entries")
        if entries is not None:
            for entry in entries:
                yield from iter_entries(entry)
            return
        yield info
    elif isinstance(info, Iterable) and not isinstance(info, (str, bytes)):
        for entry in info:
            yield from iter_entries(entry)


def video_from_entry(entry: Mapping[str, Any], channel: Mapping[str, Any], source: str) -> dict[str, Any] | None:
    video_id = safe_text(entry.get("id") or entry.get("videoId"))
    if not VIDEO_ID_RE.match(video_id):
        url = safe_text(entry.get("url") or entry.get("webpage_url"))
        parsed = urllib.parse.urlparse(url)
        query_id = urllib.parse.parse_qs(parsed.query).get("v", [""])[0]
        if VIDEO_ID_RE.match(query_id):
            video_id = query_id
    if not VIDEO_ID_RE.match(video_id):
        return None
    duration = entry.get("duration") or entry.get("lengthSeconds")
    try:
        duration_s = float(duration) if duration not in (None, "") else None
    except (TypeError, ValueError):
        duration_s = None
    upload_date = safe_text(entry.get("upload_date") or entry.get("published") or entry.get("publishedText"))
    return {
        "video_id": video_id,
        "title": safe_text(entry.get("title")),
        "description": safe_text(entry.get("description")),
        "duration_s": duration_s,
        "upload_date": upload_date,
        "timestamp": entry.get("timestamp") or entry.get("published"),
        "availability": safe_text(entry.get("availability")),
        "live_status": safe_text(entry.get("live_status") or entry.get("liveNow")),
        "view_count": entry.get("view_count") or entry.get("viewCount"),
        "channel": safe_text(entry.get("channel") or entry.get("uploader") or channel.get("display_name")),
        "channel_id": safe_text(entry.get("channel_id") or entry.get("uploader_id") or channel.get("resolved_channel_id")),
        "channel_slug": channel["slug"],
        "channel_display_name": channel["display_name"],
        "webpage_url": f"https://www.youtube.com/watch?v={video_id}",
        "inventory_sources": [source],
        "source_tabs": [],
    }


def merge_video(target: MutableMapping[str, Any], candidate: Mapping[str, Any]) -> None:
    for key, value in candidate.items():
        if key in {"inventory_sources", "source_tabs"}:
            target[key] = list(dict.fromkeys([*(target.get(key) or []), *(value or [])]))
        elif target.get(key) in (None, "", [], 0) and value not in (None, "", []):
            target[key] = value


def import_requests() -> Any:
    try:
        import requests  # type: ignore
    except ImportError as exc:
        raise HarvestError("requests is required") from exc
    return requests


def request_json(url: str, *, timeout: float = 30.0) -> Any:
    requests = import_requests()
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    return response.json()


def request_text(url: str, *, timeout: float = 30.0) -> str:
    requests = import_requests()
    response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=timeout)
    response.raise_for_status()
    response.encoding = response.encoding or "utf-8"
    return response.text


def resolve_channel_id_ytdlp(channel: Mapping[str, Any]) -> tuple[str | None, str]:
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        return None, "yt_dlp unavailable"
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "playlistend": 1,
        "socket_timeout": 30,
        "retries": 3,
        "extractor_retries": 3,
        "cachedir": False,
    }
    urls = [f"{channel['base_url'].rstrip('/')}/videos", channel["base_url"]]
    errors: list[str] = []
    for url in urls:
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
            candidates: list[str] = []
            if isinstance(info, Mapping):
                candidates.extend(safe_text(info.get(key)) for key in ("channel_id", "uploader_id", "id"))
            for entry in iter_entries(info):
                candidates.extend(safe_text(entry.get(key)) for key in ("channel_id", "uploader_id"))
            for candidate in candidates:
                match = CHANNEL_ID_RE.search(candidate)
                if match:
                    return match.group(0), f"yt_dlp:{url}"
        except Exception as exc:
            errors.append(f"{url}: {type(exc).__name__}: {exc}")
    return None, "; ".join(errors)[-2000:]


def resolve_channel_id_html(channel: Mapping[str, Any]) -> tuple[str | None, str]:
    try:
        text = request_text(channel["base_url"], timeout=30)
    except Exception as exc:
        return None, f"html: {type(exc).__name__}: {exc}"
    patterns = [
        r'"externalId":"(UC[A-Za-z0-9_-]{22})"',
        r'"channelId":"(UC[A-Za-z0-9_-]{22})"',
        r'itemprop="channelId"\s+content="(UC[A-Za-z0-9_-]{22})"',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1), "youtube_html"
    return None, "youtube_html: channel id not found"


def invidious_instances() -> list[str]:
    try:
        payload = request_json("https://api.invidious.io/instances.json", timeout=30)
    except Exception:
        return []
    result: list[str] = []
    for row in payload if isinstance(payload, list) else []:
        if not isinstance(row, list) or len(row) != 2 or not isinstance(row[1], Mapping):
            continue
        domain, details = row
        if not details.get("api") or details.get("type") != "https":
            continue
        monitor = details.get("monitor") or {}
        if isinstance(monitor, Mapping) and monitor.get("down") is True:
            continue
        result.append(f"https://{domain}")
    return result[:12]


def resolve_channel_id_invidious(channel: Mapping[str, Any], instances: Sequence[str]) -> tuple[str | None, str]:
    handle = safe_text(channel["base_url"]).rstrip("/").rsplit("/", 1)[-1]
    for instance in instances:
        for query in (handle, channel["display_name"]):
            try:
                payload = request_json(
                    f"{instance}/api/v1/search?q={urllib.parse.quote(query)}&type=channel", timeout=20
                )
                for item in payload if isinstance(payload, list) else []:
                    author_id = safe_text(item.get("authorId")) if isinstance(item, Mapping) else ""
                    if CHANNEL_ID_RE.fullmatch(author_id):
                        return author_id, f"invidious:{instance}:{query}"
            except Exception:
                continue
    return None, "invidious search failed"


def resolve_channel(channel: MutableMapping[str, Any], instances: Sequence[str]) -> list[InventoryAttempt]:
    attempts: list[InventoryAttempt] = []
    expected = safe_text(channel.get("expected_channel_id"))
    if expected:
        channel["resolved_channel_id"] = expected
        attempts.append(InventoryAttempt("configured_channel_id", "ok", expected, 1))
        return attempts
    for method in (resolve_channel_id_ytdlp, resolve_channel_id_html):
        resolved, detail = method(channel)
        attempts.append(InventoryAttempt(method.__name__, "ok" if resolved else "failed", detail, 1 if resolved else 0))
        if resolved:
            channel["resolved_channel_id"] = resolved
            return attempts
    resolved, detail = resolve_channel_id_invidious(channel, instances)
    attempts.append(InventoryAttempt("resolve_channel_id_invidious", "ok" if resolved else "failed", detail, 1 if resolved else 0))
    if resolved:
        channel["resolved_channel_id"] = resolved
    return attempts


def inventory_ytdlp(playlist_id: str, channel: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise HarvestError("yt_dlp unavailable") from exc
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "extract_flat": "in_playlist",
        "ignoreerrors": True,
        "lazy_playlist": False,
        "socket_timeout": 30,
        "retries": 5,
        "extractor_retries": 5,
        "cachedir": False,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise HarvestError("yt_dlp returned no playlist information")
    result: list[dict[str, Any]] = []
    for entry in iter_entries(info):
        video = video_from_entry(entry, channel, "uploads_playlist:yt_dlp")
        if video:
            result.append(video)
    if not result:
        raise HarvestError("yt_dlp returned zero valid video IDs")
    title = safe_text(info.get("title")) if isinstance(info, Mapping) else ""
    return result, title


def inventory_scrapetube(playlist_id: str, channel: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    try:
        import scrapetube  # type: ignore
    except ImportError as exc:
        raise HarvestError("scrapetube unavailable") from exc
    result: list[dict[str, Any]] = []
    for entry in scrapetube.get_playlist(playlist_id, sleep=0.2):
        video = video_from_entry(entry, channel, "uploads_playlist:scrapetube")
        if video:
            result.append(video)
    if not result:
        raise HarvestError("scrapetube returned zero valid video IDs")
    return result, ""


def inventory_invidious(
    playlist_id: str, channel: Mapping[str, Any], instances: Sequence[str]
) -> tuple[list[dict[str, Any]], str]:
    errors: list[str] = []
    for instance in instances:
        try:
            payload = request_json(f"{instance}/api/v1/playlists/{playlist_id}", timeout=30)
            result: list[dict[str, Any]] = []
            videos = payload.get("videos", []) if isinstance(payload, Mapping) else []
            for entry in videos:
                if isinstance(entry, Mapping):
                    video = video_from_entry(entry, channel, f"uploads_playlist:invidious:{instance}")
                    if video:
                        result.append(video)
            page = 2
            while result and len(videos) >= 100 and page <= 50:
                next_payload = request_json(f"{instance}/api/v1/playlists/{playlist_id}?page={page}", timeout=30)
                next_videos = next_payload.get("videos", []) if isinstance(next_payload, Mapping) else []
                if not next_videos:
                    break
                before = len(result)
                for entry in next_videos:
                    if isinstance(entry, Mapping):
                        video = video_from_entry(entry, channel, f"uploads_playlist:invidious:{instance}")
                        if video:
                            result.append(video)
                if len(result) == before:
                    break
                videos = next_videos
                page += 1
            if result:
                title = safe_text(payload.get("title")) if isinstance(payload, Mapping) else ""
                return result, title
        except Exception as exc:
            errors.append(f"{instance}: {type(exc).__name__}: {exc}")
    raise HarvestError("; ".join(errors)[-4000:] or "no usable Invidious instance")


def optional_tab_inventory(channel: Mapping[str, Any]) -> tuple[dict[str, set[str]], list[InventoryAttempt]]:
    try:
        import yt_dlp  # type: ignore
    except ImportError:
        return {}, [InventoryAttempt("tab_inventory", "skipped", "yt_dlp unavailable")]
    tab_ids: dict[str, set[str]] = {}
    attempts: list[InventoryAttempt] = []
    for tab in ("videos", "shorts", "streams"):
        url = f"{channel['base_url'].rstrip('/')}/{tab}"
        options = {
            "quiet": True,
            "no_warnings": True,
            "skip_download": True,
            "extract_flat": "in_playlist",
            "ignoreerrors": True,
            "socket_timeout": 25,
            "retries": 2,
            "extractor_retries": 2,
            "cachedir": False,
        }
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
            ids = {
                safe_text(entry.get("id") or entry.get("videoId"))
                for entry in iter_entries(info)
                if isinstance(entry, Mapping)
            }
            ids = {video_id for video_id in ids if VIDEO_ID_RE.fullmatch(video_id)}
            tab_ids[tab] = ids
            attempts.append(InventoryAttempt(f"tab:{tab}:yt_dlp", "ok", url, len(ids)))
        except Exception as exc:
            attempts.append(InventoryAttempt(f"tab:{tab}:yt_dlp", "failed", f"{type(exc).__name__}: {exc}"[-2000:]))
    return tab_ids, attempts


def transcript_api_segments(video_id: str) -> tuple[list[Segment], dict[str, Any]]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except ImportError as exc:
        raise HarvestError("youtube-transcript-api unavailable") from exc

    api = YouTubeTranscriptApi()
    try:
        if hasattr(api, "list"):
            listing = api.list(video_id)
        elif hasattr(YouTubeTranscriptApi, "list_transcripts"):
            listing = YouTubeTranscriptApi.list_transcripts(video_id)
        else:
            raise HarvestError("unsupported youtube-transcript-api version")
        tracks = list(listing)
    except Exception as exc:
        name = type(exc).__name__
        if name in {"TranscriptsDisabled", "NoTranscriptFound"}:
            raise VerifiedNoCaption(str(exc)) from exc
        if name in {"VideoUnavailable", "AgeRestricted"}:
            raise VideoUnavailable(str(exc)) from exc
        raise HarvestError(f"transcript list {name}: {exc}") from exc

    if not tracks:
        raise VerifiedNoCaption("transcript API listed zero tracks")

    def score(track: Any) -> tuple[int, int, str]:
        language = safe_text(getattr(track, "language_code", ""))
        generated = bool(getattr(track, "is_generated", False))
        if language == "ko":
            lang_score = 0
        elif language.startswith("ko-"):
            lang_score = 1
        elif language == "en":
            lang_score = 2
        elif language.startswith("en-"):
            lang_score = 3
        else:
            lang_score = 10
        return lang_score, 1 if generated else 0, language

    tracks.sort(key=score)
    errors: list[str] = []
    for track in tracks:
        try:
            fetched = track.fetch()
            raw = getattr(fetched, "snippets", fetched)
            segments: list[Segment] = []
            for item in raw:
                if isinstance(item, Mapping):
                    text = safe_text(item.get("text"))
                    start = float(item.get("start") or 0)
                    duration = float(item.get("duration") or 0)
                else:
                    text = safe_text(getattr(item, "text", ""))
                    start = float(getattr(item, "start", 0) or 0)
                    duration = float(getattr(item, "duration", 0) or 0)
                caption = clean_caption_text(text)
                if caption:
                    segments.append(Segment(round(start * 1000), round(duration * 1000), caption))
            segments = normalize_segments(segments)
            if not segments:
                errors.append(f"{getattr(track, 'language_code', '')}: empty")
                continue
            return segments, {
                "provider": "youtube_transcript_api",
                "language_code": safe_text(getattr(track, "language_code", "")),
                "language": safe_text(getattr(track, "language", "")),
                "is_generated": bool(getattr(track, "is_generated", False)),
                "is_translatable": bool(getattr(track, "is_translatable", False)),
            }
        except Exception as exc:
            errors.append(f"{safe_text(getattr(track, 'language_code', ''))}:{type(exc).__name__}:{exc}")
    raise HarvestError("all transcript API tracks failed: " + "; ".join(errors)[-4000:])


def track_language_score(language: str, is_generated: bool) -> tuple[int, int, str]:
    language = language or ""
    if language == "ko":
        score = 0
    elif language.startswith("ko-") or language.startswith("ko_"):
        score = 1
    elif language == "en":
        score = 2
    elif language.startswith("en-") or language.startswith("en_"):
        score = 3
    else:
        score = 10
    return score, 1 if is_generated else 0, language


def ytdlp_caption_segments(video_id: str) -> tuple[list[Segment], dict[str, Any]]:
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise HarvestError("yt_dlp unavailable") from exc
    url = f"https://www.youtube.com/watch?v={video_id}"
    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "socket_timeout": 30,
        "retries": 5,
        "extractor_retries": 5,
        "cachedir": False,
    }
    try:
        with yt_dlp.YoutubeDL(options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as exc:
        message = str(exc)
        if "not available" in message.lower() or "private" in message.lower():
            raise VideoUnavailable(message) from exc
        raise HarvestError(f"yt_dlp metadata {type(exc).__name__}: {message}") from exc
    if not isinstance(info, Mapping):
        raise HarvestError("yt_dlp returned non-object metadata")
    candidates: list[tuple[tuple[int, int, str], str, bool, Mapping[str, Any]]] = []
    for generated, container_name in ((False, "subtitles"), (True, "automatic_captions")):
        container = info.get(container_name) or {}
        if not isinstance(container, Mapping):
            continue
        for language, formats in container.items():
            for fmt in formats or []:
                if isinstance(fmt, Mapping) and fmt.get("url"):
                    candidates.append((track_language_score(str(language), generated), str(language), generated, fmt))
    if not candidates:
        raise VerifiedNoCaption("yt_dlp metadata contains no caption tracks")
    candidates.sort(key=lambda item: (item[0], 0 if item[3].get("ext") in {"json3", "vtt", "srv3"} else 1))
    errors: list[str] = []
    requests = import_requests()
    for _, language, generated, fmt in candidates:
        try:
            response = requests.get(str(fmt["url"]), headers={"User-Agent": USER_AGENT}, timeout=30)
            response.raise_for_status()
            ext = safe_text(fmt.get("ext"))
            content_type = response.headers.get("content-type", "")
            if ext == "json3" or "json" in content_type:
                segments = parse_json3(response.json())
            elif ext in {"srv1", "srv2", "srv3", "ttml"} or response.text.lstrip().startswith("<"):
                segments = parse_srv_xml(response.text)
            else:
                segments = parse_vtt(response.text)
            if segments:
                return segments, {
                    "provider": "yt_dlp_caption_url",
                    "language_code": language,
                    "is_generated": generated,
                    "format": ext or content_type,
                    "metadata_title": safe_text(info.get("title")),
                    "metadata_upload_date": safe_text(info.get("upload_date")),
                    "metadata_duration_s": info.get("duration"),
                    "metadata_channel": safe_text(info.get("channel") or info.get("uploader")),
                    "metadata_channel_id": safe_text(info.get("channel_id") or info.get("uploader_id")),
                }
            errors.append(f"{language}/{ext}: empty")
        except Exception as exc:
            errors.append(f"{language}/{safe_text(fmt.get('ext'))}:{type(exc).__name__}:{exc}")
    raise HarvestError("all yt_dlp caption tracks failed: " + "; ".join(errors)[-4000:])


def invidious_caption_segments(video_id: str, instances: Sequence[str]) -> tuple[list[Segment], dict[str, Any]]:
    errors: list[str] = []
    requests = import_requests()
    found_track_listing = False
    for instance in instances:
        try:
            payload = request_json(f"{instance}/api/v1/captions/{video_id}", timeout=25)
            tracks = payload.get("captions", payload) if isinstance(payload, Mapping) else payload
            if not isinstance(tracks, list):
                continue
            found_track_listing = True
            if not tracks:
                continue
            candidates: list[tuple[tuple[int, int, str], Mapping[str, Any]]] = []
            for track in tracks:
                if not isinstance(track, Mapping):
                    continue
                language = safe_text(track.get("languageCode") or track.get("label"))
                generated = safe_text(track.get("kind")) == "asr" or bool(track.get("autoGenerated"))
                candidates.append((track_language_score(language, generated), track))
            for _, track in sorted(candidates, key=lambda pair: pair[0]):
                track_url = safe_text(track.get("url"))
                if not track_url:
                    label = urllib.parse.quote(safe_text(track.get("label")))
                    track_url = f"{instance}/api/v1/captions/{video_id}?label={label}"
                elif track_url.startswith("/"):
                    track_url = instance + track_url
                response = requests.get(track_url, headers={"User-Agent": USER_AGENT}, timeout=25)
                response.raise_for_status()
                content_type = response.headers.get("content-type", "")
                if "json" in content_type:
                    segments = parse_json3(response.json())
                elif response.text.lstrip().startswith("<"):
                    segments = parse_srv_xml(response.text)
                else:
                    segments = parse_vtt(response.text)
                if segments:
                    return segments, {
                        "provider": f"invidious:{instance}",
                        "language_code": safe_text(track.get("languageCode") or track.get("label")),
                        "is_generated": safe_text(track.get("kind")) == "asr" or bool(track.get("autoGenerated")),
                    }
        except Exception as exc:
            errors.append(f"{instance}:{type(exc).__name__}:{exc}")
    if found_track_listing and not errors:
        raise VerifiedNoCaption("Invidious listed no captions")
    raise HarvestError("Invidious caption fallback failed: " + "; ".join(errors)[-4000:])


def caption_for_video(
    video_id: str, instances: Sequence[str], retries: int
) -> tuple[list[Segment], dict[str, Any], list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    providers = [
        ("youtube_transcript_api", lambda: transcript_api_segments(video_id)),
        ("yt_dlp", lambda: ytdlp_caption_segments(video_id)),
        ("invidious", lambda: invidious_caption_segments(video_id, instances)),
    ]
    no_caption_votes = 0
    unavailable_votes = 0
    for provider_name, provider in providers:
        for attempt in range(1, max(1, retries) + 1):
            try:
                segments, metadata = provider()
                attempts.append({"provider": provider_name, "attempt": attempt, "status": "ok", "segments": len(segments)})
                return segments, metadata, attempts
            except VerifiedNoCaption as exc:
                no_caption_votes += 1
                attempts.append({"provider": provider_name, "attempt": attempt, "status": "no_caption", "detail": str(exc)[-2000:]})
                break
            except VideoUnavailable as exc:
                unavailable_votes += 1
                attempts.append({"provider": provider_name, "attempt": attempt, "status": "unavailable", "detail": str(exc)[-2000:]})
                break
            except Exception as exc:
                attempts.append({"provider": provider_name, "attempt": attempt, "status": "failed", "detail": f"{type(exc).__name__}: {exc}"[-2000:]})
                if attempt < retries:
                    time.sleep(min(8.0, 0.75 * (2 ** (attempt - 1))) + random.random() * 0.2)
    if no_caption_votes >= 2:
        raise VerifiedNoCaption(canonical_json(attempts))
    if unavailable_votes >= 2:
        raise VideoUnavailable(canonical_json(attempts))
    raise HarvestError(canonical_json(attempts))


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_jsonl(path: Path, values: Iterable[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(canonical_json(value) + "\n")


def transcript_payload(segments: Sequence[Segment]) -> bytes:
    return "".join(canonical_json(segment.as_dict()) + "\n" for segment in segments).encode("utf-8")


def run_harvest(
    config_path: Path, output: Path, retries: int, sleep_s: float, limit: int | None
) -> dict[str, Any]:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    output.mkdir(parents=True, exist_ok=True)
    instances = invidious_instances()
    all_videos: dict[str, dict[str, Any]] = {}
    channel_summaries: list[dict[str, Any]] = []
    inventory_log: list[dict[str, Any]] = []

    for raw_channel in config["channels"]:
        channel: dict[str, Any] = dict(raw_channel)
        attempts = resolve_channel(channel, instances)
        channel_id = safe_text(channel.get("resolved_channel_id"))
        expected = safe_text(channel.get("expected_channel_id"))
        identity_ok = bool(channel_id and (not expected or channel_id == expected))
        inventory: list[dict[str, Any]] = []
        playlist_title = ""
        canonical_method = ""
        if identity_ok:
            uploads_playlist_id = "UU" + channel_id[2:]
            channel["uploads_playlist_id"] = uploads_playlist_id
            methods = [
                ("uploads_playlist:yt_dlp", lambda: inventory_ytdlp(uploads_playlist_id, channel)),
                ("uploads_playlist:scrapetube", lambda: inventory_scrapetube(uploads_playlist_id, channel)),
                ("uploads_playlist:invidious", lambda: inventory_invidious(uploads_playlist_id, channel, instances)),
            ]
            for method_name, method in methods:
                try:
                    inventory, playlist_title = method()
                    attempts.append(InventoryAttempt(method_name, "ok", playlist_title, len(inventory)))
                    canonical_method = method_name
                    break
                except Exception as exc:
                    attempts.append(InventoryAttempt(method_name, "failed", f"{type(exc).__name__}: {exc}"[-4000:]))
        else:
            attempts.append(InventoryAttempt("identity_check", "failed", f"expected={expected!r}; resolved={channel_id!r}"))

        tab_ids, tab_attempts = optional_tab_inventory(channel) if channel_id else ({}, [])
        attempts.extend(tab_attempts)
        for video in inventory:
            for tab, ids in tab_ids.items():
                if video["video_id"] in ids:
                    video["source_tabs"].append(tab)
            existing = all_videos.get(video["video_id"])
            if existing is None:
                all_videos[video["video_id"]] = video
            else:
                merge_video(existing, video)
        inventory_complete = bool(identity_ok and inventory and canonical_method)
        summary = {
            **{key: channel.get(key) for key in ("slug", "display_name", "base_url", "expected_channel_id", "resolved_channel_id", "uploads_playlist_id")},
            "identity_ok": identity_ok,
            "inventory_complete": inventory_complete,
            "canonical_inventory_method": canonical_method,
            "playlist_title": playlist_title,
            "public_video_count": len(inventory),
            "tab_counts": {key: len(value) for key, value in tab_ids.items()},
            "attempts": [attempt.as_dict() for attempt in attempts],
        }
        channel_summaries.append(summary)
        inventory_log.extend({"channel_slug": channel["slug"], **attempt.as_dict()} for attempt in attempts)

    videos = sorted(all_videos.values(), key=lambda value: (value["channel_slug"], value.get("upload_date") or "", value["video_id"]))
    if limit is not None:
        videos = videos[:limit]

    statuses: Counter[str] = Counter()
    provider_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    total_segments = 0
    total_chars = 0
    attempt_rows: list[dict[str, Any]] = []

    for index, video in enumerate(videos, start=1):
        video_id = video["video_id"]
        video["caption_attempted_at_utc"] = utc_now()
        try:
            segments, caption_meta, attempts = caption_for_video(video_id, instances, retries)
            payload = transcript_payload(segments)
            transcript_sha = sha256_bytes(payload)
            transcript_dir = output / "transcripts" / video["channel_slug"]
            jsonl_path = transcript_dir / f"{video_id}.jsonl"
            text_path = transcript_dir / f"{video_id}.txt"
            jsonl_path.parent.mkdir(parents=True, exist_ok=True)
            jsonl_path.write_bytes(payload)
            text_path.write_text(
                "".join(f"[{format_timestamp(segment.start_ms)}] {segment.text}\n" for segment in segments),
                encoding="utf-8",
                newline="\n",
            )
            video.update(
                {
                    "caption_status": "ok",
                    "caption_provider": caption_meta.get("provider"),
                    "caption_language_code": caption_meta.get("language_code"),
                    "caption_is_generated": caption_meta.get("is_generated"),
                    "caption_segment_count": len(segments),
                    "caption_char_count": sum(len(segment.text) for segment in segments),
                    "caption_sha256": transcript_sha,
                    "transcript_jsonl": str(jsonl_path.relative_to(output)),
                    "transcript_text": str(text_path.relative_to(output)),
                }
            )
            for target_key, source_key in (
                ("title", "metadata_title"),
                ("upload_date", "metadata_upload_date"),
                ("duration_s", "metadata_duration_s"),
                ("channel", "metadata_channel"),
                ("channel_id", "metadata_channel_id"),
            ):
                if video.get(target_key) in (None, "") and caption_meta.get(source_key) not in (None, ""):
                    video[target_key] = caption_meta[source_key]
            statuses["ok"] += 1
            provider_counts[safe_text(caption_meta.get("provider"))] += 1
            language_counts[safe_text(caption_meta.get("language_code"))] += 1
            total_segments += len(segments)
            total_chars += video["caption_char_count"]
        except VerifiedNoCaption as exc:
            attempts = json.loads(str(exc)) if str(exc).startswith("[") else []
            video.update({"caption_status": "no_caption", "caption_error": str(exc)[-4000:]})
            statuses["no_caption"] += 1
        except VideoUnavailable as exc:
            attempts = json.loads(str(exc)) if str(exc).startswith("[") else []
            video.update({"caption_status": "unavailable", "caption_error": str(exc)[-4000:]})
            statuses["unavailable"] += 1
        except Exception as exc:
            attempts = []
            try:
                parsed = json.loads(str(exc))
                if isinstance(parsed, list):
                    attempts = parsed
            except Exception:
                pass
            video.update(
                {
                    "caption_status": "fetch_failed",
                    "caption_error": f"{type(exc).__name__}: {exc}"[-4000:],
                    "caption_traceback": traceback.format_exc(limit=5)[-8000:],
                }
            )
            statuses["fetch_failed"] += 1
        for row in attempts:
            attempt_rows.append({"video_id": video_id, "channel_slug": video["channel_slug"], **row})
        if sleep_s > 0 and index < len(videos):
            time.sleep(sleep_s + random.random() * min(0.25, sleep_s))

    write_jsonl(output / "videos.jsonl", videos)
    write_jsonl(output / "caption_attempts.jsonl", attempt_rows)
    write_jsonl(output / "inventory_attempts.jsonl", inventory_log)
    write_json(output / "channels.json", channel_summaries)

    canonical_corpus_rows = [
        {
            "video_id": video["video_id"],
            "channel_slug": video["channel_slug"],
            "caption_status": video.get("caption_status"),
            "caption_sha256": video.get("caption_sha256"),
            "title": video.get("title"),
            "upload_date": video.get("upload_date"),
        }
        for video in videos
    ]
    inventory_complete = bool(channel_summaries) and all(row["inventory_complete"] for row in channel_summaries)
    caption_complete = statuses["fetch_failed"] == 0 and sum(statuses.values()) == len(videos)
    manifest = {
        "schema_version": 1,
        "work_claim_id": config.get("work_claim_id"),
        "snapshot_as_of_utc": config.get("snapshot_as_of_utc"),
        "harvest_started_or_completed_at_utc": utc_now(),
        "config_sha256": sha256_bytes(config_path.read_bytes()),
        "inventory_complete": inventory_complete,
        "caption_attempt_complete": caption_complete,
        "decision": "PASS_COMPLETE" if inventory_complete and caption_complete else "PARTIAL_REQUIRES_RETRY",
        "channel_count": len(channel_summaries),
        "unique_public_video_count": len(videos),
        "caption_status_counts": dict(sorted(statuses.items())),
        "caption_provider_counts": dict(sorted(provider_counts.items())),
        "caption_language_counts": dict(sorted(language_counts.items())),
        "total_caption_segments": total_segments,
        "total_caption_characters": total_chars,
        "corpus_digest_sha256": sha256_text(canonical_json(canonical_corpus_rows)),
        "invidious_instances_considered": instances,
        "channels": channel_summaries,
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


def self_test() -> None:
    vtt = """WEBVTT

00:00:01.000 --> 00:00:02.500
<v Speaker>안녕하세요</v>

2
00:02.500 --> 00:04.000 align:start position:0%
유동성  스윕

00:02.500 --> 00:04.000
유동성 스윕
"""
    segments = parse_vtt(vtt)
    assert [segment.text for segment in segments] == ["안녕하세요", "유동성 스윕"]
    assert segments[0].start_ms == 1000 and segments[0].duration_ms == 1500
    json3 = {"events": [{"tStartMs": 42, "dDurationMs": 90, "segs": [{"utf8": "FVG"}, {"utf8": " 확인"}]}]}
    assert parse_json3(json3) == [Segment(42, 90, "FVG 확인")]
    xml = '<transcript><text start="1.5" dur="2.0">오더 블록</text></transcript>'
    assert parse_srv_xml(xml) == [Segment(1500, 2000, "오더 블록")]
    assert parse_timestamp_ms("01:02.345") == 62345
    assert parse_timestamp_ms("1:01:02.345") == 3662345


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--sleep-seconds", type=float, default=0.25)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        print("self-test: PASS")
        return 0
    if not args.config or not args.output:
        parser.error("--config and --output are required unless --self-test is used")
    manifest = run_harvest(args.config, args.output, args.retries, args.sleep_seconds, args.limit)
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
