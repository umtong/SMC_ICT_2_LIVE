from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUTPUT = ROOT / "research_runs/ml_path_continuity/output"
DURABLE = ROOT / "research_results/r11_ml_path_continuity_001"
RESULT_ID = "RES-20260726-ML-PATH-CONTINUITY-001"
FIRST_PLACE_ID = "FIRST-20260726-ML-PATH-CONTINUITY-001"
TARGET = 0.01


def nested(value: Any, *keys: str, default: Any = None) -> Any:
    current = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return default
        current = current[key]
    return current


def finite_number(value: Any, default: float = float("nan")) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def git_show(ref: str, path: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(ROOT), "show", f"{ref}:{path}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def account_for(result: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    accounts = result.get("development_account")
    if not isinstance(accounts, dict):
        return "18.0", {}
    for key in ("18.0", "18", "18bp", "base"):
        value = accounts.get(key)
        if isinstance(value, dict):
            return key, value
    candidates: list[tuple[float, str, dict[str, Any]]] = []
    for key, value in accounts.items():
        if isinstance(value, dict):
            cost = finite_number(str(key).replace("bp", ""))
            if math.isfinite(cost):
                candidates.append((abs(cost - 18.0), str(key), value))
    if candidates:
        _, key, value = min(candidates)
        return key, value
    return "18.0", {}


def metric(account: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in account:
            return account[name]
    return default


def replace_line(text: str, label: str, value: str) -> str:
    pattern = rf"(?m)^- {re.escape(label)}:.*$"
    replacement = f"- {label}: {value}"
    if re.search(pattern, text):
        return re.sub(pattern, replacement, text, count=1)
    return text


def persist() -> int:
    result_path = OUTPUT / "RESULT.json"
    if not result_path.exists():
        raise FileNotFoundError(result_path)
    result = json.loads(result_path.read_text(encoding="utf-8"))
    DURABLE.mkdir(parents=True, exist_ok=True)
    shutil.copy2(result_path, DURABLE / "result.json")
    for name in ("SOURCE_MANIFEST.json", "CANDIDATES.csv", "TRADES.csv", "DAILY_NAV.csv", "SHA256SUMS.txt"):
        source = OUTPUT / name
        if source.exists():
            shutil.copy2(source, DURABLE / name)

    cost_key, account = account_for(result)
    growth = finite_number(metric(account, "geometric_daily_growth", "daily_geometric_growth"))
    total_return = finite_number(metric(account, "total_return", "return"))
    drawdown = finite_number(metric(account, "maximum_drawdown", "max_drawdown"))
    trades = int(finite_number(metric(account, "trades", "trade_count"), 0.0))
    pf = finite_number(metric(account, "profit_factor"))
    top_removed = finite_number(metric(
        account,
        "top10pct_positive_removed_return",
        "top10_positive_removed_return",
        "after_top10_return",
    ))
    median_bps = finite_number(metric(account, "median_trade_bps", "median_account_return_bps"))
    status = str(result.get("status", "UNKNOWN"))
    hard = str(result.get("hard_validity_status", "UNKNOWN"))
    unresolved = int(finite_number(metric(account, "unresolved", "unresolved_count"), 0.0))
    forced_liquidation = bool(metric(account, "forced_liquidation", "liquidated", default=False))

    subprocess.run(["git", "-C", str(ROOT), "fetch", "origin", "main", "--depth=1"], check=True)
    ranking = json.loads(git_show("origin/main", "control/ranking.json"))
    state_text = git_show("origin/main", "control/current-state.md")
    first = ranking.get("first_place") or {}
    first_growth = finite_number(nested(first, "metrics", "geometric_daily_growth"), -float("inf"))

    eligible = (
        hard in {"PASS", "PASS_INITIAL"}
        and status in {"TESTED_BELOW_GATE", "PROMISING_PRE2024_SURVIVOR", "VALIDATED", "GOAL_MET"}
        and math.isfinite(growth)
        and growth > 0.0
        and math.isfinite(drawdown)
        and drawdown < 1.0
        and not forced_liquidation
        and unresolved == 0
        and trades > 0
    )
    outranks = eligible and growth > first_growth
    now = datetime.now(timezone.utc).isoformat()
    decision = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "status": status,
        "hard_validity_status": hard,
        "base_cost_key": cost_key,
        "geometric_daily_growth": growth if math.isfinite(growth) else None,
        "target_gap": TARGET - growth if math.isfinite(growth) else None,
        "total_return": total_return if math.isfinite(total_return) else None,
        "maximum_drawdown": drawdown if math.isfinite(drawdown) else None,
        "trade_count": trades,
        "profit_factor": pf if math.isfinite(pf) else None,
        "median_trade_bps": median_bps if math.isfinite(median_bps) else None,
        "top10pct_positive_removed_return": top_removed if math.isfinite(top_removed) else None,
        "forced_liquidation": forced_liquidation,
        "unresolved_count": unresolved,
        "eligible_for_provisional_ranking": eligible,
        "prior_first_growth": first_growth if math.isfinite(first_growth) else None,
        "outranks_prior_first": outranks,
        "ranking_action": "PROMOTE_TO_FIRST" if outranks else "NO_FIRST_PLACE_CHANGE",
        "recorded_at": now,
    }
    (DURABLE / "rank_decision.json").write_text(
        json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    if not outranks:
        return 0

    old_rows = [row for row in ranking.get("ranked_candidates", []) if row.get("source_result_id") != RESULT_ID]
    new_row = {
        "rank": 1,
        "source_result_id": RESULT_ID,
        "candidate_label": "ML path-continuity structural first-passage router",
        "geometric_daily_growth": growth,
        "target_gap": TARGET - growth,
        "comparison_confidence": "LOW_TO_MODERATE",
        "comparison_status": "PROVISIONAL_PRE2024_DIFFERENT_EXECUTION_CONTRACT",
    }
    rows = [new_row] + old_rows
    rows.sort(key=lambda row: finite_number(row.get("target_gap"), float("inf")))
    for index, row in enumerate(rows, start=1):
        row["rank"] = index

    revision = int(ranking.get("revision", 0)) + 1
    ranking["revision"] = revision
    ranking["ranking_id"] = f"STRATEGY-RANKING-20260726-R{revision}"
    ranking["ranked_candidates"] = rows
    ranking["first_place"] = {
        "rank": 1,
        "first_place_id": FIRST_PLACE_ID,
        "candidate_type": "STRATEGY",
        "source_result_id": RESULT_ID,
        "source_pull_request": "https://github.com/umtong/SMC_ICT_2_LIVE/pull/170",
        "qualification_stage": "EXPLORATORY_PRE2024",
        "target_status": "MET" if growth >= TARGET else "NOT_MET",
        "selection_reason": "This hard-valid causal ML candidate has the highest recorded realistic after-cost geometric daily growth among ranked strategy results. Economic gates, concentration and pre-2024-only limitations remain disclosed separately.",
        "comparison_confidence": "LOW_TO_MODERATE",
        "metrics": {
            "candidate_id": str(result.get("candidate_id", result.get("best_candidate_id", "single_frozen_model"))),
            "family": "path_continuity_structural_first_passage",
            "base_cost_bps": finite_number(str(cost_key).replace("bp", ""), 18.0),
            "geometric_daily_growth": growth,
            "target_geometric_daily_growth": TARGET,
            "target_gap": TARGET - growth,
            "target_fraction": growth / TARGET,
            "target_multiple_required": TARGET / growth if growth > 0 else None,
            "total_return": total_return if math.isfinite(total_return) else None,
            "profit_factor": pf if math.isfinite(pf) else None,
            "maximum_drawdown": drawdown if math.isfinite(drawdown) else None,
            "trade_count": trades,
            "top10pct_removed_return": top_removed if math.isfinite(top_removed) else None,
            "median_account_return_bps": median_bps if math.isfinite(median_bps) else None,
            "actual_funding_included": bool(result.get("actual_funding_included", True)),
        },
        "sequential_evidence": {
            "train_period": "2021-01-01 through 2022-06-30",
            "calibration_period": "2022H2",
            "confirmation_period": "2023H1",
            "development_period": "2023H2",
            "2024_opened": bool(result.get("2024_opened", False)),
            "2025_opened": False,
            "2026_opened": False,
        },
        "known_weaknesses": [
            "The result is pre-2024 and not a sealed final OOS certification.",
            "Comparison uses a different information window and execution contract from older ranked results.",
            f"Top-10%-positive-trade-removed return: {top_removed if math.isfinite(top_removed) else 'unavailable'}.",
            f"Median trade at base cost: {median_bps if math.isfinite(median_bps) else 'unavailable'} bps.",
            "Bybit historical bar execution is less granular than final order-book deployment validation.",
        ],
    }
    ranking["updated_at"] = now
    ranking.setdefault("reconciliation_notes", []).extend([
        f"Inserted {RESULT_ID} after deterministic comparison against origin/main.",
        f"Base-cost geometric daily growth {growth:.12g} exceeded prior first {first_growth:.12g}.",
        "Promotion is provisional and does not grant deployment permission or research priority.",
    ])
    (ROOT / "control/ranking.json").write_text(
        json.dumps(ranking, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )

    state_text = re.sub(r"(?m)^- revision:\s*\d+\s*$", f"- revision: {revision}", state_text, count=1)
    state_text = replace_line(state_text, "current first place", f"`{FIRST_PLACE_ID}`")
    state_text = replace_line(state_text, "first-place stage", "`EXPLORATORY_PRE2024`")
    state_text = replace_line(state_text, "target_status", "`MET`" if growth >= TARGET else "`NOT_MET`")
    summary = f"""## Current strategy ranking

The current first place is the ML path-continuity structural first-passage router from `{RESULT_ID}` / PR #170.

- base-cost geometric daily growth: `{growth * 100:.7f}%`
- 1% target gap: `{(TARGET - growth) * 100:.7f} percentage points per UTC calendar day`
- total return: `{total_return * 100:.4f}%`
- maximum drawdown: `{drawdown * 100:.4f}%`
- trades: `{trades}`
- profit factor: `{pf if math.isfinite(pf) else 'unavailable'}`
- median trade: `{median_bps if math.isfinite(median_bps) else 'unavailable'} bps`
- top-10%-positive-trade-removed return: `{top_removed * 100 if math.isfinite(top_removed) else 'unavailable'}%`

It ranks first because it has the highest recorded hard-valid realistic after-cost geometric daily growth. The rank is provisional because the result is pre-2024, comparison contracts differ, and final Bybit order-book execution and sealed OOS remain unopened. Rank does not determine research priority or deployment permission.

"""
    state_text = re.sub(
        r"## Current strategy ranking\n.*?(?=## Ranking policy)",
        summary,
        state_text,
        flags=re.S,
    )
    (ROOT / "control/current-state.md").write_text(state_text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(persist())
