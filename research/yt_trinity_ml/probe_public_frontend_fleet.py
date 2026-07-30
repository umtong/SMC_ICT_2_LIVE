#!/usr/bin/env python3
"""Probe the live public Piped/Invidious fleet for caption or audio access.

Only public, unauthenticated API surfaces are used.  A provider is eligible for
full-corpus work only when a known-positive caption control is fetched and the
same instance returns a usable surface for target-channel samples.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import platform
import time
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

import requests


VIDEOS = {
    "known_positive_control": "F6wDs1HRTSo",
    "swipalnam": "-Tp2fhvVVGM",
    "chartbro": "0h9lpMUBSlE",
    "indicator_sensei": "2U0s_i07vMY",
}

STATIC_PIPED = {
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://pipedapi.reallyaweso.me",
    "https://pipedapi.privacy.com.de",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.drgns.space",
    "https://pipedapi.r4fo.com",
    "https://pipedapi-libre.kavin.rocks",
    "https://pipedapi.owo.si",
    "https://pipedapi.darkness.services",
}

STATIC_INVIDIOUS = {
    "https://yewtu.be",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://inv.us.projectsegfau.lt",
    "https://invidious.privacyredirect.com",
    "https://invidious.private.coffee",
    "https://inv.tux.pizza",
    "https://invidious.jing.rocks",
    "https://invidious.fdn.fr",
    "https://invidious.0011.lt",
}


def normalized_base(value: str) -> str | None:
    value = str(value or "").strip().rstrip("/")
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    if not parsed.hostname:
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def get_json(url: str, timeout: float = 20.0) -> Any:
    response = requests.get(
        url,
        headers={"User-Agent": "SMC-ICT-2-LIVE/1.0", "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()
    return response.json()


def discover_piped() -> set[str]:
    result = set(STATIC_PIPED)
    urls = (
        "https://piped-instances.kavin.rocks/",
        "https://piped.video/api/v1/instances",
        "https://raw.githubusercontent.com/wiki/TeamPiped/Piped-Frontend/Instances.md",
    )
    for url in urls:
        try:
            response = requests.get(url, headers={"User-Agent": "SMC-ICT-2-LIVE/1.0"}, timeout=25)
            if response.status_code != 200:
                continue
            try:
                payload = response.json()
            except Exception:
                payload = None
            candidates: list[str] = []
            if isinstance(payload, list):
                for item in payload:
                    if isinstance(item, Mapping):
                        for key in ("api_url", "apiUrl", "api", "url"):
                            if item.get(key):
                                candidates.append(str(item[key]))
                    elif isinstance(item, str):
                        candidates.append(item)
            elif isinstance(payload, Mapping):
                for item in payload.values():
                    if isinstance(item, Mapping):
                        for key in ("api_url", "apiUrl", "api", "url"):
                            if item.get(key):
                                candidates.append(str(item[key]))
            else:
                for token in response.text.replace("(`", " ").replace("`", " ").split():
                    if token.startswith("https://") and "piped" in token.lower():
                        candidates.append(token.strip(" |),"))
            for candidate in candidates:
                base = normalized_base(candidate)
                if base:
                    result.add(base)
        except Exception:
            continue
    return result


def discover_invidious() -> set[str]:
    result = set(STATIC_INVIDIOUS)
    try:
        payload = get_json("https://api.invidious.io/instances.json?sort_by=health", timeout=30)
        if isinstance(payload, list):
            for item in payload:
                if not isinstance(item, list) or len(item) < 2:
                    continue
                domain, metadata = item[0], item[1]
                if isinstance(metadata, Mapping) and metadata.get("api") is False:
                    continue
                uri = metadata.get("uri") if isinstance(metadata, Mapping) else None
                base = normalized_base(str(uri or domain))
                if base:
                    result.add(base)
    except Exception:
        pass
    return result


def caption_payload(url: str) -> dict[str, Any]:
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/136 Safari/537.36",
                "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7",
            },
            timeout=25,
            allow_redirects=True,
        )
        raw = response.content[:500_000]
        text = raw.decode("utf-8", "replace")
        meaningful = " ".join(text.split())
        lowered = text.lower()
        caption_syntax = (
            "webvtt" in lowered
            or "-->" in text
            or "<text" in lowered
            or "<tt" in lowered
            or '"events"' in lowered
            or '"start_ms"' in lowered
        )
        return {
            "status": response.status_code,
            "bytes": len(raw),
            "characters": len(meaningful),
            "content_type": response.headers.get("content-type"),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "caption_syntax": caption_syntax,
            "usable": response.status_code == 200 and len(meaningful) >= 80 and caption_syntax,
        }
    except Exception as exc:
        return {"usable": False, "exception": f"{type(exc).__name__}: {exc}"}


def audio_payload(url: str) -> dict[str, Any]:
    try:
        response = requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0", "Range": "bytes=0-4095"},
            timeout=25,
            allow_redirects=True,
            stream=True,
        )
        raw = next(response.iter_content(4096), b"")
        return {
            "status": response.status_code,
            "bytes": len(raw),
            "content_type": response.headers.get("content-type"),
            "accept_ranges": response.headers.get("accept-ranges"),
            "sha256": hashlib.sha256(raw).hexdigest() if raw else None,
            "usable": response.status_code in {200, 206} and len(raw) >= 256,
        }
    except Exception as exc:
        return {"usable": False, "exception": f"{type(exc).__name__}: {exc}"}


def first_urls(rows: Iterable[Any], keys: tuple[str, ...], limit: int = 3) -> list[str]:
    result: list[str] = []
    for row in rows or []:
        if not isinstance(row, Mapping):
            continue
        for key in keys:
            value = row.get(key)
            if isinstance(value, str) and value.startswith("http"):
                result.append(value)
                break
        if len(result) >= limit:
            break
    return result


def probe_piped(base: str, video_id: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = requests.get(
            f"{base}/streams/{video_id}",
            headers={"User-Agent": "SMC-ICT-2-LIVE/1.0", "Accept": "application/json"},
            timeout=22,
        )
        status = response.status_code
        payload = response.json() if response.content else {}
    except Exception as exc:
        return {"provider": "piped", "base": base, "video_id": video_id, "exception": f"{type(exc).__name__}: {exc}", "elapsed": round(time.monotonic() - started, 3)}
    subtitles = payload.get("subtitles") if isinstance(payload, Mapping) else []
    audio = payload.get("audioStreams") if isinstance(payload, Mapping) else []
    caption_urls = first_urls(subtitles, ("url",))
    audio_urls = first_urls(audio, ("url",))
    caption_checks = [caption_payload(urljoin(base + "/", url)) for url in caption_urls]
    audio_checks = [audio_payload(url) for url in audio_urls[:1]]
    return {
        "provider": "piped",
        "base": base,
        "video_id": video_id,
        "http_status": status,
        "title": payload.get("title") if isinstance(payload, Mapping) else None,
        "subtitle_count": len(subtitles or []),
        "audio_stream_count": len(audio or []),
        "caption_checks": caption_checks,
        "audio_checks": audio_checks,
        "caption_usable": any(row.get("usable") for row in caption_checks),
        "audio_usable": any(row.get("usable") for row in audio_checks),
        "elapsed": round(time.monotonic() - started, 3),
    }


def probe_invidious(base: str, video_id: str) -> dict[str, Any]:
    started = time.monotonic()
    try:
        response = requests.get(
            f"{base}/api/v1/videos/{video_id}",
            headers={"User-Agent": "SMC-ICT-2-LIVE/1.0", "Accept": "application/json"},
            timeout=22,
        )
        status = response.status_code
        payload = response.json() if response.content else {}
    except Exception as exc:
        return {"provider": "invidious", "base": base, "video_id": video_id, "exception": f"{type(exc).__name__}: {exc}", "elapsed": round(time.monotonic() - started, 3)}
    captions = payload.get("captions") if isinstance(payload, Mapping) else []
    adaptive = payload.get("adaptiveFormats") if isinstance(payload, Mapping) else []
    audio_rows = [row for row in adaptive or [] if isinstance(row, Mapping) and str(row.get("type") or "").startswith("audio/")]
    caption_urls = first_urls(captions, ("url",))
    audio_urls = first_urls(audio_rows, ("url",))
    caption_checks = [caption_payload(urljoin(base + "/", url)) for url in caption_urls]
    audio_checks = [audio_payload(url) for url in audio_urls[:1]]
    return {
        "provider": "invidious",
        "base": base,
        "video_id": video_id,
        "http_status": status,
        "title": payload.get("title") if isinstance(payload, Mapping) else None,
        "subtitle_count": len(captions or []),
        "audio_stream_count": len(audio_rows),
        "caption_checks": caption_checks,
        "audio_checks": audio_checks,
        "caption_usable": any(row.get("usable") for row in caption_checks),
        "audio_usable": any(row.get("usable") for row in audio_checks),
        "elapsed": round(time.monotonic() - started, 3),
    }


def probe_control(item: tuple[str, str]) -> dict[str, Any]:
    provider, base = item
    video_id = VIDEOS["known_positive_control"]
    return probe_piped(base, video_id) if provider == "piped" else probe_invidious(base, video_id)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--runner-key", default=platform.system())
    parser.add_argument("--maximum-instances", type=int, default=160)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    piped = sorted(discover_piped())
    invidious = sorted(discover_invidious())
    instances = [("piped", base) for base in piped] + [("invidious", base) for base in invidious]
    instances = instances[: args.maximum_instances]
    with concurrent.futures.ThreadPoolExecutor(max_workers=28) as pool:
        controls = list(pool.map(probe_control, instances))
    eligible = [row for row in controls if row.get("caption_usable") or row.get("audio_usable")]
    target_rows: list[dict[str, Any]] = []
    work: list[tuple[str, str, str, str]] = []
    for row in eligible:
        for channel, video_id in VIDEOS.items():
            if channel == "known_positive_control":
                continue
            work.append((row["provider"], row["base"], channel, video_id))

    def probe_target(item: tuple[str, str, str, str]) -> dict[str, Any]:
        provider, base, channel, video_id = item
        row = probe_piped(base, video_id) if provider == "piped" else probe_invidious(base, video_id)
        row["channel"] = channel
        return row

    with concurrent.futures.ThreadPoolExecutor(max_workers=24) as pool:
        target_rows = list(pool.map(probe_target, work))
    by_instance: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for row in target_rows:
        by_instance.setdefault((row["provider"], row["base"]), []).append(row)
    winners: list[dict[str, Any]] = []
    for control in eligible:
        targets = by_instance.get((control["provider"], control["base"]), [])
        caption_targets = sum(bool(row.get("caption_usable")) for row in targets)
        audio_targets = sum(bool(row.get("audio_usable")) for row in targets)
        if caption_targets or audio_targets:
            winners.append({
                "provider": control["provider"],
                "base": control["base"],
                "control_caption_usable": bool(control.get("caption_usable")),
                "control_audio_usable": bool(control.get("audio_usable")),
                "target_caption_count": caption_targets,
                "target_audio_count": audio_targets,
                "control": control,
                "targets": targets,
            })
    winners.sort(
        key=lambda row: (
            row["target_caption_count"],
            row["control_caption_usable"],
            row["target_audio_count"],
            row["control_audio_usable"],
        ),
        reverse=True,
    )
    payload = {
        "schema_version": 1,
        "runner_key": args.runner_key,
        "runner": {
            "platform": platform.platform(),
            "python": platform.python_version(),
            "github_run_id": os.environ.get("GITHUB_RUN_ID"),
            "github_sha": os.environ.get("GITHUB_SHA"),
        },
        "discovered": {"piped": len(piped), "invidious": len(invidious), "total_probed": len(instances)},
        "eligible_control_instance_count": len(eligible),
        "winner_count": len(winners),
        "winners": winners,
        "control_rows": controls,
        "target_rows": target_rows,
    }
    payload["payload_sha256_before_field"] = hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"eligible": len(eligible), "winner_count": len(winners), "winners": winners[:5]}, ensure_ascii=False, indent=2))
    return 0 if winners else 2


if __name__ == "__main__":
    raise SystemExit(main())
