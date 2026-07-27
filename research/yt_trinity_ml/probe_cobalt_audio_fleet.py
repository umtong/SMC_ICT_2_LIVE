#!/usr/bin/env python3
"""Discover and validate public Cobalt-compatible YouTube audio instances."""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import requests


CONTROL = ("known_positive_control", "F6wDs1HRTSo")
TARGETS = (
    ("swipalnam", "-Tp2fhvVVGM"),
    ("chartbro", "0h9lpMUBSlE"),
    ("indicator_sensei", "2U0s_i07vMY"),
)
DISCOVERY_URLS = (
    "https://instances.cobalt.best/instances.json",
    "https://instances.cobalt.best/api/instances.json",
    "https://raw.githubusercontent.com/imputnet/cobalt/main/docs/instances.md",
    "https://raw.githubusercontent.com/imputnet/cobalt/main/docs/run-an-instance.md",
    "https://raw.githubusercontent.com/imputnet/cobalt-instances/main/instances.json",
)
STATIC_BASES = (
    "https://api.cobalt.tools",
    "https://cobalt-api.kwiatekmiki.com",
    "https://cobalt.api.timelessnesses.me",
    "https://api.cobalt.best",
)


def normalize_base(value: str) -> str | None:
    value = str(value or "").strip().rstrip("/")
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        value = "https://" + value
    parsed = urlparse(value)
    if not parsed.hostname or parsed.scheme not in {"http", "https"}:
        return None
    if any(token in parsed.hostname.lower() for token in ("github", "discord", "localhost")):
        return None
    return f"{parsed.scheme}://{parsed.netloc}"


def walk_strings(value: Any) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield from walk_strings(key)
            yield from walk_strings(item)
    elif isinstance(value, Iterable) and not isinstance(value, (bytes, bytearray)):
        for item in value:
            yield from walk_strings(item)


def discover(session: requests.Session) -> tuple[list[str], list[dict[str, Any]]]:
    bases = {base for base in STATIC_BASES}
    ledger: list[dict[str, Any]] = []
    pattern = re.compile(r"https?://[A-Za-z0-9._:-]+")
    for url in DISCOVERY_URLS:
        row: dict[str, Any] = {"url": url}
        try:
            response = session.get(url, timeout=25, headers={"User-Agent": "SMC-ICT-2-LIVE/1.0"})
            row.update({"status_code": response.status_code, "bytes": len(response.content)})
            values: list[str] = []
            try:
                payload = response.json()
                values.extend(walk_strings(payload))
            except Exception:
                values.extend(pattern.findall(response.text))
            added = []
            for value in values:
                for candidate in pattern.findall(value) or [value]:
                    base = normalize_base(candidate)
                    if base and base not in bases:
                        bases.add(base)
                        added.append(base)
            row["added"] = sorted(added)
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
        ledger.append(row)
    return sorted(bases)[:150], ledger


