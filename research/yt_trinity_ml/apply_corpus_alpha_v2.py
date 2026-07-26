#!/usr/bin/env python3
"""Apply the transcript-derived alpha generator and execution realism corrections.

The patch is exact and idempotent so a GitHub runner can test the branch before the
resulting source changes are committed. It refuses ambiguous source states.
"""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent


def replace_exact(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if old in text:
        count = text.count(old)
        if count != 1:
            raise RuntimeError(f"expected exactly one replacement in {path}, found {count}: {old!r}")
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        return True
    if new in text:
        return False
    raise RuntimeError(f"neither old nor new source form found in {path}: {old!r}")


def main() -> int:
    pipeline = ROOT / "system" / "research_pipeline.py"
    execution = ROOT / "system" / "execution.py"

    replace_exact(
        pipeline,
        """from .core import (\n    EventCandidate,\n    FeatureConfig,\n    RiskConfig,\n    build_causal_features,\n    generate_event_candidates,\n)\n""",
        """from .core import EventCandidate, FeatureConfig, RiskConfig\nfrom .corpus_alpha import build_corpus_features, generate_corpus_candidates\n""",
    )
    replace_exact(
        pipeline,
        """        calculated = build_causal_features(frame, feature_config)\n        features[symbol] = calculated\n        candidates.extend(generate_event_candidates(calculated, symbol, feature_config))\n""",
        """        calculated = build_corpus_features(frame, feature_config)\n        features[symbol] = calculated\n        candidates.extend(generate_corpus_candidates(calculated, symbol))\n""",
    )
    replace_exact(
        execution,
        '        displayed = row.get("ask_size") if side > 0 else row.get("bid_size")\n',
        '        displayed = row.get("bid_size") if side > 0 else row.get("ask_size")\n',
    )
    replace_exact(
        execution,
        "            self._close_quantity(account, timestamp, row, position.open_quantity, ExitReason.TARGET, True)\n",
        "            self._close_quantity(account, timestamp, row, position.open_quantity, ExitReason.TARGET, False)\n",
    )
    print("corpus alpha v2 patch applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
