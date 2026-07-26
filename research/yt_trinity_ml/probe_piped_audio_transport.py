#!/usr/bin/env python3
"""Validate public Piped subtitle/audio transports for the YT Trinity corpus.

This probe is intentionally low-volume. It tests a small, channel-balanced sample,
fetches at most one 64 KiB audio prefix per video, and stops at the first instance
that returns either timestamped captions or a readable audio stream.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import platform
import re
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
INSTANCE_SOURCE = (
    "https://raw.githubusercontent.com/TeamPiped/documentation/main/"
    "content/docs/public-instances/index.md"
)
FALLBACK_INSTANCES = (
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.tokhmi.xyz",
    "https://pipedapi.moomoo.me",
    "https://pipedapi.syncpundit.io",
    "https://api-piped.mha.fi",
    "https://piped-api.garudalinux.org",
    "https://pipedapi.rivo.lol",
    "https://pipedapi.leptons.xyz",
    "https://piped-api.lunar.icu",
    "https://pipedapi-libre.kavin.rocks",
    "https://pipedapi.pfcd.me",
    "https://api.piped.yt",
)
DEFAULT_VIDEOS = (
    ("known_positive_control", "F6wDs1HRTSo"),
    ("chartbro", "0h9lpMUBSlE"),
    ("chartbro", "2jI7yDjpWv8"),
    ("swipalnam", "-Tp2fhvVVGM"),
    ("swipalnam", "6fVd2eNbWxI"),
    ("indicator_sensei", "2U0s_i07vMY"),
    ("indicator_sensei", "2I378ynVNYY"),
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_url(value: str) -> dict[str, Any]:
    try:
        parsed = urllib.parse.urlsplit(value)
        return {
            "scheme": parsed.scheme,
            "host": parsed.netloc,
            "path": parsed.path,
            "query_keys": sorted(urllib.parse.parse_qs(parsed.query, keep_blank_values=True)),
        }
    except Exception:
        return {"scheme": "", "host": "", "path": "", "query_keys": []}


def absolute_url(instance: str, value: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    if value.startswith("//"):
        return "https:" + value
    if urllib.parse.urlsplit(value).scheme:
        return value
    return urllib.parse.urljoin(instance.rstrip("/") + "/", value.lstrip("/"))


def parse_timestamped_segments(body: bytes, content_type: str) -> dict[str, Any]:
    text = body.decode("utf-8", errors="replace")
    stripped = text.lstrip("\ufeff\r\n\t ")
    result: dict[str, Any] = {
        "format": "unknown",
        "segments": 0,
        "text_chars": 0,
        "prefix": re.sub(r"\s+", " ", text[:240]).strip(),
    }
    snippets: list[str] = []
    try:
        if "json" in content_type.lower() or stripped.startswith("{") or stripped.startswith("["):
            payload = json.loads(stripped)
            result["format"] = "json"
            if isinstance(payload, Mapping):
                events = payload.get("events")
                if isinstance(events, list):
                    for event in events:
                        if not isinstance(event, Mapping):
                            continue
                        value = "".join(
                            str(segment.get("utf8") or "")
                            for segment in (event.get("segs") or [])
                            if isinstance(segment, Mapping)
                        ).strip()
                        if value:
                            snippets.append(value)
                for key in ("transcript", "captions", "segments"):
                    rows = payload.get(key)
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        if not isinstance(row, Mapping):
                            continue
                        value = str(row.get("text") or row.get("utf8") or row.get("content") or "").strip()
                        if value:
                            snippets.append(value)
            elif isinstance(payload, list):
                for row in payload:
                    if isinstance(row, Mapping):
                        value = str(row.get("text") or row.get("utf8") or row.get("content") or "").strip()
                        if value:
                            snippets.append(value)
        elif "WEBVTT" in text[:200] or "-->" in text:
            result["format"] = "vtt"
            cues = re.split(r"\r?\n\s*\r?\n", text)
            for cue in cues:
                if "-->" not in cue:
                    continue
                lines = [line.strip() for line in cue.splitlines() if line.strip()]
                value = " ".join(line for line in lines if "-->" not in line and not line.isdigit()).strip()
                if value:
                    snippets.append(value)
        elif stripped.startswith("<"):
            result["format"] = "xml"
            for match in re.finditer(r"<(?:text|p)\b[^>]*>(.*?)</(?:text|p)>", text, flags=re.I | re.S):
                value = re.sub(r"<[^>]+>", " ", match.group(1))
                value = html.unescape(re.sub(r"\s+", " ", value)).strip()
                if value:
                    snippets.append(value)
        else:
            result["format"] = "text"
    except Exception as exc:
        result["parse_error"] = f"{type(exc).__name__}: {exc}"[-1000:]
    result["segments"] = len(snippets)
    result["text_chars"] = sum(len(value) for value in snippets)
    result["first_segments"] = snippets[:5]
    return result


def discover_instances(session: requests.Session, limit: int) -> tuple[list[str], dict[str, Any]]:
    discovered: list[str] = []
    evidence: dict[str, Any] = {"source": INSTANCE_SOURCE}
    try:
        response = session.get(INSTANCE_SOURCE, timeout=30)
        body = response.content
        evidence.update(
            {
                "status": response.status_code,
                "bytes": len(body),
                "sha256": sha256_bytes(body),
                "content_type": response.headers.get("content-type", ""),
            }
        )
        if response.ok:
            for value in re.findall(r"https://[A-Za-z0-9._:-]+", response.text):
                host = urllib.parse.urlsplit(value).netloc.lower()
                if not host:
                    continue
                if any(token in host for token in ("github.com", "piped.video", "ipfs")):
                    continue
                discovered.append(value.rstrip("/"))
    except Exception as exc:
        evidence["error"] = f"{type(exc).__name__}: {exc}"[-1000:]
    discovered.extend(FALLBACK_INSTANCES)
    unique = list(dict.fromkeys(discovered))[: max(1, limit)]
    evidence["instance_count"] = len(unique)
    evidence["instances"] = unique
    return unique, evidence


def subtitle_sort_key(track: Mapping[str, Any]) -> tuple[int, int, str]:
    code = str(track.get("code") or track.get("languageCode") or "").lower()
    if code == "ko":
        language_rank = 0
    elif code.startswith("ko-"):
        language_rank = 1
    elif code == "en":
        language_rank = 2
    elif code.startswith("en-"):
        language_rank = 3
    else:
        language_rank = 10
    return (language_rank, 1 if bool(track.get("autoGenerated")) else 0, code)


def audio_sort_key(stream: Mapping[str, Any]) -> tuple[int, int, str]:
    bitrate_raw = stream.get("bitrate")
    try:
        bitrate = int(bitrate_raw)
    except (TypeError, ValueError):
        bitrate = 10**12
    mime = str(stream.get("mimeType") or stream.get("format") or "")
    return (0 if bitrate > 0 else 1, bitrate, mime)


def fetch_subtitle(
    session: requests.Session,
    instance: str,
    track: Mapping[str, Any],
    timeout: float,
) -> dict[str, Any]:
    target = absolute_url(instance, str(track.get("url") or ""))
    row: dict[str, Any] = {
        "code": str(track.get("code") or track.get("languageCode") or ""),
        "name": str(track.get("name") or track.get("label") or ""),
        "auto_generated": bool(track.get("autoGenerated")),
        "mime_type": str(track.get("mimeType") or ""),
        "url": safe_url(target),
    }
    if not target:
        row["error"] = "missing subtitle URL"
        return row
    try:
        response = session.get(target, timeout=timeout)
        body = response.content
        row.update(
            {
                "status": response.status_code,
                "bytes": len(body),
                "sha256": sha256_bytes(body),
                "content_type": response.headers.get("content-type", ""),
            }
        )
        row.update(parse_timestamped_segments(body, row["content_type"]))
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"[-1500:]
    return row


def probe_audio_prefix(
    session: requests.Session,
    instance: str,
    stream: Mapping[str, Any],
    timeout: float,
    sample_bytes: int,
) -> dict[str, Any]:
    target = absolute_url(instance, str(stream.get("url") or ""))
    row: dict[str, Any] = {
        "bitrate": stream.get("bitrate"),
        "codec": str(stream.get("codec") or ""),
        "format": str(stream.get("format") or stream.get("mimeType") or ""),
        "url": safe_url(target),
        "sample_limit_bytes": sample_bytes,
    }
    if not target:
        row["error"] = "missing audio URL"
        return row
    headers = {"Range": f"bytes=0-{max(0, sample_bytes - 1)}", "Accept-Encoding": "identity"}
    try:
        with session.get(target, headers=headers, stream=True, timeout=timeout) as response:
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(chunk_size=16_384):
                if not chunk:
                    continue
                remaining = sample_bytes - total
                if remaining <= 0:
                    break
                piece = chunk[:remaining]
                chunks.append(piece)
                total += len(piece)
                if total >= sample_bytes:
                    break
            body = b"".join(chunks)
            row.update(
                {
                    "status": response.status_code,
                    "bytes": len(body),
                    "sha256": sha256_bytes(body),
                    "content_type": response.headers.get("content-type", ""),
                    "content_length": response.headers.get("content-length"),
                    "content_range": response.headers.get("content-range"),
                    "accept_ranges": response.headers.get("accept-ranges"),
                }
            )
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"[-1500:]
    row["validated"] = bool(
        int(row.get("status") or 0) in {200, 206}
        and int(row.get("bytes") or 0) >= min(4096, sample_bytes)
        and "text/html" not in str(row.get("content_type") or "").lower()
    )
    return row


def probe_instance(
    session: requests.Session,
    instance: str,
    video_id: str,
    timeout: float,
    sample_bytes: int,
) -> dict[str, Any]:
    started = time.monotonic()
    endpoint = f"{instance.rstrip('/')}/streams/{urllib.parse.quote(video_id, safe='')}"
    row: dict[str, Any] = {
        "instance": instance,
        "endpoint": safe_url(endpoint),
        "caption_segments": 0,
        "audio_validated": False,
        "subtitle_attempts": [],
    }
    try:
        response = session.get(endpoint, timeout=timeout)
        body = response.content
        row.update(
            {
                "status": response.status_code,
                "bytes": len(body),
                "sha256": sha256_bytes(body),
                "content_type": response.headers.get("content-type", ""),
            }
        )
        if not response.ok:
            row["body_prefix"] = re.sub(r"\s+", " ", response.text[:300]).strip()
            return row
        payload = response.json()
        if not isinstance(payload, Mapping):
            row["error"] = "streams payload was not an object"
            return row
        subtitles = payload.get("subtitles") or []
        audio_streams = payload.get("audioStreams") or []
        row.update(
            {
                "title": str(payload.get("title") or ""),
                "duration": payload.get("duration"),
                "uploader": str(payload.get("uploader") or ""),
                "subtitle_track_count": len(subtitles) if isinstance(subtitles, list) else 0,
                "audio_stream_count": len(audio_streams) if isinstance(audio_streams, list) else 0,
            }
        )
        if isinstance(subtitles, list):
            ordered_tracks = sorted(
                (track for track in subtitles if isinstance(track, Mapping)),
                key=subtitle_sort_key,
            )
            for track in ordered_tracks[:4]:
                evidence = fetch_subtitle(session, instance, track, timeout)
                row["subtitle_attempts"].append(evidence)
                row["caption_segments"] = max(
                    int(row["caption_segments"]), int(evidence.get("segments") or 0)
                )
                if row["caption_segments"] > 0:
                    break
        if isinstance(audio_streams, list) and audio_streams:
            ordered_audio = sorted(
                (stream for stream in audio_streams if isinstance(stream, Mapping)),
                key=audio_sort_key,
            )
            if ordered_audio:
                row["audio"] = probe_audio_prefix(
                    session, instance, ordered_audio[0], timeout, sample_bytes
                )
                row["audio_validated"] = bool(row["audio"].get("validated"))
    except Exception as exc:
        row["error"] = f"{type(exc).__name__}: {exc}"[-2000:]
    finally:
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
    row["transport_validated"] = bool(row["caption_segments"] > 0 or row["audio_validated"])
    return row


def parse_videos(raw_values: Sequence[str]) -> list[tuple[str, str]]:
    if not raw_values:
        return list(DEFAULT_VIDEOS)
    videos: list[tuple[str, str]] = []
    for raw in raw_values:
        slug, video_id = raw.split(":", 1) if ":" in raw else ("custom", raw)
        slug = slug.strip()
        video_id = video_id.strip()
        if not slug or not re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video_id):
            raise ValueError(f"invalid --video value: {raw!r}")
        videos.append((slug, video_id))
    return videos


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--video", action="append", default=[])
    parser.add_argument("--max-instances", type=int, default=12)
    parser.add_argument("--request-timeout-seconds", type=float, default=30.0)
    parser.add_argument("--between-instance-seconds", type=float, default=2.0)
    parser.add_argument("--between-video-seconds", type=float, default=4.0)
    parser.add_argument("--audio-sample-bytes", type=int, default=65_536)
    args = parser.parse_args(argv)

    if args.max_instances < 1 or args.max_instances > 30:
        parser.error("--max-instances must be between 1 and 30")
    if args.audio_sample_bytes < 4096 or args.audio_sample_bytes > 1_048_576:
        parser.error("--audio-sample-bytes must be between 4096 and 1048576")

    videos = parse_videos(args.video)
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": "application/json,text/plain,*/*",
            "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
        }
    )

    rows: list[dict[str, Any]] = []
    try:
        instances, discovery = discover_instances(session, args.max_instances)
        for video_index, (slug, video_id) in enumerate(videos):
            if video_index:
                time.sleep(max(0.0, args.between_video_seconds))
            attempts: list[dict[str, Any]] = []
            winner: dict[str, Any] | None = None
            for instance_index, instance in enumerate(instances):
                if instance_index:
                    time.sleep(max(0.0, args.between_instance_seconds))
                evidence = probe_instance(
                    session,
                    instance,
                    video_id,
                    args.request_timeout_seconds,
                    args.audio_sample_bytes,
                )
                attempts.append(evidence)
                if evidence.get("transport_validated"):
                    winner = evidence
                    break
            rows.append(
                {
                    "channel_slug": slug,
                    "video_id": video_id,
                    "caption_segments": int((winner or {}).get("caption_segments") or 0),
                    "audio_validated": bool((winner or {}).get("audio_validated")),
                    "transport_validated": winner is not None,
                    "winning_instance": (winner or {}).get("instance"),
                    "attempts": attempts,
                }
            )
    finally:
        session.close()

    targets = [row for row in rows if row["channel_slug"] != "known_positive_control"]
    controls = [row for row in rows if row["channel_slug"] == "known_positive_control"]
    positive_control_passed = bool(controls) and all(row["transport_validated"] for row in controls)
    target_caption_count = sum(row["caption_segments"] > 0 for row in targets)
    target_audio_count = sum(row["audio_validated"] for row in targets)
    target_transport_count = sum(row["transport_validated"] for row in targets)

    if positive_control_passed and targets and target_caption_count == len(targets):
        decision = "PASS_DIRECT_CAPTIONS"
    elif positive_control_passed and targets and target_transport_count == len(targets):
        decision = "PASS_AUDIO_ASR_ROUTE"
    elif target_transport_count:
        decision = "PARTIAL_TRANSPORT"
    else:
        decision = "FAIL"

    payload: dict[str, Any] = {
        "schema_version": 1,
        "workflow": "YT Trinity Piped subtitle/audio transport probe",
        "decision": decision,
        "runner": {
            "platform": platform.platform(),
            "python": sys.version,
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_sha": os.environ.get("GITHUB_SHA"),
        },
        "instance_discovery": discovery,
        "positive_control_passed": positive_control_passed,
        "target_count": len(targets),
        "target_caption_count": target_caption_count,
        "target_audio_count": target_audio_count,
        "target_transport_count": target_transport_count,
        "rows": rows,
    }
    payload["payload_sha256_before_field"] = sha256_bytes(canonical_json(payload).encode("utf-8"))
    destination = args.output / "probe.json"
    destination.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
