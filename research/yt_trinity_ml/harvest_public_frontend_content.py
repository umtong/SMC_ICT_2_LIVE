#!/usr/bin/env python3
"""Complete one exact public-inventory shard through a validated frontend.

Native captions are preferred.  When none are exposed but a public audio stream
is validated, audio is processed transiently with faster-whisper and deleted;
only timestamped text, hashes, and the outcome ledger are retained.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin

import requests


TIMING_RE = re.compile(
    r"(?P<start>(?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})\s+-->\s+"
    r"(?P<end>(?:\d{1,2}:)?\d{2}:\d{2}[\.,]\d{3})"
)
TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class Segment:
    start_ms: int
    duration_ms: int
    text: str

    def as_dict(self) -> dict[str, Any]:
        return {"start_ms": self.start_ms, "duration_ms": self.duration_ms, "text": self.text}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def clean_text(value: str) -> str:
    value = html.unescape(value or "")
    value = TAG_RE.sub("", value)
    return WS_RE.sub(" ", value.replace("\u200b", " ").replace("\ufeff", " ")).strip()


def timestamp_ms(value: str) -> int:
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
        raise ValueError(value)
    return int(round((hours * 3600 + minutes * 60 + seconds) * 1000))


def normalize_segments(rows: Iterable[Segment]) -> list[Segment]:
    output: list[Segment] = []
    seen: set[tuple[int, int, str]] = set()
    for row in sorted(rows, key=lambda item: (item.start_ms, item.duration_ms, item.text)):
        text = clean_text(row.text)
        if not text:
            continue
        key = (max(0, int(row.start_ms)), max(0, int(row.duration_ms)), text)
        if key in seen:
            continue
        seen.add(key)
        if output and output[-1].text == text and abs(output[-1].start_ms - key[0]) <= 50:
            continue
        output.append(Segment(*key))
    return output


def parse_vtt(text: str) -> list[Segment]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rows: list[Segment] = []
    index = 0
    while index < len(lines):
        match = TIMING_RE.search(lines[index].strip())
        if not match and index + 1 < len(lines):
            match = TIMING_RE.search(lines[index + 1].strip())
            if match:
                index += 1
        if not match:
            index += 1
            continue
        start = timestamp_ms(match.group("start"))
        end = timestamp_ms(match.group("end"))
        index += 1
        cue: list[str] = []
        while index < len(lines) and lines[index].strip():
            cue.append(lines[index].strip())
            index += 1
        text_value = clean_text(" ".join(cue))
        if text_value:
            rows.append(Segment(start, max(0, end - start), text_value))
        index += 1
    return normalize_segments(rows)


def parse_json_caption(payload: Any) -> list[Segment]:
    rows: list[Segment] = []
    if isinstance(payload, Mapping) and isinstance(payload.get("events"), list):
        for event in payload["events"]:
            if not isinstance(event, Mapping):
                continue
            text = "".join(
                str(item.get("utf8") or "")
                for item in event.get("segs", []) or []
                if isinstance(item, Mapping)
            )
            text = clean_text(text)
            if text:
                rows.append(Segment(int(event.get("tStartMs") or 0), int(event.get("dDurationMs") or 0), text))
    elif isinstance(payload, list):
        for index, item in enumerate(payload):
            if not isinstance(item, Mapping):
                continue
            text = clean_text(str(item.get("text") or item.get("utf8") or ""))
            if not text:
                continue
            start = item.get("start_ms", item.get("start", item.get("offset", 0)))
            duration = item.get("duration_ms", item.get("duration", 0))
            try:
                start_value = float(start)
                duration_value = float(duration)
            except (TypeError, ValueError):
                continue
            if start_value < 100_000 and not str(start).isdigit():
                start_value *= 1000
            if duration_value < 10_000 and not str(duration).isdigit():
                duration_value *= 1000
            rows.append(Segment(int(round(start_value)), int(round(duration_value)), text))
    return normalize_segments(rows)


def parse_xml_caption(text: str) -> list[Segment]:
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return []
    rows: list[Segment] = []
    for node in root.iter():
        name = node.tag.rsplit("}", 1)[-1]
        if name not in {"text", "p"}:
            continue
        value = clean_text("".join(node.itertext()))
        if not value:
            continue
        if "start" in node.attrib:
            start = int(round(float(node.attrib.get("start", "0")) * 1000))
            duration = int(round(float(node.attrib.get("dur", "0")) * 1000))
        else:
            start = int(float(node.attrib.get("t", "0")))
            duration = int(float(node.attrib.get("d", "0")))
        rows.append(Segment(start, max(0, duration), value))
    return normalize_segments(rows)


def parse_caption(raw: bytes, content_type: str) -> list[Segment]:
    text = raw.decode("utf-8", "replace")
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")) or "json" in content_type.lower():
        try:
            rows = parse_json_caption(json.loads(text))
            if rows:
                return rows
        except Exception:
            pass
    if stripped.startswith("<") or "xml" in content_type.lower() or "ttml" in content_type.lower():
        rows = parse_xml_caption(text)
        if rows:
            return rows
    return parse_vtt(text)


def load_inventory(path: Path, shard_index: int, shard_count: int) -> list[dict[str, Any]]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    rows.sort(key=lambda row: (row["channel_slug"], row["video_id"]))
    selected = [row for index, row in enumerate(rows) if index % shard_count == shard_index]
    if not selected:
        raise RuntimeError("empty shard")
    return selected


def load_winner(path: Path) -> tuple[str, str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    winner = payload.get("winner") if isinstance(payload, Mapping) else None
    if not isinstance(winner, Mapping):
        raise RuntimeError("winner payload missing")
    provider = str(winner.get("provider") or "")
    base = str(winner.get("base") or "").rstrip("/")
    if provider not in {"piped", "invidious"} or not base.startswith("http"):
        raise RuntimeError(f"invalid winner: {provider} {base}")
    return provider, base


def api_surface(provider: str, base: str, video_id: str) -> dict[str, Any]:
    endpoint = f"{base}/streams/{video_id}" if provider == "piped" else f"{base}/api/v1/videos/{video_id}"
    response = requests.get(endpoint, headers={"User-Agent": "SMC-ICT-2-LIVE/1.0", "Accept": "application/json"}, timeout=35)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, Mapping):
        raise RuntimeError("non-object API response")
    if provider == "piped":
        subtitle_rows = payload.get("subtitles") or []
        audio_rows = payload.get("audioStreams") or []
    else:
        subtitle_rows = payload.get("captions") or []
        audio_rows = [
            row for row in payload.get("adaptiveFormats", []) or []
            if isinstance(row, Mapping) and str(row.get("type") or "").startswith("audio/")
        ]
    subtitles: list[dict[str, Any]] = []
    for row in subtitle_rows:
        if not isinstance(row, Mapping):
            continue
        url = row.get("url")
        if not isinstance(url, str):
            continue
        subtitles.append({
            "url": urljoin(base + "/", url),
            "language_code": row.get("code") or row.get("languageCode"),
            "name": row.get("name") or row.get("label"),
            "auto_generated": row.get("autoGenerated") or row.get("isAutoGenerated"),
        })
    audio: list[dict[str, Any]] = []
    for row in audio_rows:
        if not isinstance(row, Mapping) or not isinstance(row.get("url"), str):
            continue
        audio.append({
            "url": row["url"],
            "bitrate": int(row.get("bitrate") or 0),
            "mime_type": row.get("mimeType") or row.get("type"),
            "quality": row.get("quality") or row.get("audioQuality"),
        })
    audio.sort(key=lambda row: row["bitrate"], reverse=True)
    return {
        "title": payload.get("title"),
        "subtitles": subtitles,
        "audio": audio,
    }


def subtitle_rank(row: Mapping[str, Any]) -> tuple[int, int, str]:
    code = str(row.get("language_code") or "").lower()
    name = str(row.get("name") or "").lower()
    if code.startswith("ko") or "korean" in name or "한국" in name:
        language_rank = 0
    elif code.startswith("en") or "english" in name:
        language_rank = 1
    else:
        language_rank = 2
    auto = 1 if row.get("auto_generated") else 0
    return language_rank, auto, code


def fetch_native_caption(rows: Iterable[Mapping[str, Any]]) -> tuple[list[Segment], dict[str, Any]]:
    attempts: list[dict[str, Any]] = []
    for row in sorted(rows, key=subtitle_rank):
        url = str(row["url"])
        try:
            response = requests.get(
                url,
                headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.7"},
                timeout=40,
                allow_redirects=True,
            )
            raw = response.content
            segments = parse_caption(raw, response.headers.get("content-type", "")) if response.status_code == 200 else []
            attempts.append({
                "language_code": row.get("language_code"),
                "name": row.get("name"),
                "auto_generated": row.get("auto_generated"),
                "status_code": response.status_code,
                "bytes": len(raw),
                "segments": len(segments),
                "sha256": sha256_bytes(raw),
            })
            if segments:
                return segments, {"selected": attempts[-1], "attempts": attempts}
        except Exception as exc:
            attempts.append({"language_code": row.get("language_code"), "exception": f"{type(exc).__name__}: {exc}"})
    return [], {"attempts": attempts}


class WhisperTranscriber:
    def __init__(self, model_name: str) -> None:
        self.model_name = model_name
        self.model = None

    def _load(self):
        if self.model is None:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(
                self.model_name,
                device="cpu",
                compute_type="int8",
                cpu_threads=max(2, min(8, os.cpu_count() or 4)),
                num_workers=1,
            )
        return self.model

    def transcribe(self, audio_url: str, work_root: Path) -> tuple[list[Segment], dict[str, Any]]:
        work_root.mkdir(parents=True, exist_ok=True)
        source = work_root / "source_audio"
        wav = work_root / "audio.wav"
        started = time.monotonic()
        download_bytes = 0
        try:
            with requests.get(
                audio_url,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=60,
                stream=True,
                allow_redirects=True,
            ) as response:
                response.raise_for_status()
                with source.open("wb") as handle:
                    for chunk in response.iter_content(1024 * 1024):
                        if not chunk:
                            continue
                        download_bytes += len(chunk)
                        if download_bytes > 1_500_000_000:
                            raise RuntimeError("audio exceeds transient safety size")
                        handle.write(chunk)
            command = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-i", str(source), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav),
            ]
            completed = subprocess.run(command, text=True, capture_output=True, timeout=900)
            if completed.returncode != 0 or not wav.exists():
                raise RuntimeError(f"ffmpeg failed: {completed.stderr[-2000:]}")
            model = self._load()
            iterator, info = model.transcribe(
                str(wav),
                language="ko",
                beam_size=5,
                best_of=5,
                vad_filter=True,
                vad_parameters={"min_silence_duration_ms": 500},
                condition_on_previous_text=True,
                word_timestamps=False,
            )
            rows: list[Segment] = []
            for item in iterator:
                text = clean_text(str(item.text or ""))
                if text:
                    rows.append(
                        Segment(
                            int(round(float(item.start) * 1000)),
                            int(round(max(0.0, float(item.end) - float(item.start)) * 1000)),
                            text,
                        )
                    )
            rows = normalize_segments(rows)
            return rows, {
                "model": self.model_name,
                "language": getattr(info, "language", None),
                "language_probability": getattr(info, "language_probability", None),
                "duration": getattr(info, "duration", None),
                "download_bytes": download_bytes,
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
        finally:
            for path in (source, wav):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass


def write_transcript(root: Path, channel: str, video_id: str, segments: list[Segment]) -> tuple[str, str]:
    relative = Path("transcripts") / channel / f"{video_id}.jsonl"
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = "".join(json.dumps(row.as_dict(), ensure_ascii=False, sort_keys=True) + "\n" for row in segments)
    path.write_text(raw, encoding="utf-8")
    text_path = path.with_suffix(".txt")
    text_path.write_text(
        "\n".join(f"[{row.start_ms / 1000:.3f}] {row.text}" for row in segments) + "\n",
        encoding="utf-8",
    )
    return str(relative), sha256_bytes(raw.encode("utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--winner", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--shard-index", type=int, required=True)
    parser.add_argument("--shard-count", type=int, required=True)
    parser.add_argument("--asr-model", default="small")
    args = parser.parse_args()
    if not 0 <= args.shard_index < args.shard_count:
        raise ValueError("invalid shard")
    args.output.mkdir(parents=True, exist_ok=True)
    provider, base = load_winner(args.winner)
    inventory = load_inventory(args.inventory, args.shard_index, args.shard_count)
    transcriber = WhisperTranscriber(args.asr_model)
    outcomes: list[dict[str, Any]] = []
    temporary_root = Path(tempfile.mkdtemp(prefix="yt-trinity-asr-"))
    try:
        for position, item in enumerate(inventory, start=1):
            video_id = item["video_id"]
            channel = item["channel_slug"]
            started = time.monotonic()
            row = dict(item)
            row.update({
                "caption_status": "fetch_failed",
                "caption_provider": None,
                "caption_language_code": None,
                "caption_segment_count": 0,
                "caption_char_count": 0,
                "transcript_jsonl": None,
                "caption_sha256": None,
                "attempt_detail": {},
            })
            try:
                surface = api_surface(provider, base, video_id)
                native, native_detail = fetch_native_caption(surface["subtitles"])
                if native:
                    relative, digest = write_transcript(args.output, channel, video_id, native)
                    row.update({
                        "caption_status": "ok",
                        "caption_provider": f"{provider}_native_caption",
                        "caption_language_code": (native_detail.get("selected") or {}).get("language_code"),
                        "caption_segment_count": len(native),
                        "caption_char_count": sum(len(segment.text) for segment in native),
                        "transcript_jsonl": relative,
                        "caption_sha256": digest,
                        "attempt_detail": {"native": native_detail},
                    })
                elif surface["audio"]:
                    audio = surface["audio"][0]
                    work = temporary_root / video_id
                    work.mkdir(parents=True, exist_ok=True)
                    segments, asr_detail = transcriber.transcribe(audio["url"], work)
                    if not segments:
                        raise RuntimeError("ASR returned no text")
                    relative, digest = write_transcript(args.output, channel, video_id, segments)
                    row.update({
                        "caption_status": "ok",
                        "caption_provider": f"{provider}_transient_audio_faster_whisper_{args.asr_model}",
                        "caption_language_code": "ko",
                        "caption_segment_count": len(segments),
                        "caption_char_count": sum(len(segment.text) for segment in segments),
                        "transcript_jsonl": relative,
                        "caption_sha256": digest,
                        "attempt_detail": {"native": native_detail, "asr": asr_detail, "audio_mime_type": audio.get("mime_type")},
                    })
                else:
                    row["attempt_detail"] = {"native": native_detail, "surface": "no public audio stream"}
            except Exception as exc:
                row["attempt_detail"] = {**(row.get("attempt_detail") or {}), "exception": f"{type(exc).__name__}: {exc}"}
            row["processing_seconds"] = round(time.monotonic() - started, 3)
            outcomes.append(row)
            raw = "".join(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n" for value in outcomes)
            (args.output / "videos.jsonl").write_text(raw, encoding="utf-8")
            counts = Counter(value["caption_status"] for value in outcomes)
            checkpoint = {
                "schema_version": 1,
                "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
                "provider": provider,
                "base": base,
                "shard_index": args.shard_index,
                "shard_count": args.shard_count,
                "inventory_count": len(inventory),
                "completed_count": len(outcomes),
                "status_counts": dict(sorted(counts.items())),
                "updated_at_utc": utc_now(),
            }
            (args.output / "manifest.json").write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(json.dumps({"position": position, "video_id": video_id, "status": row["caption_status"], "provider": row["caption_provider"]}, ensure_ascii=False), flush=True)
    finally:
        shutil.rmtree(temporary_root, ignore_errors=True)
    counts = Counter(value["caption_status"] for value in outcomes)
    manifest = {
        "schema_version": 1,
        "claim_id": "CLM-20260727-0346-YT-TRINITY-ML-001",
        "provider": provider,
        "base": base,
        "shard_index": args.shard_index,
        "shard_count": args.shard_count,
        "inventory_count": len(inventory),
        "completed_count": len(outcomes),
        "status_counts": dict(sorted(counts.items())),
        "all_complete": len(outcomes) == len(inventory) and counts.get("fetch_failed", 0) == 0,
        "transcript_segment_count": sum(int(row["caption_segment_count"]) for row in outcomes),
        "transcript_character_count": sum(int(row["caption_char_count"]) for row in outcomes),
        "updated_at_utc": utc_now(),
        "videos_sha256": sha256_bytes((args.output / "videos.jsonl").read_bytes()),
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if manifest["all_complete"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
