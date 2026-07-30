#!/usr/bin/env python3
"""Run all resolved alpha families and select survivors by pre-2024 evidence."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: Path, old: str, new: str) -> bool:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return False
    if old not in text:
        raise RuntimeError(f"anchor missing in {path}: {old[:80]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")
    return True


def main() -> int:
    changed = []
    second = ROOT / ".github/workflows/yt-trinity-compression-bpr-research.yml"
    old_second = """              decision = str(payload.get('decision') or 'MISSING_PARENT_DECISION')\n              run_second = decision == 'ECONOMIC_FAIL_SWITCH_ALPHA'"""
    new_second = """              decision = str(payload.get('decision') or 'MISSING_PARENT_DECISION')\n              run_second = decision in {\n                  'ECONOMIC_FAIL_SWITCH_ALPHA',\n                  'POSITIVE_PRE2024_OPENED_2024H1_COARSE',\n              }"""
    if replace_once(second, old_second, new_second):
        changed.append(str(second))

    third = ROOT / ".github/workflows/yt-trinity-smt-cisd-research.yml"
    old_third = """              decision = str(payload.get('decision') or 'MISSING_PARENT_DECISION')\n              run_third = decision == 'ECONOMIC_FAIL_SWITCH_ALPHA'"""
    new_third = """              decision = str(payload.get('decision') or 'MISSING_PARENT_DECISION')\n              run_third = decision in {\n                  'ECONOMIC_FAIL_SWITCH_ALPHA',\n                  'POSITIVE_PRE2024_OPENED_2024H1_COARSE',\n              }"""
    if replace_once(third, old_third, new_third):
        changed.append(str(third))

    selector = ROOT / "research/yt_trinity_ml/select_coarse_survivor.py"
    old_key = """def positive_key(row: Mapping[str, Any]) -> tuple[float, float, float, float]:\n    metrics = row[\"official_metrics\"]\n    return (\n        float(metrics.get(\"geometric_daily_growth\") or 0.0),\n        float(metrics.get(\"account_multiple\") or 0.0),\n        -float(metrics.get(\"maximum_drawdown\") or 1.0),\n        float(metrics.get(\"completed_trades\") or 0.0),\n    )"""
    new_key = """def positive_key(row: Mapping[str, Any]) -> tuple[float, float, float, float]:\n    # H1 is only a survival gate.  Magnitude selection remains owned by the\n    # frozen pre-2024 sequential account to avoid choosing the route on the\n    # official-period return being reported later.\n    basic = row.get(\"selected_basic\")\n    metrics = basic.get(\"metrics\") if isinstance(basic, Mapping) else {}\n    if not isinstance(metrics, Mapping):\n        metrics = {}\n    return (\n        float(metrics.get(\"geometric_daily_growth\") or 0.0),\n        float(metrics.get(\"account_multiple\") or 0.0),\n        -float(metrics.get(\"maximum_drawdown\") or 1.0),\n        float(metrics.get(\"completed_trades\") or 0.0),\n    )"""
    if replace_once(selector, old_key, new_key):
        changed.append(str(selector))
    print("\n".join(changed) if changed else "alpha-chain selection fix already present")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
