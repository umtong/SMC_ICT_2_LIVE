#!/usr/bin/env python3
"""Integrate the corpus-bound full result into trade-tape authority selection."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    if old not in text:
        raise RuntimeError(f"anchor missing in {path}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    selector = ROOT / "research/yt_trinity_ml/select_event_tape_authorities.py"
    text = selector.read_text(encoding="utf-8")
    text = text.replace(
        '''TARGET_DECISIONS = {\n    "TARGET_EXCEEDED_COARSE_EVENT_TAPE_REQUIRED",\n    "TARGET_POSSIBLE_ONLY_WITH_EXECUTION_EDGE_EVENT_TAPE_REQUIRED",\n}''',
        '''TARGET_DECISIONS = {\n    "TARGET_EXCEEDED_COARSE_EVENT_TAPE_REQUIRED",\n    "TARGET_POSSIBLE_ONLY_WITH_EXECUTION_EDGE_EVENT_TAPE_REQUIRED",\n    "TARGET_EXCEEDED_CORPUS_BOUND_COARSE_EVENT_TAPE_REQUIRED",\n    "TARGET_POSSIBLE_ONLY_WITH_CORPUS_BOUND_EXECUTION_EDGE",\n}''',
    )
    marker = "\n\ndef key(row: Mapping[str, Any]):"
    function = '''\n\ndef add_corpus_bound(path: Path, rows: list[dict[str, Any]]) -> None:\n    if not path.exists():\n        return\n    payload = json.loads(path.read_text(encoding="utf-8"))\n    decision = str(payload.get("decision") or "")\n    if decision not in TARGET_DECISIONS:\n        return\n    metrics = payload.get("realistic_metrics")\n    zero = payload.get("zero_friction_metrics_same_signals")\n    if not isinstance(metrics, Mapping) or not isinstance(zero, Mapping):\n        return\n    rows.append({\n        "authority_key": "corpus_bound_system",\n        "source_pointer": path.name,\n        "source_pointer_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),\n        "run_id": int(payload["run_id"]),\n        "source_sha": payload.get("source_sha"),\n        "artifact_name": payload.get("artifact_name"),\n        "decision": decision,\n        "strategy_id": payload.get("strategy_id"),\n        "route_key": "corpus_bound_pool",\n        "realistic_metrics": metrics,\n        "zero_friction_metrics": zero,\n        "evidence": payload.get("evidence"),\n        "corpus_binding": payload.get("corpus_binding"),\n        "frozen_config_sha256": payload.get("frozen_config_sha256"),\n    })\n'''
    if "def add_corpus_bound(" not in text:
        if marker not in text:
            raise RuntimeError("event-tape selector function anchor missing")
        text = text.replace(marker, function + marker, 1)
    old_call = '''    add_single(args.root / "FULL_SEQUENTIAL_COARSE_POINTER.json", rows)\n    add_pooled(args.root / "POOLED_TRINITY_RUN_POINTER.json", rows)'''
    new_call = '''    add_single(args.root / "FULL_SEQUENTIAL_COARSE_POINTER.json", rows)\n    add_pooled(args.root / "POOLED_TRINITY_RUN_POINTER.json", rows)\n    add_corpus_bound(args.root / "CORPUS_BOUND_RUN_POINTER.json", rows)'''
    if new_call not in text:
        if old_call not in text:
            raise RuntimeError("event-tape selector call anchor missing")
        text = text.replace(old_call, new_call, 1)
    selector.write_text(text, encoding="utf-8")

    workflow = ROOT / ".github/workflows/yt-trinity-event-tape-authority.yml"
    replace(
        workflow,
        '''      - research/yt_trinity_ml/POOLED_TRINITY_RUN_POINTER.json\n      - research/yt_trinity_ml/select_event_tape_authorities.py''',
        '''      - research/yt_trinity_ml/POOLED_TRINITY_RUN_POINTER.json\n      - research/yt_trinity_ml/CORPUS_BOUND_RUN_POINTER.json\n      - research/yt_trinity_ml/select_event_tape_authorities.py''',
    )

    tape = ROOT / "research/yt_trinity_ml/run_public_trade_tape_validation.py"
    text = tape.read_text(encoding="utf-8")
    old = '''        full = summary.get("official_full_period") or {}\n        execution = full.get("realistic_execution") or {}'''
    new = '''        full = summary.get("official_full_period") or {}\n        execution = summary.get("realistic_execution") or full.get("realistic_execution") or {}'''
    if new not in text:
        if old not in text:
            raise RuntimeError("trade-tape root execution anchor missing")
        text = text.replace(old, new, 1)
    text = text.replace(
        '"source_route_key": summary.get("route_key", "pooled_trinity"),',
        '"source_route_key": summary.get("route_key") or ("corpus_bound_pool" if summary.get("corpus_binding") else "pooled_trinity"),',
    )
    tape.write_text(text, encoding="utf-8")
    print("corpus-bound event-tape integration applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
