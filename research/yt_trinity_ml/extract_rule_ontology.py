#!/usr/bin/env python3
"""Extract timestamp-addressable trading rule windows from the complete corpus.

This deterministic recall-first pass does not claim keyword matches are profitable.
It creates the evidence surface from which the compact human-audited ontology and
frozen system contract are derived.
"""

from __future__ import annotations

import argparse
import collections
import hashlib
import importlib.util
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence


RULE_PATTERNS: dict[str, tuple[str, ...]] = {
    "context": (
        r"상위\s*(시간|프레임)", r"하위\s*(시간|프레임)", r"추세", r"횡보", r"세션", r"장세",
        r"변동성", r"거래량", r"모멘텀", r"다이버전스", r"정배열", r"역배열", r"과매수", r"과매도",
    ),
    "location": (
        r"유동성", r"고점", r"저점", r"지지", r"저항", r"추세선", r"채널", r"오더\s*블록",
        r"FVG", r"갭", r"매물대", r"밸류", r"프리미엄", r"디스카운트", r"VWAP",
    ),
    "trigger": (
        r"돌파", r"이탈", r"스윕", r"휩쏘", r"페이크", r"리테스트", r"되돌림", r"반등", r"반락",
        r"크로스", r"골든\s*크로스", r"데드\s*크로스", r"다이버전스", r"구조\s*(전환|변화|돌파)",
        r"BOS", r"CHOCH", r"MSS", r"장악", r"마감", r"확정", r"컨펌",
    ),
    "entry": (
        r"진입", r"매수", r"매도", r"롱", r"숏", r"포지션", r"타점", r"주문", r"받아",
        r"따라붙", r"눌림", r"반등\s*매매", r"돌파\s*매매",
    ),
    "invalidation": (
        r"손절", r"스탑", r"무효", r"깨지면", r"이탈하면", r"넘으면", r"아래로", r"위로",
        r"정리", r"컷", r"리스크", r"청산",
    ),
    "target": (
        r"익절", r"목표", r"타겟", r"수익\s*실현", r"다음\s*(고점|저점|저항|지지|유동성)",
        r"전고", r"전저", r"손익비", r"분할\s*청산", r"트레일링",
    ),
    "condition": (
        r"만약", r"때", r"하면", r"한다면", r"경우", r"확인", r"기다", r"전제", r"조건",
        r"반드시", r"우선", r"그\s*다음", r"이후", r"동시에", r"겹치",
    ),
}
COMPILED = {
    slot: tuple(re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns)
    for slot, patterns in RULE_PATTERNS.items()
}
SIDE_PATTERNS = {
    "LONG": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (r"롱", r"매수", r"상승", r"반등", r"양봉")),
    "SHORT": tuple(re.compile(pattern, re.IGNORECASE) for pattern in (r"숏", r"매도", r"하락", r"반락", r"음봉")),
}


@dataclass(frozen=True)
class Segment:
    start_ms: int
    duration_ms: int
    text: str