def media_urls(payload: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(payload, Mapping):
        for key in ("url", "audio", "audioUrl", "downloadUrl", "stream", "streamUrl"):
            value = payload.get(key)
            if isinstance(value, str) and value.startswith("http"):
                urls.append(value)
        picker = payload.get("picker")
        if isinstance(picker, list):
            for item in picker:
                urls.extend(media_urls(item))
        for value in payload.values():
            if isinstance(value, (Mapping, list)):
                urls.extend(media_urls(value))
    elif isinstance(payload, list):
        for item in payload:
            urls.extend(media_urls(item))
    return list(dict.fromkeys(urls))


def validate_media(session: requests.Session, url: str) -> dict[str, Any]:
    try:
        response = session.get(
            url,
            timeout=35,
            stream=True,
            allow_redirects=True,
            headers={"User-Agent": "SMC-ICT-2-LIVE/1.0", "Range": "bytes=0-262143"},
        )
        raw = b""
        for chunk in response.iter_content(65_536):
            if chunk:
                raw += chunk
            if len(raw) >= 262_144:
                raw = raw[:262_144]
                break
        content_type = str(response.headers.get("content-type") or "").lower()
        media_magic = raw.startswith((b"OggS", b"ID3", b"\xff\xfb", b"\x1aE\xdf\xa3", b"ftyp")) or b"ftyp" in raw[:64]
        html = b"<html" in raw[:1000].lower() or b"<!doctype" in raw[:1000].lower()
        usable = response.status_code in {200, 206} and len(raw) >= 16_384 and not html and ("audio" in content_type or "video" in content_type or "octet-stream" in content_type or media_magic)
        return {
            "url": url,
            "final_url": response.url,
            "status_code": response.status_code,
            "content_type": content_type,
            "sample_bytes": len(raw),
            "sample_sha256": hashlib.sha256(raw).hexdigest() if raw else None,
            "media_magic": media_magic,
            "html": html,
            "usable": usable,
        }
    except Exception as exc:
        return {"url": url, "error": f"{type(exc).__name__}: {exc}", "usable": False}


def request_variants(base: str, video_id: str):
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    payloads = (
        {"url": video_url, "downloadMode": "audio", "audioFormat": "opus", "filenameStyle": "basic"},
        {"url": video_url, "downloadMode": "audio", "audioFormat": "mp3", "filenameStyle": "basic"},
        {"url": video_url, "isAudioOnly": True, "aFormat": "opus", "filenamePattern": "basic"},
        {"url": video_url, "isAudioOnly": True, "aFormat": "mp3", "filenamePattern": "basic"},
    )
    endpoints = ("/", "/api/json", "/api", "/api/v1")
    for endpoint in endpoints:
        for payload in payloads:
            yield base.rstrip("/") + endpoint, payload


def probe_one(base: str, label: str, video_id: str) -> dict[str, Any]:
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-LIVE/1.0", "Accept": "application/json"})
    attempts = []
    for endpoint, payload in request_variants(base, video_id):
        row: dict[str, Any] = {"endpoint": endpoint, "payload": payload}
        try:
            response = session.post(endpoint, json=payload, timeout=45, allow_redirects=True)
            row.update({
                "status_code": response.status_code,
                "content_type": response.headers.get("content-type"),
                "bytes": len(response.content),
                "body_prefix": response.text[:1500],
            })
            try:
                result = response.json()
                row["json"] = result
            except Exception:
                result = None
            urls = media_urls(result)
            row["media_urls"] = urls[:10]
            validations = [validate_media(session, url) for url in urls[:3]]
            row["media_validations"] = validations
            attempts.append(row)
            usable = next((item for item in validations if item.get("usable")), None)
            if usable:
                return {
                    "base": base,
                    "label": label,
                    "video_id": video_id,
                    "usable": True,
                    "endpoint": endpoint,
                    "request_payload": payload,
                    "media": usable,
                    "attempts": attempts,
                }
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {exc}"
            attempts.append(row)
    return {"base": base, "label": label, "video_id": video_id, "usable": False, "attempts": attempts}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=16)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    bases, discovery = discover(session)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        control_rows = list(pool.map(lambda base: probe_one(base, *CONTROL), bases))
    eligible = [row for row in control_rows if row.get("usable")]
    target_rows = []
    if eligible:
        work = [(row["base"], label, video_id) for row in eligible for label, video_id in TARGETS]
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(max(1, args.workers), len(work))) as pool:
            target_rows = list(pool.map(lambda item: probe_one(*item), work))
    by_base: dict[str, dict[str, Any]] = {}
    for row in eligible:
        by_base[row["base"]] = {"control": row, "targets": []}
    for row in target_rows:
        by_base.setdefault(row["base"], {"control": None, "targets": []})["targets"].append(row)
    winners = []
    for base, bundle in by_base.items():
        target_success = sum(bool(row.get("usable")) for row in bundle["targets"])
        if target_success:
            winners.append({"base": base, "target_success_count": target_success, **bundle})
    winners.sort(key=lambda row: (row["target_success_count"], row["base"]), reverse=True)
    result = {
        "schema_version": 1,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "source_sha": os.environ.get("GITHUB_SHA"),
        "discovered_base_count": len(bases),
        "discovery": discovery,
        "control_success_count": len(eligible),
        "winner_count": len(winners),
        "winners": winners,
        "control_rows": control_rows,
        "target_rows": target_rows,
        "decision": "COBALT_AUDIO_WINNER_FOUND" if winners else "NO_COBALT_AUDIO_WINNER",
    }
    result["payload_sha256_before_field"] = hashlib.sha256(
        json.dumps(result, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    (args.output / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if winners:
        winner = {
            "schema_version": 1,
            "run_id": result["run_id"],
            "source_sha": result["source_sha"],
            "decision": result["decision"],
            "winner": winners[0],
            "result_sha256": hashlib.sha256((args.output / "result.json").read_bytes()).hexdigest(),
        }
        (args.output / "winner.json").write_text(json.dumps(winner, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"decision": result["decision"], "bases": len(bases), "controls": len(eligible), "winners": len(winners)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
