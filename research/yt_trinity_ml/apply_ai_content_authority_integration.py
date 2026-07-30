#!/usr/bin/env python3
"""Integrate the validated AI-transcription corpus into authority/state selection."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"anchor missing in {path}: {old[:140]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main() -> int:
    selector = ROOT / "research/yt_trinity_ml/select_complete_content_corpus.py"
    replace_once(
        selector,
        '''POINTERS = (\n    "COMPLETE_CONTENT_CORPUS_POINTER.json",\n    "COBALT_CONTENT_CORPUS_POINTER.json",\n    "FULL_CAPTION_CORPUS_POINTER.json",\n)''',
        '''POINTERS = (\n    "COMPLETE_CONTENT_CORPUS_POINTER.json",\n    "COBALT_CONTENT_CORPUS_POINTER.json",\n    "AI_CONTENT_CORPUS_POINTER.json",\n    "FULL_CAPTION_CORPUS_POINTER.json",\n)''',
    )

    authority = ROOT / ".github/workflows/yt-trinity-content-authority.yml"
    replace_once(
        authority,
        '''      - research/yt_trinity_ml/COBALT_CONTENT_CORPUS_POINTER.json\n      - research/yt_trinity_ml/FULL_CAPTION_CORPUS_POINTER.json''',
        '''      - research/yt_trinity_ml/COBALT_CONTENT_CORPUS_POINTER.json\n      - research/yt_trinity_ml/AI_CONTENT_CORPUS_POINTER.json\n      - research/yt_trinity_ml/FULL_CAPTION_CORPUS_POINTER.json''',
    )

    state = ROOT / ".github/workflows/yt-trinity-execution-state.yml"
    text = state.read_text(encoding="utf-8")
    trigger_anchor = "      - research/yt_trinity_ml/*CONTRACT*.json\n"
    trigger_line = "      - research/yt_trinity_ml/CERTIFIED_TARGET_CANDIDATE.json\n"
    if trigger_line not in text:
        if trigger_anchor not in text:
            raise RuntimeError("execution-state trigger anchor missing")
        text = text.replace(trigger_anchor, trigger_anchor + trigger_line, 1)
    allowed_anchor = "              'COBALT_CONTENT_CORPUS_POINTER.json',\n"
    additions = (
        "              'AI_CONTENT_CORPUS_POINTER.json',\n"
        "              'SESSION_PO3_RUN_POINTER.json',\n"
        "              'CERTIFIED_TARGET_CANDIDATE.json',\n"
    )
    for line in additions.splitlines(keepends=True):
        if line not in text:
            if allowed_anchor not in text:
                raise RuntimeError("execution-state allowed-name anchor missing")
            text = text.replace(allowed_anchor, allowed_anchor + line, 1)
            allowed_anchor = line
    public_glob = "                  or path.name.startswith('PUBLIC_TRADE_TAPE_RESULT_')\n"
    strict_glob = "                  or path.name.startswith('STRICT_TRADE_TAPE_RESULT_')\n"
    if strict_glob not in text:
        if public_glob not in text:
            raise RuntimeError("execution-state result glob anchor missing")
        text = text.replace(public_glob, public_glob + strict_glob, 1)
    state.write_text(text, encoding="utf-8")

    test_path = ROOT / "research/yt_trinity_ml/tests/test_content_authority.py"
    if not test_path.exists():
        test_path.write_text(
            '''from __future__ import annotations\n\nimport json\nimport sys\nfrom pathlib import Path\n\nimport select_complete_content_corpus as selector\n\n\ndef pointer(provider: str, native: int, asr: int, characters: int) -> dict:\n    counts = {}\n    if native:\n        counts[provider] = native\n    if asr:\n        counts["documented_public_ai_transcription_api"] = asr\n    return {\n        "schema_version": 1,\n        "run_id": 123,\n        "source_sha": "a" * 40,\n        "artifact_name": f"artifact-{provider}",\n        "manifest_sha256": "b" * 64,\n        "rule_ontology_sha256": "c" * 64,\n        "manifest": {\n            "decision": "PASS_COMPLETE",\n            "content_attempt_complete": True,\n            "caption_attempt_complete": True,\n            "unique_public_video_count": native + asr,\n            "total_caption_characters": characters,\n            "total_caption_segments": 1000,\n            "caption_provider_counts": counts,\n        },\n    }\n\n\ndef test_ai_content_pointer_is_eligible_and_native_wins_quality_tie(tmp_path: Path) -> None:\n    (tmp_path / "AI_CONTENT_CORPUS_POINTER.json").write_text(\n        json.dumps(pointer("ai", 0, 10, 50_000)), encoding="utf-8"\n    )\n    (tmp_path / "COMPLETE_CONTENT_CORPUS_POINTER.json").write_text(\n        json.dumps(pointer("youtube_native", 10, 0, 45_000)), encoding="utf-8"\n    )\n    output = tmp_path / "selected.json"\n    original = sys.argv\n    try:\n        sys.argv = ["select", "--root", str(tmp_path), "--output", str(output)]\n        selector.main()\n    finally:\n        sys.argv = original\n    result = json.loads(output.read_text(encoding="utf-8"))\n    assert result["decision"] == "COMPLETE_CONTENT_AUTHORITY_SELECTED"\n    assert result["selected"]["pointer_file"] == "COMPLETE_CONTENT_CORPUS_POINTER.json"\n    assert any(row["pointer_file"] == "AI_CONTENT_CORPUS_POINTER.json" for row in result["alternatives"])\n''',
            encoding="utf-8",
        )
    print("AI content authority integration applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
