#!/usr/bin/env python3
"""Probe public Piped and Invidious instances for timestamped YouTube captions.

The probe is intentionally bounded to four videos: one known positive control and one
representative video per target channel. Public instance APIs are unauthenticated by
design. We stop after recovering every sample or exhausting a small, documented list,
and preserve exact transport evidence without treating network failure as no-caption.
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
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

VIDEOS: tuple[tuple[str, str], ...] = (
    ("chartbro", "0h9lpMUBSlE"),
    ("swipalnam", "-Tp2fhvVVGM"),
    ("indicator_sensei", "2U0s_i07vMY"),
    ("known_positive_control", "F6wDs1HRTSo"),
)

PIPED_INSTANCES: tuple[str, ...] = (
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.leptons.xyz",
    "https://pipedapi.nosebs.ru",
    "https://pipedapi-libre.kavin.rocks",
    "https://piped-api.privacy.com.de",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
    "https://pipedapi.drgns.space",
    "https://pipedapi.owo.si",
    "https://pipedapi.ducks.party",
    "https://piped-api.codespace.cz",
    "https://pipedapi.reallyaweso.me",
    "https://api.piped.private.coffee",
    "https://pipedapi.darkness.services",
    "https://pipedapi.orangenet.cc",
)

INVIDIOUS_INSTANCE_INDEX = "https://api.invidious.io/instances.json?sort_by=health"
USER_AGENT = "SMC-ICT-2-LIVE-alt-caption-probe/1.0"
WS_RE = re.compile(r"\s+")
TAG_RE = re.compile(r"<[^>]+>")


@dataclass(frozen=True)
class Segment:
    start_ms: int
    duration_ms: int
    text: str


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def clean_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = TAG_RE.sub("", text)
    return WS_RE.sub(" ", text.replace("\u200b", " ").replace("\ufeff", " ")).strip()


def normalize_segments(values: Iterable[Segment]) -> list[Segment]:
    rows: list[Segment] = []
    seen: set[tuple[int, int, str]] = set()
    for value in sorted(values, key=lambda row: (row.start_ms, row.duration_ms, row.text)):
        text = clean_text(value.text)
        key = (max(int(value.start_ms), 0), max(int(value.duration_ms), 0), text)
        if not text or key in seen:
            continue
        seen.add(key)
        if rows and rows[-1].text == text and abs(rows[-1].start_ms - key[0]) <= 50:
            continue
        rows.append(Segment(*key))
    return rows


def parse_json3(payload: Mapping[str, Any]) -> list[Segment]:
    rows: list[Segment] = []
    for event in payload.get("events", []) or []:
        if not isinstance(event, Mapping):
            continue
        text = "".join(
            str(piece.get("utf8") or "")
            for piece in (event.get("segs") or [])
            if isinstance(piece, Mapping)
        )
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
        local = node.tag.rsplit("}", 1)[-1]
        if local not in {"text", "p"}:
            continue
        caption = "".join(node.itertext())
        if "start" in node.attrib:
            start_ms = round(float(node.attrib.get("start", "0")) * 1000)
            duration_ms = round(float(node.attrib.get("dur", "0")) * 1000)
        else:
            start_ms = int(float(node.attrib.get("t", "0")))
            duration_ms = int(float(node.attrib.get("d", "0")))
        rows.append(Segment(start_ms, duration_ms, caption))
    return normalize_segments(rows)


def parse_timestamp(token: str) -> int:
    parts = token.strip().replace(",", ".").split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"invalid timestamp: {token}")
    return round((int(hours) * 3600 + int(minutes) * 60 + float(seconds)) * 1000)


def parse_vtt(text: str) -> list[Segment]:
    rows: list[Segment] = []
    blocks = re.split(r"\r?\n\s*\r?\n", text.strip())
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        timing_index = next((index for index, line in enumerate(lines) if "-->" in line), None)
        if timing_index is None:
            continue
        left, right = [piece.strip().split(" ", 1)[0] for piece in lines[timing_index].split("-->", 1)]
        start_ms = parse_timestamp(left)
        end_ms = parse_timestamp(right)
        caption = " ".join(lines[timing_index + 1 :])
        rows.append(Segment(start_ms, max(end_ms - start_ms, 0), caption))
    return normalize_segments(rows)


def parse_caption_response(response: requests.Response) -> list[Segment]:
    stripped = response.text.lstrip()
    content_type = response.headers.get("content-type", "").lower()
    if "json" in content_type or stripped.startswith("{"):
        payload = response.json()
        if isinstance(payload, Mapping):
            if "events" in payload:
                return parse_json3(payload)
            values = payload.get("transcript") or payload.get("captions") or payload.get("segments")
            if isinstance(values, list):
                rows: list[Segment] = []
                for item in values:
                    if not isinstance(item, Mapping):
                        continue
                    start = item.get("start_ms", item.get("start", item.get("offset", 0)))
                    duration = item.get("duration_ms", item.get("duration", 0))
                    if isinstance(start, float) and start < 100000:
                        start = round(start * 1000)
                    if isinstance(duration, float) and duration < 100000:
                        duration = round(duration * 1000)
                    rows.append(Segment(int(float(start or 0)), int(float(duration or 0)), str(item.get("text") or item.get("content") or "")))
                return normalize_segments(rows)
    if "vtt" in content_type or stripped.startswith("WEBVTT") or "-->" in stripped[:2000]:
        return parse_vtt(response.text)
    if stripped.startswith("<"):
        return parse_xml(response.text)
    return []


def safe_url(value: str) -> dict[str, str]:
    parsed = urllib.parse.urlsplit(value)
    return {"scheme": parsed.scheme, "host": parsed.netloc, "path": parsed.path}


def preferred_tracks(tracks: Sequence[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    def score(track: Mapping[str, Any]) -> tuple[int, int, str]:
        code = str(track.get("code") or track.get("language_code") or track.get("languageCode") or "").lower()
        auto = bool(track.get("autoGenerated") or track.get("auto_generated") or track.get("kind") == "asr")
        if code == "ko":
            language_score = 0
        elif code.startswith("ko-") or code.startswith("ko_"):
            language_score = 1
        elif code == "en":
            language_score = 2
        elif code.startswith("en-") or code.startswith("en_"):
            language_score = 3
        else:
            language_score = 10
        return language_score, 1 if auto else 0, code

    return sorted((row for row in tracks if isinstance(row, Mapping)), key=score)


def fetch_track(
    session: requests.Session,
    base: str,
    track: Mapping[str, Any],
    timeout: float,
) -> tuple[list[Segment], dict[str, Any]]:
    raw_url = str(track.get("url") or track.get("baseUrl") or "")
    if not raw_url:
        raise ValueError("track URL is missing")
    url = urllib.parse.urljoin(base.rstrip("/") + "/", raw_url)
    response = session.get(url, timeout=timeout)
    evidence = {
        "http_status": response.status_code,
        "bytes": len(response.content),
        "content_type": response.headers.get("content-type", ""),
        "url": safe_url(response.url),
        "body_sha256": sha256_bytes(response.content),
    }
    response.raise_for_status()
    segments = parse_caption_response(response)
    evidence["segment_count"] = len(segments)
    return segments, evidence


def probe_piped_instance(
    session: requests.Session,
    base: str,
    video_id: str,
    timeout: float,
) -> dict[str, Any]:
    started = time.monotonic()
    row: dict[str, Any] = {"provider": "piped", "instance": base, "segment_count": 0}
    try:
        response = session.get(f"{base.rstrip('/')}/streams/{video_id}", timeout=timeout)
        row.update({"http_status": response.status_code, "bytes": len(response.content), "content_type": response.headers.get("content-type", "")})
        response.raise_for_status()
        payload = response.json()
        tracks = payload.get("subtitles") if isinstance(payload, Mapping) else None
        audio = payload.get("audioStreams") if isinstance(payload, Mapping) else None
        row["track_count"] = len(tracks) if isinstance(tracks, list) else 0
        row["audio_stream_count"] = len(audio) if isinstance(audio, list) else 0
        row["title"] = payload.get("title") if isinstance(payload, Mapping) else None
        errors: list[str] = []
        for track in preferred_tracks(tracks or []):
            try:
                segments, fetch = fetch_track(session, base, track, timeout)
                if segments:
                    text = " ".join(segment.text for segment in segments)
                    row.update({
                        "segment_count": len(segments),
                        "character_count": len(text),
                        "text_sha256": sha256_bytes(text.encode("utf-8")),
                        "language_code": track.get("code"),
                        "auto_generated": track.get("autoGenerated"),
                        "track_fetch": fetch,
                        "segments": [asdict(segment) for segment in segments],
                    })
                    return row
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}"[-1000:])
        if errors:
            row["track_errors"] = errors[-5:]
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"[-2000:]
    finally:
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return row


def invidious_instances(session: requests.Session, timeout: float, limit: int) -> tuple[list[str], dict[str, Any]]:
    evidence: dict[str, Any] = {"index": INVIDIOUS_INSTANCE_INDEX}
    try:
        response = session.get(INVIDIOUS_INSTANCE_INDEX, timeout=timeout)
        evidence.update({"http_status": response.status_code, "bytes": len(response.content)})
        response.raise_for_status()
        payload = response.json()
        rows: list[tuple[float, str]] = []
        for item in payload if isinstance(payload, list) else []:
            if not isinstance(item, list) or len(item) != 2 or not isinstance(item[1], Mapping):
                continue
            host, details = str(item[0]), item[1]
            if not details.get("api") or details.get("type") != "https":
                continue
            health = details.get("health")
            try:
                health_score = float(health)
            except (TypeError, ValueError):
                health_score = 0.0
            rows.append((health_score, f"https://{host}"))
        rows.sort(key=lambda pair: (-pair[0], pair[1]))
        instances = [base for _, base in rows[:limit]]
        evidence["instance_count"] = len(instances)
        evidence["instances"] = instances
        return instances, evidence
    except Exception as exc:  # noqa: BLE001
        evidence["error"] = f"{type(exc).__name__}: {exc}"[-2000:]
        return [], evidence


def probe_invidious_instance(
    session: requests.Session,
    base: str,
    video_id: str,
    timeout: float,
) -> dict[str, Any]:
    started = time.monotonic()
    row: dict[str, Any] = {"provider": "invidious", "instance": base, "segment_count": 0}
    try:
        response = session.get(f"{base.rstrip('/')}/api/v1/videos/{video_id}", params={"hl": "ko"}, timeout=timeout)
        row.update({"http_status": response.status_code, "bytes": len(response.content), "content_type": response.headers.get("content-type", "")})
        response.raise_for_status()
        payload = response.json()
        tracks = payload.get("captions") if isinstance(payload, Mapping) else None
        formats = payload.get("adaptiveFormats") if isinstance(payload, Mapping) else None
        row["track_count"] = len(tracks) if isinstance(tracks, list) else 0
        row["audio_stream_count"] = sum("audio" in str(item.get("type") or "") for item in (formats or []) if isinstance(item, Mapping))
        row["title"] = payload.get("title") if isinstance(payload, Mapping) else None
        errors: list[str] = []
        for track in preferred_tracks(tracks or []):
            try:
                segments, fetch = fetch_track(session, base, track, timeout)
                if segments:
                    text = " ".join(segment.text for segment in segments)
                    row.update({
                        "segment_count": len(segments),
                        "character_count": len(text),
                        "text_sha256": sha256_bytes(text.encode("utf-8")),
                        "language_code": track.get("language_code"),
                        "track_fetch": fetch,
                        "segments": [asdict(segment) for segment in segments],
                    })
                    return row
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{type(exc).__name__}: {exc}"[-1000:])
        if errors:
            row["track_errors"] = errors[-5:]
    except Exception as exc:  # noqa: BLE001
        row["error"] = f"{type(exc).__name__}: {exc}"[-2000:]
    finally:
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return row


def probe_provider(
    session: requests.Session,
    provider: str,
    instances: Sequence[str],
    timeout: float,
    pace_seconds: float,
    output: Path,
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    recovered: dict[str, dict[str, Any]] = {}
    attempts: list[dict[str, Any]] = []
    probe = probe_piped_instance if provider == "piped" else probe_invidious_instance
    for instance_index, base in enumerate(instances):
        missing = [(slug, video_id) for slug, video_id in VIDEOS if video_id not in recovered]
        if not missing:
            break
        for video_index, (slug, video_id) in enumerate(missing):
            if attempts and pace_seconds > 0:
                time.sleep(pace_seconds)
            row = probe(session, base, video_id, timeout)
            segments = row.pop("segments", [])
            row.update({"channel_slug": slug, "video_id": video_id, "instance_index": instance_index, "video_index": video_index})
            attempts.append(row)
            if segments:
                transcript = output / "transcripts" / provider / f"{slug}-{video_id}.jsonl"
                transcript.parent.mkdir(parents=True, exist_ok=True)
                transcript.write_text("".join(canonical_json(segment) + "\n" for segment in segments), encoding="utf-8")
                recovered[video_id] = {
                    "provider": provider,
                    "instance": base,
                    "channel_slug": slug,
                    "video_id": video_id,
                    "segment_count": row["segment_count"],
                    "character_count": row.get("character_count", 0),
                    "text_sha256": row.get("text_sha256"),
                    "language_code": row.get("language_code"),
                    "transcript_path": str(transcript.relative_to(output)),
                }
        positive = recovered.get("F6wDs1HRTSo")
        if not positive and instance_index >= 5:
            # Avoid hammering unhealthy instances when even the positive control is unavailable.
            break
    return recovered, attempts


def self_test() -> None:
    rows = parse_vtt("WEBVTT\n\n00:00:01.000 --> 00:00:02.500\n안녕하세요\n")
    assert len(rows) == 1 and rows[0].start_ms == 1000 and rows[0].duration_ms == 1500
    xml = '<transcript><text start="1.25" dur="0.5">테스트 &amp; 확인</text></transcript>'
    rows = parse_xml(xml)
    assert len(rows) == 1 and rows[0].text == "테스트 & 확인" and rows[0].start_ms == 1250
    payload = {"events": [{"tStartMs": 3000, "dDurationMs": 800, "segs": [{"utf8": "완료"}]}]}
    rows = parse_json3(payload)
    assert len(rows) == 1 and rows[0].text == "완료"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout-seconds", type=float, default=35.0)
    parser.add_argument("--pace-seconds", type=float, default=0.75)
    parser.add_argument("--max-piped-instances", type=int, default=10)
    parser.add_argument("--max-invidious-instances", type=int, default=10)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        print("alt caption frontend probe self-test: ok")
        return 0
    if args.output is None:
        parser.error("--output is required unless --self-test is used")

    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.5"})
    try:
        recovered, piped_attempts = probe_provider(
            session,
            "piped",
            PIPED_INSTANCES[: max(args.max_piped_instances, 0)],
            args.timeout_seconds,
            args.pace_seconds,
            args.output,
        )
        dynamic_invidious, index_evidence = invidious_instances(
            session, args.timeout_seconds, max(args.max_invidious_instances, 0)
        )
        missing_before_invidious = {video_id for _, video_id in VIDEOS} - set(recovered)
        invidious_recovered: dict[str, dict[str, Any]] = {}
        invidious_attempts: list[dict[str, Any]] = []
        if missing_before_invidious:
            invidious_recovered, invidious_attempts = probe_provider(
                session,
                "invidious",
                dynamic_invidious,
                args.timeout_seconds,
                args.pace_seconds,
                args.output,
            )
            for video_id, row in invidious_recovered.items():
                recovered.setdefault(video_id, row)
    finally:
        session.close()

    rows = [recovered.get(video_id, {"channel_slug": slug, "video_id": video_id, "recovered": False}) for slug, video_id in VIDEOS]
    for row in rows:
        row["recovered"] = bool(int(row.get("segment_count") or 0) > 0)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "transport": "public_piped_invidious_caption_apis",
        "source_sha": os.environ.get("GITHUB_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "runner": {"platform": platform.platform(), "python": sys.version},
        "videos": rows,
        "recovered_video_count": sum(bool(row.get("recovered")) for row in rows),
        "target_recovered_count": sum(bool(row.get("recovered")) and row.get("channel_slug") != "known_positive_control" for row in rows),
        "positive_control_passed": any(row.get("video_id") == "F6wDs1HRTSo" and row.get("recovered") for row in rows),
        "piped_attempts": piped_attempts,
        "invidious_instance_index": index_evidence,
        "invidious_attempts": invidious_attempts,
    }
    payload["decision"] = "PASS" if payload["positive_control_passed"] and payload["target_recovered_count"] > 0 else "FAIL"
    payload["payload_sha256_before_field"] = sha256_bytes(canonical_json(payload).encode("utf-8"))
    (args.output / "probe.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
