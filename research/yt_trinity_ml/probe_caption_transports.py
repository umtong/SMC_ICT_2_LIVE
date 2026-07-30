#!/usr/bin/env python3
"""Probe public YouTube caption transports without downloading video media."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import subprocess
import sys
import time
import urllib.parse
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
DEFAULT_VIDEOS = (
    ("chartbro", "0h9lpMUBSlE"),
    ("swipalnam", "-Tp2fhvVVGM"),
    ("indicator_sensei", "2U0s_i07vMY"),
    ("known_previous_success", "F6wDs1HRTSo"),
)
PROFILE_CLIENTS = {
    "default": None,
    "default_impersonate": None,
    "android_vr": "android_vr",
    "web_embedded": "web_embedded",
    "tv": "tv",
    "tv_simply": "tv_simply",
    "web_safari": "web_safari",
    "mweb": "mweb",
    "ios": "ios",
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def safe_url(value: str) -> dict[str, str]:
    try:
        parsed = urllib.parse.urlsplit(value)
        return {"scheme": parsed.scheme, "host": parsed.netloc, "path": parsed.path}
    except Exception:
        return {"scheme": "", "host": "", "path": ""}


def body_evidence(response: requests.Response) -> dict[str, Any]:
    body = response.content
    content_type = response.headers.get("content-type", "")
    result: dict[str, Any] = {
        "http_status": response.status_code,
        "content_type": content_type,
        "bytes": len(body),
        "sha256": sha256_bytes(body),
        "url": safe_url(response.url),
        "segments": 0,
        "format": "unknown",
    }
    if not body:
        return result
    text = response.text
    stripped = text.lstrip()
    try:
        if "json" in content_type or stripped.startswith("{") or stripped.startswith("["):
            payload = response.json()
            result["format"] = "json"
            if isinstance(payload, Mapping):
                events = payload.get("events") or []
                if isinstance(events, list):
                    result["segments"] = sum(
                        1
                        for event in events
                        if isinstance(event, Mapping)
                        and any(
                            isinstance(segment, Mapping) and str(segment.get("utf8") or "").strip()
                            for segment in (event.get("segs") or [])
                        )
                    )
                elif isinstance(payload.get("captions"), list):
                    result["track_count"] = len(payload["captions"])
            elif isinstance(payload, list):
                result["list_count"] = len(payload)
        elif stripped.startswith("<"):
            result["format"] = "xml"
            result["segments"] = len(re.findall(r"<(?:text|p)(?:\s|>)", text))
        elif "WEBVTT" in text[:100] or "-->" in text:
            result["format"] = "vtt"
            result["segments"] = text.count("-->")
        else:
            result["format"] = "text"
    except Exception as exc:
        result["parse_error"] = f"{type(exc).__name__}: {exc}"[-1000:]
    result["body_prefix"] = re.sub(r"\s+", " ", text[:240]).strip()
    return result


def best_caption_formats(info: Mapping[str, Any]) -> list[tuple[str, bool, Mapping[str, Any]]]:
    rows: list[tuple[tuple[int, int, int, str], str, bool, Mapping[str, Any]]] = []
    for generated, key in ((False, "subtitles"), (True, "automatic_captions")):
        container = info.get(key) or {}
        if not isinstance(container, Mapping):
            continue
        for language, formats in container.items():
            language_text = str(language)
            if language_text == "ko":
                language_score = 0
            elif language_text.startswith("ko-"):
                language_score = 1
            elif language_text == "en":
                language_score = 2
            elif language_text.startswith("en-"):
                language_score = 3
            else:
                language_score = 10
            for fmt in formats or []:
                if not isinstance(fmt, Mapping) or not fmt.get("url"):
                    continue
                ext = str(fmt.get("ext") or "")
                format_score = {"json3": 0, "srv3": 1, "vtt": 2}.get(ext, 5)
                rows.append(((language_score, 1 if generated else 0, format_score, language_text), language_text, generated, fmt))
    rows.sort(key=lambda item: item[0])
    return [(language, generated, fmt) for _, language, generated, fmt in rows]


def run_command(command: Sequence[str], timeout: int = 150) -> dict[str, Any]:
    started = time.monotonic()
    try:
        completed = subprocess.run(
            list(command),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        return {
            "returncode": completed.returncode,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "returncode": None,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "stdout": exc.stdout or "",
            "stderr": (exc.stderr or "") + f"\nTimeoutExpired after {timeout}s",
        }


def probe_ytdlp(video_id: str, profile: str, session: requests.Session) -> dict[str, Any]:
    client = PROFILE_CLIENTS[profile]
    command = [
        sys.executable,
        "-m",
        "yt_dlp",
        "--skip-download",
        "--dump-single-json",
        "--no-playlist",
        "--no-warnings",
        "--socket-timeout",
        "30",
        "--retries",
        "1",
        "--extractor-retries",
        "1",
        "--sleep-requests",
        "4",
        "--sleep-subtitles",
        "4",
        "--js-runtimes",
        "deno",
        "--remote-components",
        "ejs:github",
    ]
    if client:
        command.extend(["--extractor-args", f"youtube:player_client={client}"])
    if profile == "default_impersonate":
        command.extend(["--impersonate", "chrome"])
    command.append(f"https://www.youtube.com/watch?v={video_id}")
    executed = run_command(command)
    result: dict[str, Any] = {
        "provider": "yt_dlp",
        "profile": profile,
        "returncode": executed["returncode"],
        "elapsed_seconds": executed["elapsed_seconds"],
        "stderr_tail": str(executed["stderr"])[-4000:],
        "metadata_ok": False,
        "segments": 0,
        "caption_fetches": [],
    }
    if executed["returncode"] != 0:
        return result
    stdout = str(executed["stdout"]).strip()
    try:
        info = json.loads(stdout)
    except Exception as exc:
        result["json_error"] = f"{type(exc).__name__}: {exc}"
        result["stdout_tail"] = stdout[-2000:]
        return result
    if not isinstance(info, Mapping):
        result["json_error"] = "yt-dlp JSON was not an object"
        return result
    result.update(
        {
            "metadata_ok": True,
            "title": str(info.get("title") or ""),
            "channel_id": str(info.get("channel_id") or info.get("uploader_id") or ""),
            "availability": str(info.get("availability") or ""),
            "live_status": str(info.get("live_status") or ""),
            "subtitle_languages": sorted(str(value) for value in (info.get("subtitles") or {}).keys()),
            "automatic_caption_languages": sorted(str(value) for value in (info.get("automatic_captions") or {}).keys()),
        }
    )
    common_headers = {"User-Agent": USER_AGENT}
    if isinstance(info.get("http_headers"), Mapping):
        common_headers.update({str(key): str(value) for key, value in info["http_headers"].items()})
    for language, generated, fmt in best_caption_formats(info)[:6]:
        headers = dict(common_headers)
        if isinstance(fmt.get("http_headers"), Mapping):
            headers.update({str(key): str(value) for key, value in fmt["http_headers"].items()})
        fetch: dict[str, Any] = {
            "language": language,
            "generated": generated,
            "ext": str(fmt.get("ext") or ""),
            "url": safe_url(str(fmt.get("url") or "")),
        }
        try:
            response = session.get(str(fmt["url"]), headers=headers, timeout=35)
            fetch.update(body_evidence(response))
            result["segments"] = max(int(result["segments"]), int(fetch.get("segments") or 0))
        except Exception as exc:
            fetch["error"] = f"{type(exc).__name__}: {exc}"[-1500:]
        result["caption_fetches"].append(fetch)
        if result["segments"] > 0:
            break
    return result


def probe_transcript_api(video_id: str) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {"provider": "youtube_transcript_api", "segments": 0}
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        api = YouTubeTranscriptApi()
        listing = api.list(video_id) if hasattr(api, "list") else YouTubeTranscriptApi.list_transcripts(video_id)
        tracks = list(listing)
        result["tracks"] = [
            {
                "language_code": str(getattr(track, "language_code", "")),
                "generated": bool(getattr(track, "is_generated", False)),
            }
            for track in tracks
        ]
        tracks.sort(
            key=lambda track: (
                0 if str(getattr(track, "language_code", "")) == "ko" else 1,
                bool(getattr(track, "is_generated", False)),
            )
        )
        for track in tracks:
            fetched = track.fetch()
            snippets = getattr(fetched, "snippets", fetched)
            result["segments"] = sum(
                bool(str(item.get("text") if isinstance(item, Mapping) else getattr(item, "text", "")).strip())
                for item in snippets
            )
            if result["segments"]:
                break
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[-4000:]
    result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def timedtext_urls(video_id: str) -> Iterable[str]:
    for host in ("https://www.youtube.com", "https://video.google.com"):
        for language in ("ko", "en"):
            for kind in (None, "asr"):
                query = {"v": video_id, "lang": language, "fmt": "json3"}
                if kind:
                    query["kind"] = kind
                yield f"{host}/api/timedtext?{urllib.parse.urlencode(query)}"


def discover_invidious(session: requests.Session) -> list[str]:
    result: list[str] = []
    try:
        response = session.get("https://api.invidious.io/instances.json", timeout=30)
        response.raise_for_status()
        for row in response.json():
            if not isinstance(row, list) or len(row) != 2 or not isinstance(row[1], Mapping):
                continue
            host, metadata = str(row[0]), row[1]
            if metadata.get("api") and str(metadata.get("type") or "https") == "https":
                result.append(f"https://{host}")
    except Exception:
        pass
    return result[:24]


def discover_piped(session: requests.Session) -> list[str]:
    result: list[str] = []
    for index_url in (
        "https://piped-instances.kavin.rocks/",
        "https://piped.video/api/v1/instances",
    ):
        try:
            response = session.get(index_url, timeout=30)
            response.raise_for_status()
            payload = response.json()
            rows = payload if isinstance(payload, list) else payload.get("instances", [])
            for row in rows:
                if not isinstance(row, Mapping):
                    continue
                value = row.get("api_url") or row.get("api") or row.get("apiUrl")
                if value and str(value).startswith("https://"):
                    result.append(str(value).rstrip("/"))
        except Exception:
            continue
    result.extend(["https://pipedapi.kavin.rocks", "https://pipedapi.adminforge.de"])
    return list(dict.fromkeys(result))[:24]


def probe_direct(video_id: str, session: requests.Session) -> dict[str, Any]:
    transcript_api = probe_transcript_api(video_id)
    result: dict[str, Any] = {
        "provider": "direct_fallbacks",
        "segments": int(transcript_api.get("segments") or 0),
        "transcript_api": transcript_api,
        "timedtext": [],
        "invidious": [],
        "piped": [],
    }
    for url in timedtext_urls(video_id):
        row: dict[str, Any] = {"url": safe_url(url)}
        try:
            response = session.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
            row.update(body_evidence(response))
            result["segments"] = max(result["segments"], int(row.get("segments") or 0))
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"[-1000:]
        result["timedtext"].append(row)
        if result["segments"] > 0:
            return result

    for instance in discover_invidious(session):
        row = {"instance": instance}
        try:
            response = session.get(f"{instance}/api/v1/captions/{video_id}", headers={"User-Agent": USER_AGENT}, timeout=20)
            row.update(body_evidence(response))
            payload = response.json() if response.ok else None
            tracks = payload.get("captions", payload) if isinstance(payload, Mapping) else payload
            row["tracks"] = len(tracks) if isinstance(tracks, list) else 0
            for track in tracks or []:
                if not isinstance(track, Mapping):
                    continue
                target = str(track.get("url") or "")
                if not target:
                    label = urllib.parse.quote(str(track.get("label") or ""))
                    target = f"{instance}/api/v1/captions/{video_id}?label={label}"
                elif target.startswith("/"):
                    target = instance + target
                evidence = body_evidence(session.get(target, headers={"User-Agent": USER_AGENT}, timeout=20))
                row["caption"] = evidence
                result["segments"] = max(result["segments"], int(evidence.get("segments") or 0))
                if result["segments"] > 0:
                    break
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"[-1000:]
        result["invidious"].append(row)
        if result["segments"] > 0:
            return result

    for instance in discover_piped(session):
        row = {"instance": instance}
        try:
            response = session.get(f"{instance}/streams/{video_id}", headers={"User-Agent": USER_AGENT}, timeout=20)
            row.update(body_evidence(response))
            payload = response.json() if response.ok else None
            tracks = payload.get("subtitles", []) if isinstance(payload, Mapping) else []
            row["tracks"] = len(tracks) if isinstance(tracks, list) else 0
            ordered = sorted(
                (track for track in tracks if isinstance(track, Mapping)),
                key=lambda track: (
                    0 if str(track.get("code") or track.get("languageCode") or "") == "ko" else 1,
                    bool(track.get("autoGenerated")),
                ),
            )
            for track in ordered:
                target = str(track.get("url") or "")
                if target.startswith("/"):
                    target = instance + target
                if not target:
                    continue
                evidence = body_evidence(session.get(target, headers={"User-Agent": USER_AGENT}, timeout=20))
                row["caption"] = evidence
                result["segments"] = max(result["segments"], int(evidence.get("segments") or 0))
                if result["segments"] > 0:
                    break
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"[-1000:]
        result["piped"].append(row)
        if result["segments"] > 0:
            return result
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile", required=True, choices=sorted((*PROFILE_CLIENTS, "direct")))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--video", action="append", default=[])
    parser.add_argument("--between-video-seconds", type=float, default=8.0)
    args = parser.parse_args(argv)

    videos: list[tuple[str, str]] = []
    if args.video:
        for raw in args.video:
            slug, video_id = raw.split(":", 1) if ":" in raw else ("custom", raw)
            videos.append((slug, video_id))
    else:
        videos.extend(DEFAULT_VIDEOS)

    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7"})
    rows: list[dict[str, Any]] = []
    try:
        for index, (slug, video_id) in enumerate(videos):
            if index:
                time.sleep(max(0.0, args.between_video_seconds))
            result = probe_direct(video_id, session) if args.profile == "direct" else probe_ytdlp(video_id, args.profile, session)
            rows.append({"channel_slug": slug, "video_id": video_id, "result": result})
    finally:
        session.close()

    payload = {
        "schema_version": 1,
        "profile": args.profile,
        "runner": {
            "platform": platform.platform(),
            "python": sys.version,
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_sha": os.environ.get("GITHUB_SHA"),
        },
        "videos": rows,
        "recovered_video_count": sum(int(row["result"].get("segments") or 0) > 0 for row in rows),
    }
    payload["payload_sha256"] = sha256_bytes(canonical_json(payload).encode("utf-8"))
    destination = args.output / "probe.json"
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
