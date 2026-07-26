#!/usr/bin/env python3
"""Probe public YouTube caption tracks through coherent InnerTube clients.

This transport does not download video/audio media and uses only the public player
response and caption-track URLs exposed by YouTube. The probe is intentionally
small and evidence-oriented: it records playability, track counts, segment counts,
text hashes, and bounded excerpts without treating transport failure as no-caption.
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import html
import json
import os
import platform
import re
import sys
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

API_KEY = "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"
PLAYER_ENDPOINT = "https://www.youtube.com/youtubei/v1/player"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")
DEFAULT_VIDEOS: tuple[tuple[str, str], ...] = (
    ("chartbro", "0h9lpMUBSlE"),
    ("swipalnam", "-Tp2fhvVVGM"),
    ("indicator_sensei", "2U0s_i07vMY"),
    ("known_previous_success", "F6wDs1HRTSo"),
)


@dataclasses.dataclass(frozen=True)
class ClientProfile:
    name: str
    version: str
    client_id: str
    user_agent: str
    extra: Mapping[str, Any] = dataclasses.field(default_factory=dict)


CLIENTS: tuple[ClientProfile, ...] = (
    ClientProfile(
        name="ANDROID_VR",
        version="1.61.48",
        client_id="28",
        user_agent=(
            "com.google.android.apps.youtube.vr.oculus/1.61.48 "
            "(Linux; U; Android 12L; eureka-user Build/SQ3A.220605.009.A1) gzip"
        ),
        extra={
            "androidSdkVersion": 32,
            "deviceMake": "Oculus",
            "deviceModel": "Quest 3",
            "osName": "Android",
            "osVersion": "12L",
        },
    ),
    ClientProfile(
        name="IOS",
        version="20.10.4",
        client_id="5",
        user_agent=(
            "com.google.ios.youtube/20.10.4 "
            "(iPhone16,2; U; CPU iOS 18_3_2 like Mac OS X)"
        ),
        extra={
            "deviceMake": "Apple",
            "deviceModel": "iPhone16,2",
            "osName": "iPhone",
            "osVersion": "18.3.2.22D82",
        },
    ),
    ClientProfile(
        name="TVHTML5_SIMPLY_EMBEDDED_PLAYER",
        version="2.0",
        client_id="85",
        user_agent=(
            "Mozilla/5.0 (PlayStation; PlayStation 4/12.00) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.0 Safari/605.1.15"
        ),
    ),
    ClientProfile(
        name="MWEB",
        version="2.20250606.01.00",
        client_id="2",
        user_agent=(
            "Mozilla/5.0 (iPhone; CPU iPhone OS 18_3 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
            "Mobile/15E148 Safari/604.1"
        ),
    ),
)


@dataclasses.dataclass(frozen=True)
class Segment:
    start_ms: int
    duration_ms: int
    text: str

    def as_dict(self) -> dict[str, Any]:
        return dataclasses.asdict(self)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def clean_text(value: str) -> str:
    text = html.unescape(value or "")
    text = TAG_RE.sub("", text)
    text = text.replace("\u200b", " ").replace("\ufeff", " ")
    return WS_RE.sub(" ", text).strip()


def normalize_segments(values: Iterable[Segment]) -> list[Segment]:
    rows: list[Segment] = []
    seen: set[tuple[int, int, str]] = set()
    for item in sorted(values, key=lambda row: (row.start_ms, row.duration_ms, row.text)):
        text = clean_text(item.text)
        key = (max(0, int(item.start_ms)), max(0, int(item.duration_ms)), text)
        if not text or key in seen:
            continue
        seen.add(key)
        if rows and rows[-1].text == text and abs(rows[-1].start_ms - key[0]) <= 40:
            continue
        rows.append(Segment(*key))
    return rows


def parse_json3(payload: Mapping[str, Any]) -> list[Segment]:
    rows: list[Segment] = []
    for event in payload.get("events", []) or []:
        if not isinstance(event, Mapping):
            continue
        text = "".join(
            str(segment.get("utf8") or "")
            for segment in (event.get("segs") or [])
            if isinstance(segment, Mapping)
        )
        text = clean_text(text)
        if text:
            rows.append(
                Segment(
                    int(float(event.get("tStartMs") or 0)),
                    int(float(event.get("dDurationMs") or 0)),
                    text,
                )
            )
    return normalize_segments(rows)


def parse_xml(text: str) -> list[Segment]:
    root = ET.fromstring(text)
    rows: list[Segment] = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] not in {"text", "p"}:
            continue
        caption = clean_text("".join(node.itertext()))
        if not caption:
            continue
        if "start" in node.attrib:
            start_ms = round(float(node.attrib.get("start", "0")) * 1000)
            duration_ms = round(float(node.attrib.get("dur", "0")) * 1000)
        else:
            start_ms = int(float(node.attrib.get("t", "0")))
            duration_ms = int(float(node.attrib.get("d", "0")))
        rows.append(Segment(start_ms, duration_ms, caption))
    return normalize_segments(rows)


def safe_url(value: str) -> dict[str, str]:
    parsed = urllib.parse.urlsplit(value)
    return {"scheme": parsed.scheme, "host": parsed.netloc, "path": parsed.path}


def request_headers(profile: ClientProfile) -> dict[str, str]:
    return {
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        "Content-Type": "application/json",
        "Cookie": "CONSENT=YES+cb.20210328-17-p0.en+FX+000",
        "Origin": "https://www.youtube.com",
        "User-Agent": profile.user_agent,
        "X-YouTube-Client-Name": profile.client_id,
        "X-YouTube-Client-Version": profile.version,
    }


def player_payload(video_id: str, profile: ClientProfile) -> dict[str, Any]:
    client: dict[str, Any] = {
        "clientName": profile.name,
        "clientVersion": profile.version,
        "hl": "ko",
        "gl": "KR",
    }
    client.update(profile.extra)
    return {
        "context": {"client": client},
        "videoId": video_id,
        "contentCheckOk": True,
        "racyCheckOk": True,
    }


def nested_mapping(value: Any, *keys: str) -> Mapping[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return current if isinstance(current, Mapping) else {}


def caption_tracks(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    renderer = nested_mapping(payload, "captions", "playerCaptionsTracklistRenderer")
    rows = renderer.get("captionTracks") or []
    return [row for row in rows if isinstance(row, Mapping) and row.get("baseUrl")]


def track_score(track: Mapping[str, Any]) -> tuple[int, int, str]:
    language = str(track.get("languageCode") or "")
    generated = str(track.get("kind") or "") == "asr"
    if language == "ko":
        language_score = 0
    elif language.startswith("ko-") or language.startswith("ko_"):
        language_score = 1
    elif language == "en":
        language_score = 2
    elif language.startswith("en-") or language.startswith("en_"):
        language_score = 3
    else:
        language_score = 10
    return language_score, 1 if generated else 0, language


def caption_url(base_url: str, fmt: str | None = "json3") -> str:
    parsed = urllib.parse.urlsplit(base_url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    query = [(key, value) for key, value in query if key != "fmt"]
    if fmt:
        query.append(("fmt", fmt))
    return urllib.parse.urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urllib.parse.urlencode(query), parsed.fragment)
    )


def fetch_segments(
    session: requests.Session,
    track: Mapping[str, Any],
    profile: ClientProfile,
    timeout: float,
) -> tuple[list[Segment], dict[str, Any]]:
    base_url = str(track.get("baseUrl") or "")
    if not base_url:
        raise ValueError("caption track has no baseUrl")
    if "exp=xpe" in base_url:
        raise RuntimeError("caption URL requires Proof of Origin Token")
    headers = request_headers(profile)
    headers.pop("Content-Type", None)
    attempts: list[dict[str, Any]] = []
    for fmt in ("json3", None):
        url = caption_url(base_url, fmt)
        started = time.monotonic()
        response = session.get(url, headers=headers, timeout=timeout)
        row: dict[str, Any] = {
            "format_requested": fmt or "original",
            "http_status": response.status_code,
            "bytes": len(response.content),
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "content_type": response.headers.get("content-type", ""),
            "url": safe_url(response.url),
            "body_sha256": sha256_bytes(response.content),
        }
        attempts.append(row)
        response.raise_for_status()
        stripped = response.text.lstrip()
        segments: list[Segment]
        if fmt == "json3" or "json" in row["content_type"] or stripped.startswith("{"):
            try:
                segments = parse_json3(response.json())
            except Exception as exc:
                row["parse_error"] = f"{type(exc).__name__}: {exc}"[-1000:]
                segments = []
        elif stripped.startswith("<"):
            try:
                segments = parse_xml(response.text)
            except Exception as exc:
                row["parse_error"] = f"{type(exc).__name__}: {exc}"[-1000:]
                segments = []
        else:
            segments = []
        row["segment_count"] = len(segments)
        if segments:
            return segments, {"attempts": attempts}
    raise RuntimeError("caption URL returned no parseable segments: " + canonical_json(attempts))


def probe_client(
    session: requests.Session,
    video_id: str,
    profile: ClientProfile,
    timeout: float,
) -> dict[str, Any]:
    started = time.monotonic()
    result: dict[str, Any] = {
        "client": profile.name,
        "client_version": profile.version,
        "client_id": profile.client_id,
        "track_count": 0,
        "segment_count": 0,
    }
    try:
        response = session.post(
            PLAYER_ENDPOINT,
            params={"key": API_KEY},
            headers=request_headers(profile),
            json=player_payload(video_id, profile),
            timeout=timeout,
        )
        result.update(
            {
                "player_http_status": response.status_code,
                "player_bytes": len(response.content),
                "player_body_sha256": sha256_bytes(response.content),
                "player_content_type": response.headers.get("content-type", ""),
            }
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, Mapping):
            raise TypeError("player response is not an object")
        playability = nested_mapping(payload, "playabilityStatus")
        details = nested_mapping(payload, "videoDetails")
        result.update(
            {
                "playability_status": str(playability.get("status") or ""),
                "playability_reason": str(playability.get("reason") or ""),
                "title": str(details.get("title") or ""),
                "author": str(details.get("author") or ""),
            }
        )
        tracks = sorted(caption_tracks(payload), key=track_score)
        result["track_count"] = len(tracks)
        result["tracks"] = [
            {
                "language_code": str(track.get("languageCode") or ""),
                "generated": str(track.get("kind") or "") == "asr",
                "translatable": bool(track.get("isTranslatable")),
                "url": safe_url(str(track.get("baseUrl") or "")),
                "protected_xpe": "exp=xpe" in str(track.get("baseUrl") or ""),
            }
            for track in tracks
        ]
        if result["playability_status"] not in {"", "OK"}:
            return result
        errors: list[str] = []
        for track in tracks:
            try:
                segments, evidence = fetch_segments(session, track, profile, timeout)
                text = " ".join(segment.text for segment in segments)
                result.update(
                    {
                        "segment_count": len(segments),
                        "text_characters": len(text),
                        "text_sha256": sha256_bytes(text.encode("utf-8")),
                        "language_code": str(track.get("languageCode") or ""),
                        "generated": str(track.get("kind") or "") == "asr",
                        "first_segments": [segment.as_dict() for segment in segments[:4]],
                        "caption_fetch": evidence,
                    }
                )
                return result
            except Exception as exc:
                errors.append(
                    f"{track.get('languageCode', '')}/{track.get('kind', '')}:"
                    f"{type(exc).__name__}:{exc}"
                )
        if errors:
            result["caption_errors"] = errors[-8:]
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[-4000:]
    finally:
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return result


def probe_video(
    session: requests.Session,
    slug: str,
    video_id: str,
    timeout: float,
    between_clients_seconds: float,
) -> dict[str, Any]:
    if not VIDEO_ID_RE.fullmatch(video_id):
        return {"channel_slug": slug, "video_id": video_id, "error": "invalid video id", "attempts": []}
    attempts: list[dict[str, Any]] = []
    for index, profile in enumerate(CLIENTS):
        if index and between_clients_seconds > 0:
            time.sleep(between_clients_seconds)
        row = probe_client(session, video_id, profile, timeout)
        attempts.append(row)
        if int(row.get("segment_count") or 0) > 0:
            break
    best = max(attempts, key=lambda row: int(row.get("segment_count") or 0), default={})
    return {
        "channel_slug": slug,
        "video_id": video_id,
        "recovered": int(best.get("segment_count") or 0) > 0,
        "winning_client": best.get("client") if int(best.get("segment_count") or 0) > 0 else None,
        "segment_count": int(best.get("segment_count") or 0),
        "attempts": attempts,
    }


def self_test() -> None:
    payload = {
        "events": [
            {"tStartMs": 1000, "dDurationMs": 500, "segs": [{"utf8": " 안녕 "}]},
            {"tStartMs": 2000, "dDurationMs": 750, "segs": [{"utf8": "세계"}]},
        ]
    }
    rows = parse_json3(payload)
    assert [row.text for row in rows] == ["안녕", "세계"]
    assert rows[0].start_ms == 1000 and rows[1].duration_ms == 750
    track = {"languageCode": "ko", "kind": "asr"}
    assert track_score(track)[:2] == (0, 1)
    url = caption_url("https://example.test/timedtext?v=x&fmt=srv3", "json3")
    assert urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["fmt"] == ["json3"]
    assert caption_tracks(
        {"captions": {"playerCaptionsTracklistRenderer": {"captionTracks": [{"baseUrl": "x"}]}}}
    )


def parse_videos(raw_values: Sequence[str]) -> list[tuple[str, str]]:
    if not raw_values:
        return list(DEFAULT_VIDEOS)
    rows: list[tuple[str, str]] = []
    for raw in raw_values:
        slug, video_id = raw.split(":", 1) if ":" in raw else ("custom", raw)
        rows.append((slug, video_id))
    return rows


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=False)
    parser.add_argument("--video", action="append", default=[])
    parser.add_argument("--timeout-seconds", type=float, default=35.0)
    parser.add_argument("--between-clients-seconds", type=float, default=1.0)
    parser.add_argument("--between-videos-seconds", type=float, default=3.0)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        self_test()
        print("multiclient innertube probe self-test: ok")
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")

    videos = parse_videos(args.video)
    session = requests.Session()
    rows: list[dict[str, Any]] = []
    try:
        for index, (slug, video_id) in enumerate(videos):
            if index and args.between_videos_seconds > 0:
                time.sleep(args.between_videos_seconds)
            rows.append(
                probe_video(
                    session,
                    slug,
                    video_id,
                    args.timeout_seconds,
                    args.between_clients_seconds,
                )
            )
    finally:
        session.close()

    payload: dict[str, Any] = {
        "schema_version": 1,
        "transport": "coherent_multiclient_innertube",
        "source_reference": "edouard-claude/yt-transcript main.go (adapted and independently tested)",
        "runner": {
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_sha": os.environ.get("GITHUB_SHA"),
            "platform": platform.platform(),
            "python": sys.version,
        },
        "clients": [dataclasses.asdict(profile) for profile in CLIENTS],
        "videos": rows,
        "recovered_video_count": sum(bool(row.get("recovered")) for row in rows),
        "total_segment_count": sum(int(row.get("segment_count") or 0) for row in rows),
    }
    payload["payload_sha256"] = sha256_bytes(canonical_json(payload).encode("utf-8"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
