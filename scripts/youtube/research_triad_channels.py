#!/usr/bin/env python3
"""Collect a complete public YouTube transcript corpus for the project triad.

This script intentionally downloads no video or audio. It inventories every public
upload tab, captures metadata, requests creator and auto-generated captions, converts
WebVTT captions to normalized timestamped text, and emits coverage/evidence reports.

The script is designed for GitHub Actions because the project runtime may not have
outbound network access. Every failure is recorded rather than silently discarded.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import csv
import dataclasses
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable, Iterator


@dataclasses.dataclass(frozen=True)
class Channel:
    key: str
    name: str
    locator: str
    expected_channel_id: str | None


CHANNELS: tuple[Channel, ...] = (
    Channel(
        key="easychart",
        name="쉽알남",
        locator="https://www.youtube.com/channel/UCBltgdQdT3h004d5cTw-EhQ",
        expected_channel_id="UCBltgdQdT3h004d5cTw-EhQ",
    ),
    Channel(
        key="chartbro",
        name="차트브로",
        locator="https://www.youtube.com/@chartbro",
        expected_channel_id=None,
    ),
    Channel(
        key="indicator_sensei",
        name="지표센세",
        locator="https://www.youtube.com/channel/UCEeQbR5tgf-ogqhxRQHMlQQ",
        expected_channel_id="UCEeQbR5tgf-ogqhxRQHMlQQ",
    ),
)

TABS: tuple[str, ...] = ("videos", "shorts", "streams")

# Terms support corpus navigation; they do not decide economic validity.
ONTOLOGY: dict[str, tuple[str, ...]] = {
    "liquidity": (
        "유동성", "liquidity", "스탑헌트", "스탑 헌트", "stop hunt", "liquidity grab",
        "유동성 사냥", "liquidity sweep", "스윕", "sweep",
    ),
    "market_structure": (
        "시장 구조", "마켓 스트럭처", "market structure", "bos", "choch", "mss",
        "구조 전환", "구조 변화", "고점", "저점", "스윙 하이", "스윙 로우",
    ),
    "fvg_imbalance": (
        "fvg", "fair value gap", "페어 밸류 갭", "불균형", "imbalance", "ifvg",
        "inverse fair value gap", "bpr", "balanced price range",
    ),
    "orderblock_pdarray": (
        "오더 블록", "오더블록", "order block", "pd array", "pd어레이", "pd 어레이",
        "브레이커", "breaker", "미티게이션", "mitigation", "리젝션 블록",
    ),
    "premium_discount": (
        "프리미엄", "디스카운트", "premium", "discount", "equilibrium", "이퀼리브리엄",
        "dealing range", "딜링 레인지", "오테", "ote", "optimal trade entry",
    ),
    "po3_amd": (
        "po3", "power of three", "amd", "accumulation", "manipulation", "distribution",
        "매집", "조작", "분배", "누적", "유인", "페이크 무브",
    ),
    "time_session": (
        "킬존", "killzone", "kill zone", "세션", "session", "런던", "뉴욕", "아시아",
        "매크로 타임", "macro time", "silver bullet", "실버 불릿", "오픈", "opening range",
    ),
    "mtf_fractal": (
        "다중 시간", "멀티 타임", "multi timeframe", "mtf", "프랙탈", "fractal",
        "상위 시간", "하위 시간", "top down", "탑다운", "방향성", "바이어스", "bias",
    ),
    "smt_cross_asset": (
        "smt", "divergence", "다이버전스", "상관관계", "비트코인", "이더리움",
        "btc", "eth", "cross asset", "교차 자산",
    ),
    "trend_indicators": (
        "ema", "이동평균", "moving average", "pac", "hull", "헐", "볼린저", "bollinger",
        "supertrend", "슈퍼트렌드", "ichimoku", "일목",
    ),
    "momentum_mean_reversion": (
        "rsi", "z-score", "z score", "z스코어", "스토캐스틱", "stochastic", "macd",
        "회귀", "regression", "평균 회귀", "mean reversion", "과매수", "과매도",
    ),
    "volume_orderflow": (
        "거래량", "volume", "오더플로우", "order flow", "델타", "delta", "cvd",
        "footprint", "풋프린트", "volume profile", "볼륨 프로파일", "vwap",
    ),
    "derivatives_positioning": (
        "미결제약정", "open interest", "oi", "펀딩", "funding", "롱숏비", "long short ratio",
        "청산", "liquidation", "청산맵", "청산 자석", "liquidation map",
    ),
    "harmonic_pattern": (
        "하모닉", "harmonic", "가틀리", "gartley", "뱃", "bat", "크랩", "crab",
        "버터플라이", "butterfly", "사이퍼", "cypher", "prz",
    ),
    "risk_execution": (
        "리스크", "risk", "손절", "stop loss", "스탑로스", "익절", "take profit", "손익비",
        "risk reward", "레버리지", "leverage", "포지션 사이즈", "position size", "분할 진입",
        "수수료", "fee", "슬리피지", "slippage", "시장가", "지정가",
    ),
    "psychology_process": (
        "심리", "멘탈", "mindset", "뇌동", "복기", "매매일지", "journal", "원칙", "규칙",
        "시나리오", "기다", "인내", "discipline", "확률",
    ),
}


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def run_command(
    args: list[str],
    *,
    timeout: int,
    cwd: Path | None = None,
    attempts: int = 2,
) -> subprocess.CompletedProcess[str]:
    last: subprocess.CompletedProcess[str] | None = None
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=timeout,
            check=False,
        )
        last = proc
        if proc.returncode == 0:
            return proc
        if attempt < attempts:
            time.sleep(min(8, 2 ** attempt))
    assert last is not None
    return last


def yt_dlp_base_args() -> list[str]:
    return [
        sys.executable,
        "-m",
        "yt_dlp",
        "--ignore-config",
        "--no-warnings",
        "--socket-timeout",
        "30",
        "--retries",
        "5",
        "--fragment-retries",
        "5",
        "--extractor-retries",
        "3",
        "--extractor-args",
        "youtube:player_client=web,android_vr,ios",
    ]


def inventory_tab(channel: Channel, tab: str, log_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    url = f"{channel.locator.rstrip('/')}/{tab}"
    args = yt_dlp_base_args() + [
        "--flat-playlist",
        "--dump-single-json",
        "--playlist-end",
        "2000",
        url,
    ]
    proc = run_command(args, timeout=600, attempts=3)
    log_path = log_dir / f"inventory__{channel.key}__{tab}.log"
    log_path.write_text(
        f"COMMAND: {' '.join(args)}\nRETURN_CODE: {proc.returncode}\n\nSTDERR\n{proc.stderr}\n\nSTDOUT\n{proc.stdout}",
        encoding="utf-8",
    )
    status: dict[str, Any] = {
        "channel": channel.name,
        "channel_key": channel.key,
        "tab": tab,
        "url": url,
        "ok": proc.returncode == 0,
        "return_code": proc.returncode,
        "log": str(log_path),
        "error": None,
    }
    if proc.returncode != 0:
        status["error"] = proc.stderr[-4000:]
        return [], status
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        status["ok"] = False
        status["error"] = f"invalid JSON: {exc}"
        return [], status

    entries: list[dict[str, Any]] = []
    for idx, item in enumerate(payload.get("entries") or []):
        if not isinstance(item, dict):
            continue
        video_id = item.get("id") or item.get("url")
        if not video_id or not re.fullmatch(r"[A-Za-z0-9_-]{11}", str(video_id)):
            continue
        entries.append(
            {
                "channel": channel.name,
                "channel_key": channel.key,
                "expected_channel_id": channel.expected_channel_id,
                "resolved_channel_id": item.get("channel_id") or payload.get("channel_id"),
                "tab": tab,
                "tab_index": idx,
                "video_id": str(video_id),
                "url": f"https://www.youtube.com/watch?v={video_id}",
                "flat_title": item.get("title"),
                "flat_duration": item.get("duration"),
                "flat_timestamp": item.get("timestamp"),
                "flat_upload_date": item.get("upload_date"),
            }
        )
    status["count"] = len(entries)
    status["resolved_channel_id"] = payload.get("channel_id")
    status["playlist_id"] = payload.get("id")
    return entries, status


def deduplicate_inventory(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        vid = row["video_id"]
        if vid not in by_id:
            row = dict(row)
            row["tabs"] = [row["tab"]]
            by_id[vid] = row
        elif row["tab"] not in by_id[vid]["tabs"]:
            by_id[vid]["tabs"].append(row["tab"])
    return sorted(
        by_id.values(),
        key=lambda r: (r["channel_key"], r.get("flat_timestamp") or 0, r["video_id"]),
    )


def choose_caption_files(work_dir: Path, video_id: str) -> list[Path]:
    return sorted(
        p for p in work_dir.glob(f"{video_id}.*")
        if p.suffix.lower() in {".vtt", ".srt", ".ttml", ".json3"}
    )


def parse_vtt(path: Path) -> list[tuple[str, str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    raw = re.sub(r"^\ufeff", "", raw)
    lines = raw.splitlines()
    cues: list[tuple[str, str]] = []
    timestamp = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if not buffer:
            return
        text = " ".join(buffer)
        text = re.sub(r"<\d\d:\d\d(?::\d\d)?\.\d{3}>", "", text)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text)
        text = re.sub(r"\s+", " ", text).strip()
        if text and (not cues or cues[-1][1] != text):
            cues.append((timestamp, text))
        buffer = []

    for line in lines:
        stripped = line.strip()
        if "-->" in stripped:
            flush()
            timestamp = stripped.split("-->", 1)[0].strip()
            continue
        if not stripped:
            flush()
            continue
        if (
            stripped == "WEBVTT"
            or stripped.startswith(("Kind:", "Language:", "NOTE", "STYLE"))
            or re.fullmatch(r"\d+", stripped)
        ):
            continue
        if timestamp:
            buffer.append(stripped)
    flush()
    return cues


def normalize_caption(path: Path, destination: Path) -> dict[str, Any]:
    cues = parse_vtt(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("w", encoding="utf-8") as fh:
        for ts, text in cues:
            fh.write(f"[{ts}] {text}\n" if ts else f"{text}\n")
    return {
        "source_file": str(path),
        "text_file": str(destination),
        "cue_count": len(cues),
        "character_count": sum(len(text) for _, text in cues),
        "sha256": sha256_file(destination),
    }


def fetch_one_video(
    row: dict[str, Any],
    *,
    output_root: Path,
    raw_root: Path,
    log_root: Path,
) -> dict[str, Any]:
    channel_dir = raw_root / row["channel_key"]
    channel_dir.mkdir(parents=True, exist_ok=True)
    text_dir = output_root / "transcripts" / row["channel_key"]
    text_dir.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix=f"yt_{row['video_id']}_") as tmp:
        tmp_dir = Path(tmp)
        template = str(tmp_dir / "%(id)s.%(language)s.%(ext)s")
        args = yt_dlp_base_args() + [
            "--skip-download",
            "--write-info-json",
            "--write-description",
            "--write-subs",
            "--write-auto-subs",
            "--sub-langs",
            "ko.*,ko,en.*,en",
            "--sub-format",
            "vtt/best",
            "--output",
            template,
            row["url"],
        ]
        proc = run_command(args, timeout=420, attempts=2)
        log_path = log_root / f"video__{row['video_id']}.log"
        log_path.write_text(
            f"COMMAND: {' '.join(args)}\nRETURN_CODE: {proc.returncode}\n\nSTDERR\n{proc.stderr}\n\nSTDOUT\n{proc.stdout}",
            encoding="utf-8",
        )

        info_files = list(tmp_dir.glob(f"{row['video_id']}*.info.json"))
        info: dict[str, Any] = {}
        if info_files:
            try:
                info = json.loads(info_files[0].read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                info = {}

        copied: list[Path] = []
        for source in tmp_dir.iterdir():
            if not source.is_file():
                continue
            target = channel_dir / source.name
            shutil.copy2(source, target)
            copied.append(target)

        caption_files = choose_caption_files(channel_dir, row["video_id"])

        def caption_rank(path: Path) -> tuple[int, str]:
            name = path.name.lower()
            if ".ko." in name and "orig" not in name:
                return (0, name)
            if ".ko-" in name or ".ko_" in name:
                return (1, name)
            if ".en." in name:
                return (2, name)
            return (3, name)

        caption_files.sort(key=caption_rank)
        normalized: list[dict[str, Any]] = []
        for caption in caption_files:
            lang_token = caption.name[len(row["video_id"]) + 1 :].rsplit(".", 1)[0]
            destination = text_dir / f"{row['video_id']}__{lang_token}.txt"
            try:
                normalized.append(normalize_caption(caption, destination))
            except Exception as exc:
                normalized.append({"source_file": str(caption), "error": repr(exc)})

        manual = info.get("subtitles") or {}
        automatic = info.get("automatic_captions") or {}
        subtitle_kind = "none"
        if manual:
            subtitle_kind = "manual"
        elif automatic:
            subtitle_kind = "automatic"
        elif caption_files:
            subtitle_kind = "downloaded_unknown"

        title = info.get("title") or row.get("flat_title")
        upload_date = info.get("upload_date") or row.get("flat_upload_date")
        description_file = next((p for p in copied if p.suffix == ".description"), None)
        return {
            **row,
            "fetch_ok": proc.returncode == 0,
            "fetch_return_code": proc.returncode,
            "fetch_error": None if proc.returncode == 0 else proc.stderr[-4000:],
            "log": str(log_path),
            "title": title,
            "description": info.get("description"),
            "description_file": str(description_file) if description_file else None,
            "channel_id": info.get("channel_id") or row.get("resolved_channel_id"),
            "channel_url": info.get("channel_url"),
            "uploader": info.get("uploader"),
            "duration": info.get("duration") or row.get("flat_duration"),
            "timestamp": info.get("timestamp") or row.get("flat_timestamp"),
            "upload_date": upload_date,
            "availability": info.get("availability"),
            "live_status": info.get("live_status"),
            "view_count": info.get("view_count"),
            "like_count": info.get("like_count"),
            "comment_count": info.get("comment_count"),
            "was_live": info.get("was_live"),
            "age_limit": info.get("age_limit"),
            "manual_caption_languages": sorted(manual.keys()),
            "automatic_caption_languages": sorted(automatic.keys()),
            "subtitle_kind": subtitle_kind,
            "caption_files": [str(p) for p in caption_files],
            "normalized_transcripts": normalized,
            "raw_files": [str(p) for p in copied],
        }


def iter_sentences(text: str) -> Iterator[str]:
    for segment in re.split(r"(?<=[.!?。！？])\s+|\n+", text):
        segment = re.sub(r"^\[[^\]]+\]\s*", "", segment).strip()
        if segment:
            yield segment


def build_ontology_evidence(records: list[dict[str, Any]], output_root: Path) -> dict[str, Any]:
    evidence_dir = output_root / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    counts: dict[str, Counter[str]] = defaultdict(Counter)
    video_hits: dict[str, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    snippets: list[dict[str, Any]] = []

    for record in records:
        transcripts = record.get("normalized_transcripts") or []
        selected = next((t for t in transcripts if t.get("text_file") and not t.get("error")), None)
        if not selected:
            continue
        path = Path(selected["text_file"])
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        lower = text.lower()
        for concept, terms in ONTOLOGY.items():
            total = 0
            for term in terms:
                total += lower.count(term.lower())
            if total:
                counts[record["channel_key"]][concept] += total
                video_hits[record["channel_key"]][concept].add(record["video_id"])
                concept_snippets = 0
                for sentence in iter_sentences(text):
                    sentence_lower = sentence.lower()
                    hit_terms = [t for t in terms if t.lower() in sentence_lower]
                    if hit_terms:
                        snippets.append(
                            {
                                "channel": record["channel"],
                                "channel_key": record["channel_key"],
                                "video_id": record["video_id"],
                                "title": record.get("title"),
                                "concept": concept,
                                "terms": hit_terms,
                                "text": sentence[:1000],
                                "source": selected["text_file"],
                            }
                        )
                        concept_snippets += 1
                        if concept_snippets >= 8:
                            break

    with (evidence_dir / "ontology_snippets.jsonl").open("w", encoding="utf-8") as fh:
        for item in snippets:
            fh.write(json.dumps(item, ensure_ascii=False) + "\n")

    summary: dict[str, Any] = {}
    for channel in CHANNELS:
        summary[channel.key] = {
            "channel": channel.name,
            "term_mentions": dict(counts[channel.key].most_common()),
            "videos_with_concept": {
                concept: len(ids) for concept, ids in video_hits[channel.key].items()
            },
        }
    (evidence_dir / "ontology_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return summary


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def build_coverage(records: list[dict[str, Any]], inventory_status: list[dict[str, Any]]) -> dict[str, Any]:
    by_channel: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in records:
        by_channel[row["channel_key"]].append(row)

    channels: dict[str, Any] = {}
    for channel in CHANNELS:
        rows = by_channel[channel.key]
        fetched = sum(bool(r.get("fetch_ok")) for r in rows)
        any_caption = sum(bool(r.get("normalized_transcripts")) for r in rows)
        manual = sum(r.get("subtitle_kind") == "manual" for r in rows)
        automatic = sum(r.get("subtitle_kind") == "automatic" for r in rows)
        missing = len(rows) - any_caption
        channels[channel.key] = {
            "name": channel.name,
            "locator": channel.locator,
            "expected_channel_id": channel.expected_channel_id,
            "resolved_channel_ids": sorted({r.get("channel_id") for r in rows if r.get("channel_id")}),
            "inventoried_unique_videos": len(rows),
            "metadata_fetch_ok": fetched,
            "metadata_fetch_failed": len(rows) - fetched,
            "videos_with_any_normalized_caption": any_caption,
            "videos_without_caption": missing,
            "manual_caption_videos": manual,
            "automatic_caption_videos": automatic,
            "coverage_ratio": (any_caption / len(rows)) if rows else 0.0,
            "tab_counts": dict(Counter(tab for r in rows for tab in r.get("tabs", []))),
        }
    return {
        "generated_at": utc_now(),
        "channels": channels,
        "inventory_status": inventory_status,
        "total_unique_videos": len(records),
        "total_with_caption": sum(bool(r.get("normalized_transcripts")) for r in records),
        "total_without_caption": sum(not bool(r.get("normalized_transcripts")) for r in records),
    }


def write_markdown_report(
    path: Path,
    coverage: dict[str, Any],
    ontology: dict[str, Any],
    tool_versions: dict[str, Any],
) -> None:
    lines = [
        "# YouTube Triad Public Transcript Corpus",
        "",
        f"Generated: `{coverage['generated_at']}`",
        "",
        "This report distinguishes **public video inventory**, **metadata retrieval**, and **caption availability**. A video without public captions is recorded as such; it is not silently omitted or machine-transcribed from downloaded audio.",
        "",
        "## Toolchain",
        "",
        "```json",
        json.dumps(tool_versions, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Coverage",
        "",
        "| Channel | Unique uploads | Metadata OK | Captioned | No public caption | Coverage |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for item in coverage["channels"].values():
        lines.append(
            f"| {item['name']} | {item['inventoried_unique_videos']} | {item['metadata_fetch_ok']} | "
            f"{item['videos_with_any_normalized_caption']} | {item['videos_without_caption']} | "
            f"{item['coverage_ratio']:.1%} |"
        )
    lines.extend(["", "## Ontology mention counts", ""])
    for item in ontology.values():
        lines.append(f"### {item['channel']}")
        lines.append("")
        if not item["term_mentions"]:
            lines.append("No caption text was available for ontology extraction.")
            lines.append("")
            continue
        lines.append("| Concept | Mentions | Videos |")
        lines.append("|---|---:|---:|")
        for concept, count in item["term_mentions"].items():
            videos = item["videos_with_concept"].get(concept, 0)
            lines.append(f"| `{concept}` | {count} | {videos} |")
        lines.append("")
    lines.extend(
        [
            "## Evidence files",
            "",
            "- `inventory.jsonl`: de-duplicated upload inventory",
            "- `video_manifest.jsonl`: metadata, caption availability, errors and hashes",
            "- `transcripts/<channel>/`: normalized timestamped transcript text",
            "- `raw_captions/<channel>/`: public caption evidence and metadata",
            "- `evidence/ontology_snippets.jsonl`: bounded source snippets by concept",
            "- `logs/`: exact command outcomes for every inventory tab and video",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def get_tool_versions() -> dict[str, Any]:
    version_proc = run_command([sys.executable, "-m", "yt_dlp", "--version"], timeout=30, attempts=1)
    return {
        "python": sys.version,
        "platform": sys.platform,
        "yt_dlp": version_proc.stdout.strip() if version_proc.returncode == 0 else None,
        "yt_dlp_version_error": version_proc.stderr.strip() if version_proc.returncode else None,
        "script_sha256": sha256_file(Path(__file__)),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("youtube_triad_artifact"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-videos", type=int, default=0, help="0 means all inventoried videos")
    args = parser.parse_args()

    output_root: Path = args.out.resolve()
    raw_root = output_root / "raw_captions"
    log_root = output_root / "logs"
    output_root.mkdir(parents=True, exist_ok=True)
    raw_root.mkdir(parents=True, exist_ok=True)
    log_root.mkdir(parents=True, exist_ok=True)

    tool_versions = get_tool_versions()
    (output_root / "tool_versions.json").write_text(
        json.dumps(tool_versions, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    inventory_rows: list[dict[str, Any]] = []
    inventory_status: list[dict[str, Any]] = []
    for channel in CHANNELS:
        for tab in TABS:
            rows, status = inventory_tab(channel, tab, log_root)
            inventory_rows.extend(rows)
            inventory_status.append(status)

    inventory = deduplicate_inventory(inventory_rows)
    if args.max_videos > 0:
        inventory = inventory[: args.max_videos]
    write_jsonl(output_root / "inventory.jsonl", inventory)
    (output_root / "inventory_status.json").write_text(
        json.dumps(inventory_status, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    records: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        future_map = {
            executor.submit(
                fetch_one_video,
                row,
                output_root=output_root,
                raw_root=raw_root,
                log_root=log_root,
            ): row
            for row in inventory
        }
        for future in concurrent.futures.as_completed(future_map):
            row = future_map[future]
            try:
                records.append(future.result())
            except Exception as exc:
                records.append(
                    {
                        **row,
                        "fetch_ok": False,
                        "fetch_return_code": None,
                        "fetch_error": repr(exc),
                        "subtitle_kind": "none",
                        "normalized_transcripts": [],
                        "caption_files": [],
                        "raw_files": [],
                    }
                )

    records.sort(key=lambda r: (r["channel_key"], r.get("timestamp") or 0, r["video_id"]))
    write_jsonl(output_root / "video_manifest.jsonl", records)

    with (output_root / "video_manifest.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        fields = [
            "channel", "channel_key", "video_id", "title", "upload_date", "duration", "tabs",
            "fetch_ok", "subtitle_kind", "manual_caption_languages", "automatic_caption_languages",
            "normalized_transcript_count", "url", "fetch_error",
        ]
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for r in records:
            writer.writerow(
                {
                    "channel": r.get("channel"),
                    "channel_key": r.get("channel_key"),
                    "video_id": r.get("video_id"),
                    "title": r.get("title"),
                    "upload_date": r.get("upload_date"),
                    "duration": r.get("duration"),
                    "tabs": ",".join(r.get("tabs") or []),
                    "fetch_ok": r.get("fetch_ok"),
                    "subtitle_kind": r.get("subtitle_kind"),
                    "manual_caption_languages": ",".join(r.get("manual_caption_languages") or []),
                    "automatic_caption_languages": ",".join(r.get("automatic_caption_languages") or []),
                    "normalized_transcript_count": len(r.get("normalized_transcripts") or []),
                    "url": r.get("url"),
                    "fetch_error": r.get("fetch_error"),
                }
            )

    ontology = build_ontology_evidence(records, output_root)
    coverage = build_coverage(records, inventory_status)
    (output_root / "coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_markdown_report(output_root / "REPORT.md", coverage, ontology, tool_versions)

    artifact_files = sorted(p for p in output_root.rglob("*") if p.is_file())
    artifact_manifest = {
        "generated_at": utc_now(),
        "file_count": len(artifact_files),
        "files": [
            {
                "path": str(p.relative_to(output_root)),
                "size_bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            }
            for p in artifact_files
        ],
    }
    (output_root / "ARTIFACT_MANIFEST.json").write_text(
        json.dumps(artifact_manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    successful_tabs = sum(bool(s.get("ok")) for s in inventory_status)
    if successful_tabs == 0 or not inventory:
        print(json.dumps(coverage, ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(coverage, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
