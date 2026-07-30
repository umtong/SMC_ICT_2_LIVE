#!/usr/bin/env python3
"""Create a deterministic evidence-addressable concept index from the caption corpus."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Sequence


CONCEPTS: dict[str, tuple[str, ...]] = {
    "liquidity": (
        r"유동성", r"liquidity", r"스탑\s*헌팅", r"stop\s*hunt", r"sweep", r"스윕",
        r"raid", r"레이드", r"equal\s*(high|low)", r"동일\s*(고점|저점)", r"전고", r"전저",
    ),
    "market_structure": (
        r"시장\s*구조", r"market\s*structure", r"BOS", r"MSS", r"CHOCH",
        r"구조\s*(돌파|전환|변화)", r"고점.*저점", r"저점.*고점", r"추세\s*(전환|변화)",
    ),
    "imbalance_delivery": (
        r"\bFVG\b", r"fair\s*value\s*gap", r"페어\s*밸류\s*갭", r"불균형", r"imbalance",
        r"order\s*block", r"오더\s*블록", r"breaker", r"브레이커", r"mitigation", r"미티게이션",
        r"displacement", r"디스플레이스먼트", r"변위",
    ),
    "support_resistance_geometry": (
        r"지지", r"저항", r"support", r"resistance", r"추세선", r"trend\s*line", r"채널",
        r"channel", r"돌파", r"breakout", r"fake\s*out", r"페이크", r"트랩", r"trap",
    ),
    "chart_pattern": (
        r"패턴", r"pattern", r"더블\s*(탑|바텀)", r"double\s*(top|bottom)", r"헤드.*숄더",
        r"head.*shoulder", r"컵.*핸들", r"cup.*handle", r"다이아몬드", r"diamond", r"웨지",
        r"wedge", r"삼각", r"triangle", r"플래그", r"flag", r"하모닉", r"harmonic",
    ),
    "trend_momentum_indicators": (
        r"\bRSI\b", r"\bMACD\b", r"이동\s*평균", r"moving\s*average", r"\bEMA\b", r"\bSMA\b",
        r"stochastic", r"스토캐스틱", r"\bADX\b", r"모멘텀", r"momentum", r"다이버전스", r"divergence",
    ),
    "volatility_volume_indicators": (
        r"볼린저", r"bollinger", r"\bATR\b", r"변동성", r"volatility", r"거래량", r"volume",
        r"\bVWAP\b", r"\bOBV\b", r"\bMFI\b", r"켈트너", r"keltner", r"squeeze", r"스퀴즈",
    ),
    "multi_timeframe_context": (
        r"탑\s*다운", r"top\s*down", r"상위\s*시간", r"하위\s*시간", r"higher\s*timeframe",
        r"lower\s*timeframe", r"멀티\s*타임", r"multi.?timeframe", r"일봉", r"주봉", r"4시간",
        r"세션", r"session",
    ),
    "entry_confirmation": (
        r"진입", r"entry", r"확인", r"confirmation", r"리테스트", r"retest", r"되돌림", r"pullback",
        r"컨펌", r"trigger", r"트리거", r"confluence", r"컨플루언스", r"근거",
    ),
    "risk_exit": (
        r"손절", r"stop\s*loss", r"익절", r"take\s*profit", r"무효화", r"invalidation", r"리스크",
        r"risk", r"레버리지", r"leverage", r"포지션\s*사이즈", r"position\s*size", r"손익비", r"R\s*R",
    ),
    "execution_psychology": (
        r"시장가", r"지정가", r"limit\s*order", r"market\s*order", r"슬리피지", r"slippage",
        r"수수료", r"fee", r"심리", r"psychology", r"복수", r"FOMO", r"원칙", r"discipline",
    ),
}
COMPILED = {
    concept: [re.compile(pattern, flags=re.IGNORECASE) for pattern in patterns]
    for concept, patterns in CONCEPTS.items()
}


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def matched_concepts(text: str) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for concept, patterns in COMPILED.items():
        matches: list[str] = []
        for pattern in patterns:
            matches.extend(match.group(0) for match in pattern.finditer(text))
        if matches:
            result[concept] = sorted(set(matches), key=str.casefold)
    return result


def build(corpus_dir: Path) -> dict[str, Any]:
    videos = read_jsonl(corpus_dir / "videos.jsonl")
    occurrences: list[dict[str, Any]] = []
    category_counts: collections.Counter[str] = collections.Counter()
    channel_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)
    video_counts: dict[str, collections.Counter[str]] = collections.defaultdict(collections.Counter)

    for video in videos:
        if video.get("caption_status") != "ok":
            continue
        transcript_path = corpus_dir / video["transcript_jsonl"]
        for segment in read_jsonl(transcript_path):
            matches = matched_concepts(segment["text"])
            if not matches:
                continue
            row = {
                "video_id": video["video_id"],
                "channel_slug": video["channel_slug"],
                "channel_display_name": video["channel_display_name"],
                "title": video.get("title"),
                "start_ms": segment["start_ms"],
                "duration_ms": segment["duration_ms"],
                "text": segment["text"],
                "concepts": matches,
            }
            occurrences.append(row)
            for concept in matches:
                category_counts[concept] += 1
                channel_counts[video["channel_slug"]][concept] += 1
                video_counts[video["video_id"]][concept] += 1

    occurrence_path = corpus_dir / "concept_occurrences.jsonl"
    occurrence_path.write_text(
        "".join(canonical_json(row) + "\n" for row in occurrences),
        encoding="utf-8",
        newline="\n",
    )

    representatives: dict[str, list[dict[str, Any]]] = {}
    for concept in CONCEPTS:
        candidates = [row for row in occurrences if concept in row["concepts"]]
        candidates.sort(
            key=lambda row: (
                -len(row["concepts"][concept]),
                -len(row["text"]),
                row["channel_slug"],
                row["video_id"],
                row["start_ms"],
            )
        )
        selected: list[dict[str, Any]] = []
        used_videos: set[str] = set()
        for row in candidates:
            if row["video_id"] in used_videos and len(used_videos) < 12:
                continue
            selected.append(row)
            used_videos.add(row["video_id"])
            if len(selected) >= 18:
                break
        representatives[concept] = selected

    index = {
        "schema_version": 1,
        "corpus_digest_sha256": json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))["corpus_digest_sha256"],
        "concept_definitions": CONCEPTS,
        "occurrence_count": len(occurrences),
        "concept_counts": dict(sorted(category_counts.items())),
        "channel_concept_counts": {key: dict(sorted(value.items())) for key, value in sorted(channel_counts.items())},
        "video_concept_counts": {key: dict(sorted(value.items())) for key, value in sorted(video_counts.items())},
        "representative_evidence": representatives,
        "occurrence_sha256": hashlib.sha256(occurrence_path.read_bytes()).hexdigest(),
    }
    (corpus_dir / "concept_index.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    lines = [
        "# Transcript Evidence Map\n",
        f"Corpus digest: `{index['corpus_digest_sha256']}`  ",
        f"Concept-addressable segments: **{len(occurrences):,}**\n",
    ]
    for concept, count in category_counts.most_common():
        lines.append(f"## {concept} — {count:,} segments\n")
        for row in representatives.get(concept, [])[:12]:
            seconds = row["start_ms"] / 1000
            lines.append(
                f"- `{row['channel_display_name']}` / `{row['video_id']}` / {seconds:.3f}s — "
                f"{row['text']}\n"
            )
    (corpus_dir / "EVIDENCE_MAP.md").write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return index


def self_test() -> None:
    matches = matched_concepts("유동성 스윕 후 MSS와 FVG 리테스트에서 진입하고 손절은 전저 아래")
    assert {"liquidity", "market_structure", "imbalance_delivery", "entry_confirmation", "risk_exit"} <= set(matches)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        self_test()
        print("self-test: PASS")
        return 0
    if not args.corpus:
        parser.error("--corpus is required")
    result = build(args.corpus)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
