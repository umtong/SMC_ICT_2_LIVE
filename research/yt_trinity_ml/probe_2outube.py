#!/usr/bin/env python3
"""Probe 2outube's server-rendered transcript reader with strict positive control.

This is intentionally narrow: 2outube states that it uses a managed residential
provider rather than direct datacenter-to-YouTube caption requests.  We test one
known-caption control and one representative video from each target channel.  Raw
HTML and normalized evidence are retained so a successful transport can be expanded
without guessing at undocumented response shapes.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import platform
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import requests

VIDEOS = (
    ("known_positive_control", "F6wDs1HRTSo"),
    ("chartbro", "0h9lpMUBSlE"),
    ("swipalnam", "-Tp2fhvVVGM"),
    ("indicator_sensei", "2U0s_i07vMY"),
)
TIMESTAMP_RE = re.compile(r"(?<!\d)(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?!\d)")
GENERIC_MARKERS = (
    "change one letter",
    "read the video",
    "paste any youtube link",
    "every video is a document",
)
CHALLENGE_MARKERS = (
    "captcha",
    "turnstile",
    "human verification",
    "verify you are human",
    "checking your browser",
    "cf-chl-",
)
NO_CAPTION_MARKERS = (
    "no captions",
    "captions disabled",
    "transcript unavailable",
    "no transcript",
    "nothing for us to fetch",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class VisibleHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hidden = 0
        self.text: list[str] = []
        self.data_segments: list[dict[str, Any]] = []
        self._candidate_start: float | None = None
        self._candidate_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden += 1
        attr = {str(key).lower(): value for key, value in attrs}
        start = None
        for key in ("data-start", "data-time", "data-timestamp", "data-seconds"):
            if attr.get(key) not in (None, ""):
                start = safe_float(attr.get(key))
                break
        if start is not None:
            self._candidate_start = start
            self._candidate_text = []

    def handle_endtag(self, tag: str) -> None:
        if self._candidate_start is not None and self._candidate_text:
            text = " ".join(self._candidate_text).strip()
            if text:
                self.data_segments.append({"start": self._candidate_start, "text": text})
            self._candidate_start = None
            self._candidate_text = []
        if tag in {"script", "style", "noscript", "svg"} and self.hidden:
            self.hidden -= 1

    def handle_data(self, data: str) -> None:
        cleaned = " ".join(data.split())
        if not cleaned:
            return
        if not self.hidden:
            self.text.append(cleaned)
            if self._candidate_start is not None:
                self._candidate_text.append(cleaned)


def walk_json(value: Any, output: list[dict[str, Any]]) -> None:
    if isinstance(value, Mapping):
        text = str(value.get("text") or value.get("content") or value.get("caption") or "").strip()
        start = None
        for key in ("start", "startTime", "start_time", "time", "offset"):
            if key in value:
                start = safe_float(value.get(key))
                break
        duration = None
        for key in ("duration", "durationSeconds", "duration_seconds"):
            if key in value:
                duration = safe_float(value.get(key))
                break
        if text and start is not None:
            row: dict[str, Any] = {"start": start, "text": text}
            if duration is not None:
                row["duration"] = duration
            output.append(row)
        for child in value.values():
            walk_json(child, output)
    elif isinstance(value, list):
        for child in value:
            walk_json(child, output)


def script_json_candidates(body: str) -> Iterable[Any]:
    for match in re.finditer(r"<script\b[^>]*>(.*?)</script>", body, flags=re.I | re.S):
        payload = html.unescape(match.group(1)).strip()
        if not payload:
            continue
        if payload[0] in "[{":
            try:
                yield json.loads(payload)
            except Exception:
                pass
        for marker in ("__NEXT_DATA__", "__remixContext", "__INITIAL_STATE__"):
            if marker not in payload:
                continue
            assignment = re.search(re.escape(marker) + r"\s*=\s*({.*})\s*;?\s*$", payload, flags=re.S)
            if assignment:
                try:
                    yield json.loads(assignment.group(1))
                except Exception:
                    pass


def normalize_segments(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[float, str]] = set()
    for row in rows:
        start = safe_float(row.get("start"))
        text = " ".join(str(row.get("text") or "").split())
        if start is None or not text:
            continue
        key = (round(start, 3), text)
        if key in seen:
            continue
        seen.add(key)
        normalized: dict[str, Any] = {"start": start, "text": text}
        duration = safe_float(row.get("duration"))
        if duration is not None:
            normalized["duration"] = duration
        result.append(normalized)
    result.sort(key=lambda item: (float(item["start"]), str(item["text"])))
    return result


def inspect_html(body: str) -> dict[str, Any]:
    parser = VisibleHTML()
    parser.feed(body)
    visible = "\n".join(parser.text)
    lower = visible.lower()
    json_segments: list[dict[str, Any]] = []
    for payload in script_json_candidates(body):
        walk_json(payload, json_segments)
    segments = normalize_segments([*parser.data_segments, *json_segments])
    timestamps = [match.group(0) for match in TIMESTAMP_RE.finditer(visible)]
    title_match = re.search(r"<title[^>]*>(.*?)</title>", body, flags=re.I | re.S)
    title = html.unescape(title_match.group(1)).strip() if title_match else None
    transcript_like_lines = []
    for line in visible.splitlines():
        if TIMESTAMP_RE.search(line) and len(line) > 8:
            transcript_like_lines.append(line[:1000])
    generic_score = sum(marker in lower for marker in GENERIC_MARKERS)
    challenge = any(marker in body.lower() or marker in lower for marker in CHALLENGE_MARKERS)
    no_caption = any(marker in lower for marker in NO_CAPTION_MARKERS)
    # A valid transcript must be addressable as structured segments or show several
    # timestamped speech lines.  Generic landing-page examples alone are rejected.
    transcript_detected = bool(segments) or (
        len(transcript_like_lines) >= 3 and len(visible) >= 500 and generic_score < 3
    )
    return {
        "title": title,
        "visible_chars": len(visible),
        "visible_sha256": sha256_bytes(visible.encode("utf-8")),
        "visible_prefix": visible[:3000],
        "timestamp_token_count": len(timestamps),
        "timestamped_line_count": len(transcript_like_lines),
        "first_timestamped_lines": transcript_like_lines[:5],
        "structured_segment_count": len(segments),
        "first_segments": segments[:5],
        "transcript_detected": transcript_detected,
        "challenge_detected": challenge,
        "no_caption_detected": no_caption,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--delay-seconds", type=float, default=5.0)
    args = parser.parse_args(argv)
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/132 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.7,en;q=0.6",
        }
    )
    rows: list[dict[str, Any]] = []
    try:
        home = session.get("https://2outube.com/", timeout=40)
        home.raise_for_status()
        for index, (channel, video_id) in enumerate(VIDEOS):
            if index:
                time.sleep(max(0.0, args.delay_seconds))
            url = f"https://2outube.com/watch?v={video_id}"
            started = time.monotonic()
            try:
                response = session.get(url, timeout=150, allow_redirects=True)
                raw = response.content
                body = response.text
                evidence = inspect_html(body)
                row = {
                    "channel": channel,
                    "video_id": video_id,
                    "requested_url": url,
                    "final_url": response.url,
                    "status_code": response.status_code,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "content_type": response.headers.get("content-type"),
                    "body_bytes": len(raw),
                    "body_sha256": sha256_bytes(raw),
                    "rate_headers": {
                        key: value
                        for key, value in response.headers.items()
                        if any(token in key.lower() for token in ("rate", "retry", "cf-", "request-id"))
                    },
                    **evidence,
                }
                (args.output / f"{channel}-{video_id}.html").write_bytes(raw)
            except Exception as exc:  # exact network failure is evidence
                row = {
                    "channel": channel,
                    "video_id": video_id,
                    "requested_url": url,
                    "elapsed_seconds": round(time.monotonic() - started, 3),
                    "request_error": f"{type(exc).__name__}: {exc}"[-4000:],
                    "transcript_detected": False,
                }
            rows.append(row)
    finally:
        session.close()
    positive = any(
        row.get("channel") == "known_positive_control" and row.get("transcript_detected")
        for row in rows
    )
    recovered = [
        row
        for row in rows
        if row.get("channel") != "known_positive_control" and row.get("transcript_detected")
    ]
    result = {
        "schema_version": 1,
        "workflow": "YT Trinity managed 2outube transcript probe",
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "source_sha": os.environ.get("GITHUB_SHA"),
        "runner": {"platform": platform.platform(), "python": platform.python_version()},
        "positive_control_passed": positive,
        "target_recovered_count": len(recovered),
        "decision": "VALIDATED_PROVIDER" if positive and recovered else "FAIL",
        "rows": rows,
    }
    result["payload_sha256_before_field"] = sha256_bytes(canonical_json(result).encode("utf-8"))
    (args.output / "probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
