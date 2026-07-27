#!/usr/bin/env python3
"""Integrate the HTF OTE route into causal selection and full replay."""

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
    selector = ROOT / "research/yt_trinity_ml/select_coarse_survivor.py"
    replace(
        selector,
        '''    (\n        "ifvg_failure",\n        "YT_TRINITY_FAILED_DISPLACEMENT_IFVG_ACTION_VALUE_V1",\n        "IFVG_FAILURE_RUN_POINTER.json",\n    ),\n)''',
        '''    (\n        "ifvg_failure",\n        "YT_TRINITY_FAILED_DISPLACEMENT_IFVG_ACTION_VALUE_V1",\n        "IFVG_FAILURE_RUN_POINTER.json",\n    ),\n    (\n        "htf_ote",\n        "YT_TRINITY_HTF_OTE_FVG_ACTION_VALUE_V1",\n        "HTF_OTE_RUN_POINTER.json",\n    ),\n)''',
    )

    full = ROOT / "research/yt_trinity_ml/run_full_sequential_survivor.py"
    replace(
        full,
        'import run_ifvg_failure_research as ifvg_failure\nimport run_smt_cisd_research as smt',
        'import run_htf_ote_continuation as htf_ote\nimport run_ifvg_failure_research as ifvg_failure\nimport run_smt_cisd_research as smt',
    )
    replace(
        full,
        'if route_key not in {"cisd_bpr_ifvg", "compression_bpr", "smt_cisd", "ifvg_failure"}:',
        'if route_key not in {"cisd_bpr_ifvg", "compression_bpr", "smt_cisd", "ifvg_failure", "htf_ote"}:',
    )
    replace(
        full,
        '''    elif route_key == "compression_bpr":\n        generator = compression.generate_candidates\n    else:\n        generator = ifvg_failure.generate_candidates''',
        '''    elif route_key == "compression_bpr":\n        generator = compression.generate_candidates\n    elif route_key == "ifvg_failure":\n        generator = ifvg_failure.generate_candidates\n    else:\n        generator = htf_ote.generate_candidates''',
    )

    selection_workflow = ROOT / ".github/workflows/yt-trinity-coarse-survivor-selection.yml"
    replace(
        selection_workflow,
        '''      - research/yt_trinity_ml/IFVG_FAILURE_RUN_POINTER.json\n      - research/yt_trinity_ml/select_coarse_survivor.py''',
        '''      - research/yt_trinity_ml/IFVG_FAILURE_RUN_POINTER.json\n      - research/yt_trinity_ml/HTF_OTE_RUN_POINTER.json\n      - research/yt_trinity_ml/select_coarse_survivor.py''',
    )

    full_workflow = ROOT / ".github/workflows/yt-trinity-full-sequential-survivor.yml"
    replace(
        full_workflow,
        '''            research/yt_trinity_ml/run_compression_bpr_continuation.py \\\n            research/yt_trinity_ml/run_ifvg_failure_research.py \\\n            research/yt_trinity_ml/run_smt_cisd_research.py''',
        '''            research/yt_trinity_ml/run_compression_bpr_continuation.py \\\n            research/yt_trinity_ml/run_htf_ote_continuation.py \\\n            research/yt_trinity_ml/run_ifvg_failure_research.py \\\n            research/yt_trinity_ml/run_smt_cisd_research.py''',
    )

    tests = ROOT / "research/yt_trinity_ml/tests/test_new_alpha_runners.py"
    replace(
        tests,
        'import run_full_sequential_survivor as full\nimport run_ifvg_failure_research as ifvg_failure',
        'import run_full_sequential_survivor as full\nimport run_htf_ote_continuation as htf_ote\nimport run_ifvg_failure_research as ifvg_failure',
    )
    replace(
        tests,
        '''    ifvg_features, ifvg_rows = ifvg_failure.generate_candidates(btc, "BTCUSDT")\n    smt_features, smt_rows = smt.generate_joint_candidates({"BTCUSDT": btc, "ETHUSDT": eth})''',
        '''    ifvg_features, ifvg_rows = ifvg_failure.generate_candidates(btc, "BTCUSDT")\n    htf_features, htf_rows = htf_ote.generate_candidates(btc, "BTCUSDT")\n    smt_features, smt_rows = smt.generate_joint_candidates({"BTCUSDT": btc, "ETHUSDT": eth})''',
    )
    replace(
        tests,
        '''    assert len(ifvg_features) == len(btc)\n    assert set(smt_features) == {"BTCUSDT", "ETHUSDT"}\n    for row in [*cisd_rows, *compression_rows, *ifvg_rows, *smt_rows]:''',
        '''    assert len(ifvg_features) == len(btc)\n    assert len(htf_features) == len(btc)\n    assert set(smt_features) == {"BTCUSDT", "ETHUSDT"}\n    for row in [*cisd_rows, *compression_rows, *ifvg_rows, *htf_rows, *smt_rows]:''',
    )
    print("HTF OTE route integration applied")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