@dataclass(frozen=True)
class Window:
    start_index: int
    end_index: int
    start_ms: int
    end_ms: int
    text: str


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_concept_module(path: Path):
    spec = importlib.util.spec_from_file_location("yt_trinity_build_concept_index", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def match_slots(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for slot, patterns in COMPILED.items():
        matches = sorted({match.group(0) for pattern in patterns for match in pattern.finditer(text)}, key=str.casefold)
        if matches:
            result[slot] = matches
    return result


def infer_side(text: str) -> str:
    counts = {
        side: sum(len(pattern.findall(text)) for pattern in patterns)
        for side, patterns in SIDE_PATTERNS.items()
    }
    if counts["LONG"] > counts["SHORT"]:
        return "LONG"
    if counts["SHORT"] > counts["LONG"]:
        return "SHORT"
    return "BOTH_OR_UNSPECIFIED"


def build_windows(segments: Sequence[Segment], radius: int = 3, maximum_ms: int = 120_000) -> list[Window]:
    anchors = [index for index, segment in enumerate(segments) if len(match_slots(segment.text)) >= 2 or "entry" in match_slots(segment.text)]
    ranges: list[tuple[int, int]] = []
    for anchor in anchors:
        start = max(0, anchor - radius)
        end = min(len(segments), anchor + radius + 1)
        while end - start > 1 and segments[end - 1].start_ms + segments[end - 1].duration_ms - segments[start].start_ms > maximum_ms:
            if anchor - start > end - 1 - anchor:
                start += 1
            else:
                end -= 1
        ranges.append((start, end))
    merged: list[tuple[int, int]] = []
    for start, end in sorted(set(ranges)):
        if merged and start <= merged[-1][1] - 2:
            candidate = (merged[-1][0], max(merged[-1][1], end))
            duration = segments[candidate[1] - 1].start_ms + segments[candidate[1] - 1].duration_ms - segments[candidate[0]].start_ms
            if duration <= maximum_ms:
                merged[-1] = candidate
                continue
        merged.append((start, end))
    result: list[Window] = []
    for start, end in merged:
        selected = segments[start:end]
        if selected:
            result.append(
                Window(
                    start,
                    end,
                    selected[0].start_ms,
                    selected[-1].start_ms + selected[-1].duration_ms,
                    " ".join(segment.text for segment in selected),
                )
            )
    return result


def family_signature(concepts: Mapping[str, Any], slots: Mapping[str, Any], text: str) -> str:
    names = set(concepts)
    if "liquidity" in names and ("market_structure" in names or re.search(r"스윕|휩쏘|raid", text, re.IGNORECASE)):
        return "LIQUIDITY_SWEEP_REVERSAL"
    if "market_structure" in names and ("imbalance_delivery" in names or re.search(r"돌파|리테스트|displacement", text, re.IGNORECASE)):
        return "DISPLACEMENT_BREAK_RETEST_CONTINUATION"
    if "volatility_volume_indicators" in names and re.search(r"스퀴즈|수축|돌파|확장", text, re.IGNORECASE):
        return "COMPRESSION_EXPANSION_CONTEXT"
    if "trend_momentum_indicators" in names:
        return "INDICATOR_CONTEXT_OR_CONFIRMATION"
    if "chart_pattern" in names or "support_resistance_geometry" in names:
        return "GEOMETRIC_PATTERN_CONTEXT"
    return "UNCLASSIFIED_RULE_EVIDENCE"


def extract(corpus: Path, concept_script: Path) -> dict[str, Any]:
    concept_module = load_concept_module(concept_script)
    videos = read_jsonl(corpus / "videos.jsonl")
    rows: list[dict[str, Any]] = []
    for video in videos:
        if video.get("caption_status") != "ok":
            continue
        raw_segments = read_jsonl(corpus / video["transcript_jsonl"])
        segments = [Segment(int(row["start_ms"]), int(row["duration_ms"]), str(row["text"])) for row in raw_segments]
        for window in build_windows(segments):
            slots = match_slots(window.text)
            concepts = concept_module.matched_concepts(window.text)
            explicit_slots = {"entry", "invalidation", "target"} & set(slots)
            if "entry" not in slots and len(slots) < 3:
                continue
            score = 4 * len(explicit_slots) + 2 * len(slots) + len(concepts) + min(5, sum(len(value) for value in slots.values()))
            rows.append(
                {
                    "channel_slug": video["channel_slug"],
                    "channel_display_name": video["channel_display_name"],
                    "video_id": video["video_id"],
                    "title": video.get("title"),
                    "start_ms": window.start_ms,
                    "end_ms": window.end_ms,
                    "text": window.text,
                    "slots": slots,
                    "concepts": concepts,
                    "side": infer_side(window.text),
                    "family_signature": family_signature(concepts, slots, window.text),
                    "explicitness_score": score,
                }
            )

    rows.sort(key=lambda row: (-row["explicitness_score"], row["channel_slug"], row["video_id"], row["start_ms"]))
    output_path = corpus / "rule_evidence_windows.jsonl"
    output_path.write_text("".join(canonical_json(row) + "\n" for row in rows), encoding="utf-8", newline="\n")

    groups: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for row in rows:
        groups[row["family_signature"]].append(row)
    ontology: dict[str, Any] = {
        "schema_version": 1,
        "corpus_digest_sha256": json.loads((corpus / "manifest.json").read_text(encoding="utf-8"))["corpus_digest_sha256"],
        "rule_window_count": len(rows),
        "rule_window_sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
        "families": {},
    }
    for family, evidence in sorted(groups.items()):
        channels = sorted({row["channel_slug"] for row in evidence})
        videos_for_family = sorted({row["video_id"] for row in evidence})
        slots = collections.Counter(slot for row in evidence for slot in row["slots"])
        concepts = collections.Counter(concept for row in evidence for concept in row["concepts"])
        representatives: list[dict[str, Any]] = []
        used_videos: set[str] = set()
        for row in evidence:
            if row["video_id"] in used_videos and len(used_videos) < 20:
                continue
            representatives.append(row)
            used_videos.add(row["video_id"])
            if len(representatives) >= 24:
                break
        ontology["families"][family] = {
            "evidence_windows": len(evidence),
            "unique_channels": channels,
            "unique_video_count": len(videos_for_family),
            "slot_counts": dict(sorted(slots.items())),
            "concept_counts": dict(sorted(concepts.items())),
            "representative_evidence": representatives,
        }

    ontology_path = corpus / "rule_ontology_candidates.json"
    ontology_path.write_text(json.dumps(ontology, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return ontology


def self_test() -> None:
    text = "상위 추세가 상승이고 유동성을 스윕한 뒤 구조 전환을 확인하면 롱 진입, 전저 이탈 시 손절하고 다음 고점에서 익절"
    slots = match_slots(text)
    assert {"context", "location", "trigger", "entry", "invalidation", "target", "condition"} <= set(slots)
    assert infer_side(text) == "LONG"


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--concept-script", type=Path, default=Path(__file__).with_name("build_concept_index.py"))
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        print("self-test: PASS")
        return 0
    if args.corpus is None:
        parser.error("--corpus is required")
    result = extract(args.corpus, args.concept_script)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
