#!/usr/bin/env python3
"""Probe raw Innertube player clients for public caption tracks.

This intentionally bypasses yt-dlp's final extraction decision and records the
unmodified player playability/caption surface for a known-positive control plus
one representative public video from each target channel.  It does not use
credentials, cookies, restricted media, or private interfaces.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import time
from pathlib import Path
from typing import Any, Mapping

from curl_cffi import requests


VIDEOS = {
    "known_positive_control": "F6wDs1HRTSo",
    "swipalnam": "-Tp2fhvVVGM",
    "chartbro": "0h9lpMUBSlE",
    "indicator_sensei": "2U0s_i07vMY",
}

FALLBACK_CLIENTS: dict[str, dict[str, Any]] = {
    "web": {
        "clientName": "WEB",
        "clientVersion": "2.20260720.01.00",
        "api_key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        "client_id": "1",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36",
    },
    "mweb": {
        "clientName": "MWEB",
        "clientVersion": "2.20260720.01.00",
        "api_key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        "client_id": "2",
        "user_agent": "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 Chrome/136 Mobile Safari/537.36",
    },
    "android": {
        "clientName": "ANDROID",
        "clientVersion": "20.28.35",
        "androidSdkVersion": 35,
        "osName": "Android",
        "osVersion": "15",
        "hl": "ko",
        "gl": "KR",
        "api_key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        "client_id": "3",
        "user_agent": "com.google.android.youtube/20.28.35 (Linux; U; Android 15) gzip",
    },
    "android_vr": {
        "clientName": "ANDROID_VR",
        "clientVersion": "1.60.19",
        "androidSdkVersion": 32,
        "osName": "Android",
        "osVersion": "12L",
        "hl": "ko",
        "gl": "KR",
        "api_key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        "client_id": "28",
        "user_agent": "com.google.android.apps.youtube.vr.oculus/1.60.19 (Linux; U; Android 12L) gzip",
    },
    "ios": {
        "clientName": "IOS",
        "clientVersion": "20.28.1",
        "deviceMake": "Apple",
        "deviceModel": "iPhone16,2",
        "osName": "iPhone",
        "osVersion": "18.5.0.22F76",
        "hl": "ko",
        "gl": "KR",
        "api_key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        "client_id": "5",
        "user_agent": "com.google.ios.youtube/20.28.1 (iPhone16,2; U; CPU iOS 18_5 like Mac OS X; ko_KR)",
    },
    "tv": {
        "clientName": "TVHTML5",
        "clientVersion": "7.20260720.18.00",
        "hl": "ko",
        "gl": "KR",
        "api_key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        "client_id": "7",
        "user_agent": "Mozilla/5.0 (ChromiumStylePlatform) Cobalt/Version",
    },
    "tv_embedded": {
        "clientName": "TVHTML5_SIMPLY_EMBEDDED_PLAYER",
        "clientVersion": "2.0",
        "hl": "ko",
        "gl": "KR",
        "api_key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        "client_id": "85",
        "user_agent": "Mozilla/5.0 (ChromiumStylePlatform) Cobalt/Version",
        "third_party": True,
    },
    "web_embedded": {
        "clientName": "WEB_EMBEDDED_PLAYER",
        "clientVersion": "1.20260720.00.00",
        "hl": "ko",
        "gl": "KR",
        "api_key": "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8",
        "client_id": "56",
        "user_agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36",
        "third_party": True,
    },
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def visitor_data(session: requests.Session) -> str | None:
    try:
        response = session.get(
            "https://www.youtube.com/?hl=ko&gl=KR",
            headers={"Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7"},
            timeout=30,
        )
    except Exception:
        return None
    patterns = (
        r'"VISITOR_DATA":"([^"]+)"',
        r'"visitorData":"([^"]+)"',
        r'VISITOR_DATA\\x22:\\x22([^\\]+)',
    )
    for pattern in patterns:
        match = re.search(pattern, response.text)
        if match:
            return match.group(1).replace("\\u003d", "=")
    return None


def dynamic_clients() -> dict[str, dict[str, Any]]:
    """Read current yt-dlp client constants when available, retaining safe fallbacks."""
    result = {name: dict(row) for name, row in FALLBACK_CLIENTS.items()}
    try:
        import yt_dlp.extractor.youtube._base as base  # type: ignore
    except Exception:
        return result
    candidates: list[Mapping[str, Any]] = []
    for name in dir(base):
        value = getattr(base, name, None)
        if isinstance(value, Mapping) and "CLIENT" in name.upper():
            candidates.append(value)
    aliases = {
        "web": ("web",),
        "mweb": ("mweb",),
        "android": ("android",),
        "android_vr": ("android_vr",),
        "ios": ("ios",),
        "tv": ("tv",),
        "tv_embedded": ("tv_embedded", "tv_simply_embedded"),
        "web_embedded": ("web_embedded",),
    }
    for mapping in candidates:
        for output_name, keys in aliases.items():
            for key in keys:
                raw = mapping.get(key)
                if not isinstance(raw, Mapping):
                    continue
                context = raw.get("INNERTUBE_CONTEXT") or raw.get("innertube_context")
                client = context.get("client") if isinstance(context, Mapping) else None
                if isinstance(client, Mapping) and client.get("clientName") and client.get("clientVersion"):
                    merged = dict(result[output_name])
                    merged.update(dict(client))
                    api_key = raw.get("INNERTUBE_API_KEY") or raw.get("innertube_api_key")
                    if api_key:
                        merged["api_key"] = api_key
                    client_id = raw.get("INNERTUBE_CONTEXT_CLIENT_NAME") or raw.get("innertube_context_client_name")
                    if client_id:
                        merged["client_id"] = str(client_id)
                    user_agent = raw.get("INNERTUBE_CONTEXT_CLIENT_VERSION")
                    if raw.get("user_agent"):
                        merged["user_agent"] = raw["user_agent"]
                    result[output_name] = merged
                    break
    return result


def text_from_json3(payload: Any) -> tuple[int, int]:
    if not isinstance(payload, Mapping):
        return 0, 0
    segments = 0
    characters = 0
    for event in payload.get("events", []) or []:
        if not isinstance(event, Mapping):
            continue
        text = "".join(
            str(part.get("utf8") or "")
            for part in event.get("segs", []) or []
            if isinstance(part, Mapping)
        ).strip()
        if text:
            segments += 1
            characters += len(text)
    return segments, characters


def probe_one(
    session: requests.Session,
    client_key: str,
    config: Mapping[str, Any],
    video_id: str,
    visitor: str | None,
) -> dict[str, Any]:
    client = {
        key: value
        for key, value in config.items()
        if key not in {"api_key", "client_id", "user_agent", "third_party"}
    }
    client.setdefault("hl", "ko")
    client.setdefault("gl", "KR")
    if visitor:
        client["visitorData"] = visitor
    context: dict[str, Any] = {"client": client}
    if config.get("third_party"):
        context["thirdParty"] = {"embedUrl": "https://www.google.com/"}
    body = {
        "context": context,
        "videoId": video_id,
        "contentCheckOk": True,
        "racyCheckOk": True,
        "playbackContext": {"contentPlaybackContext": {"html5Preference": "HTML5_PREF_WANTS"}},
    }
    api_key = str(config.get("api_key") or FALLBACK_CLIENTS["web"]["api_key"])
    headers = {
        "Content-Type": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        "Origin": "https://www.youtube.com",
        "User-Agent": str(config.get("user_agent") or FALLBACK_CLIENTS["web"]["user_agent"]),
        "X-Youtube-Client-Name": str(config.get("client_id") or "1"),
        "X-Youtube-Client-Version": str(client.get("clientVersion")),
    }
    if visitor:
        headers["X-Goog-Visitor-Id"] = visitor
    started = time.monotonic()
    try:
        response = session.post(
            f"https://www.youtube.com/youtubei/v1/player?key={api_key}&prettyPrint=false",
            headers=headers,
            json=body,
            timeout=45,
        )
        status_code = response.status_code
        payload = response.json()
    except Exception as exc:
        return {
            "client": client_key,
            "video_id": video_id,
            "elapsed_seconds": round(time.monotonic() - started, 3),
            "exception": f"{type(exc).__name__}: {exc}",
        }
    playability = payload.get("playabilityStatus") if isinstance(payload, Mapping) else {}
    captions = payload.get("captions") if isinstance(payload, Mapping) else {}
    renderer = captions.get("playerCaptionsTracklistRenderer") if isinstance(captions, Mapping) else {}
    tracks = renderer.get("captionTracks") if isinstance(renderer, Mapping) else []
    translated_languages = renderer.get("translationLanguages") if isinstance(renderer, Mapping) else []
    track_rows: list[dict[str, Any]] = []
    for track in tracks or []:
        if not isinstance(track, Mapping):
            continue
        base_url = str(track.get("baseUrl") or "")
        segments = 0
        characters = 0
        caption_status = None
        if base_url:
            separator = "&" if "?" in base_url else "?"
            try:
                caption_response = session.get(
                    base_url + separator + "fmt=json3",
                    headers={"User-Agent": headers["User-Agent"], "Accept-Language": headers["Accept-Language"]},
                    timeout=35,
                )
                caption_status = caption_response.status_code
                if caption_response.status_code == 200:
                    segments, characters = text_from_json3(caption_response.json())
            except Exception as exc:
                caption_status = f"{type(exc).__name__}: {exc}"
        track_rows.append({
            "language_code": track.get("languageCode"),
            "kind": track.get("kind"),
            "is_translatable": track.get("isTranslatable"),
            "name": track.get("name"),
            "vss_id": track.get("vssId"),
            "caption_http_status": caption_status,
            "segments": segments,
            "characters": characters,
            "base_url_sha256": hashlib.sha256(base_url.encode()).hexdigest() if base_url else None,
        })
    return {
        "client": client_key,
        "video_id": video_id,
        "http_status": status_code,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "playability_status": playability.get("status") if isinstance(playability, Mapping) else None,
        "playability_reason": playability.get("reason") if isinstance(playability, Mapping) else None,
        "playability_messages": playability.get("messages") if isinstance(playability, Mapping) else None,
        "video_title": ((payload.get("videoDetails") or {}).get("title") if isinstance(payload, Mapping) else None),
        "caption_track_count": len(track_rows),
        "translation_language_count": len(translated_languages or []),
        "tracks": track_rows,
        "response_sha256": hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runner-key", default=platform.system())
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    session = requests.Session(impersonate="chrome")
    visitor = visitor_data(session)
    clients = dynamic_clients()
    rows: list[dict[str, Any]] = []
    for channel, video_id in VIDEOS.items():
        for client_key, config in clients.items():
            result = probe_one(session, client_key, config, video_id, visitor)
            result["channel"] = channel
            rows.append(result)
            time.sleep(0.25)
    recovered = [
        row for row in rows
        if any(int(track.get("segments") or 0) > 0 for track in row.get("tracks", []))
    ]
    positive_control = [row for row in recovered if row.get("channel") == "known_positive_control"]
    target_recovered = [row for row in recovered if row.get("channel") != "known_positive_control"]
    payload = {
        "schema_version": 1,
        "runner_key": args.runner_key,
        "runner": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_sha": os.environ.get("GITHUB_SHA"),
        },
        "visitor_data_present": bool(visitor),
        "client_count": len(clients),
        "row_count": len(rows),
        "positive_control_pass": bool(positive_control),
        "target_recovered_count": len(target_recovered),
        "recovered": recovered,
        "rows": rows,
    }
    payload["payload_sha256_before_field"] = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "positive_control_pass": payload["positive_control_pass"],
        "target_recovered_count": payload["target_recovered_count"],
        "recovered": recovered,
    }, ensure_ascii=False, indent=2))
    return 0 if positive_control else 2


if __name__ == "__main__":
    raise SystemExit(main())
