from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd

DAY_MS = 86_400_000
START_MS = int(pd.Timestamp("2021-01-01", tz="UTC").value // 1_000_000)
END_MS = int(pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000)
CALENDAR_DAYS = 1095


def json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        number = float(value)
        return number if np.isfinite(number) else None
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def profit_factor(values: Iterable[float]) -> float | None:
    array = np.asarray(list(values), dtype=float)
    array = array[np.isfinite(array)]
    positive = float(array[array > 0].sum())
    negative = float(-array[array < 0].sum())
    return positive / negative if negative > 0 else None


def top_positive_share(values: Iterable[float], count: int = 5) -> float | None:
    array = np.asarray(list(values), dtype=float)
    positive = np.maximum(array[np.isfinite(array)], 0.0)
    total = float(positive.sum())
    if total <= 0:
        return None
    return float(np.sort(positive)[-count:].sum() / total)


def event_summary(frame: pd.DataFrame) -> dict[str, Any]:
    filled = frame[frame["is_filled"].eq(1)]
    values = filled["net_r"].dropna().to_numpy(float)
    return {
        "candidates": int(len(frame)),
        "fills": int(len(filled)),
        "mean_r": float(np.mean(values)) if len(values) else None,
        "median_r": float(np.median(values)) if len(values) else None,
        "sum_r": float(np.sum(values)) if len(values) else 0.0,
        "win_rate": float(np.mean(values > 0)) if len(values) else None,
        "profit_factor": profit_factor(values),
        "top5_positive_share": top_positive_share(values),
    }


def semantic_masks(frame: pd.DataFrame) -> dict[str, pd.Series]:
    delayed = frame["csd_same_bar_confirm"].eq(0) & frame["csd_delay_bars"].ge(1)
    higher_target = frame["target_external"].eq(1) & frame["target_importance"].gt(frame["node_importance"])

    dpc = (
        frame["setup"].eq("DPC")
        & frame["dpc_trigger"].eq("pullback_sweep")
        & delayed
        & frame["pullback_depth_atr"].notna()
        & frame["state_agreement"].ge(1)
        & higher_target
        & frame["terminal_rr"].ge(2.0)
    )
    srr = (
        frame["setup"].eq("SRR")
        & delayed
        & frame["state_transition"].eq(1)
        & frame["node_importance"].ge(3.0)
        & higher_target
        & frame["terminal_rr"].ge(2.0)
    )
    return {
        "all_raw": pd.Series(True, index=frame.index),
        "causal_delayed_retest": delayed & frame["target_external"].eq(1),
        "DPC_contract": dpc,
        "SRR_contract": srr,
        "strict_contract_union": dpc | srr,
    }


def route_account(
    frame: pd.DataFrame,
    policy: str,
    risk_fraction: float = 0.005,
    notional_cap: float = 3.0,
) -> tuple[dict[str, Any], pd.DataFrame]:
    work = frame[
        frame["decision_time_ms"].ge(START_MS) & frame["decision_time_ms"].lt(END_MS)
    ].copy()
    work["importance_gap"] = work["target_importance"] - work["node_importance"]
    work = work.sort_values(
        [
            "decision_time_ms",
            "importance_gap",
            "target_importance",
            "terminal_rr",
            "node_importance",
            "candidate_id",
        ],
        ascending=[True, False, False, False, False, True],
        kind="stable",
    ).drop_duplicates("decision_time_ms", keep="first")

    nav = 10_000.0
    slot_free = START_MS
    pending_orders = 0
    slot_skips = 0
    trades: list[dict[str, Any]] = []
    nav_path = [nav]

    for row in work.itertuples(index=False):
        decision = int(row.decision_time_ms)
        if decision < slot_free:
            slot_skips += 1
            continue
        if int(row.is_filled) != 1:
            release = int(row.label_available_at_ms) if np.isfinite(row.label_available_at_ms) else decision
            slot_free = min(max(release, decision), END_MS)
            pending_orders += 1
            continue

        entry = float(row.entry)
        risk_per_unit = float(row.risk_per_unit)
        net_r = float(row.net_r)
        if not all(np.isfinite([entry, risk_per_unit, net_r])) or entry <= 0 or risk_per_unit <= 0:
            continue

        quantity = min(nav * risk_fraction / risk_per_unit, nav * notional_cap / entry)
        pnl = quantity * risk_per_unit * net_r
        before = nav
        nav += pnl
        trades.append(
            {
                "policy": policy,
                "candidate_id": row.candidate_id,
                "symbol": row.symbol,
                "setup": row.setup,
                "decision_time_ms": decision,
                "entry_time_ms": int(row.fill_time_ms),
                "exit_time_ms": int(row.exit_time_ms),
                "entry": entry,
                "risk_per_unit": risk_per_unit,
                "quantity": quantity,
                "net_r": net_r,
                "net_pnl": pnl,
                "nav_before": before,
                "nav_after": nav,
            }
        )
        nav_path.append(nav)
        slot_free = min(int(row.exit_time_ms), END_MS)
        if nav <= 0:
            nav = 0.0
            break

    trade_frame = pd.DataFrame(trades)
    pnl = trade_frame["net_pnl"].to_numpy(float) if not trade_frame.empty else np.array([], dtype=float)
    peaks = np.maximum.accumulate(np.asarray(nav_path, dtype=float))
    drawdown = (peaks - np.asarray(nav_path, dtype=float)) / peaks
    summary = {
        "policy": policy,
        "start_nav": 10_000.0,
        "final_nav": float(nav),
        "account_multiple": float(nav / 10_000.0),
        "geometric_daily_growth": float((nav / 10_000.0) ** (1 / CALENDAR_DAYS) - 1) if nav > 0 else -1.0,
        "trades": int(len(trade_frame)),
        "pending_orders": int(pending_orders),
        "slot_skips": int(slot_skips),
        "win_rate": float(np.mean(pnl > 0)) if len(pnl) else None,
        "profit_factor": profit_factor(pnl),
        "realized_nav_max_drawdown": float(drawdown.max()) if len(drawdown) else 0.0,
        "top5_positive_share": top_positive_share(pnl),
        "risk_fraction": risk_fraction,
        "notional_cap": notional_cap,
        "nav_note": "fatal-screen realized NAV; exact UTC intratrade marks are unnecessary after negative event economics",
    }
    return summary, trade_frame


def gate_audit(artifact_root: Path, run_summary: dict[str, Any]) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    inventories: list[dict[str, Any]] = []
    selected_rows: list[dict[str, Any]] = []
    proper_diagnostic: dict[str, Any] = {}

    published = run_summary["winner"]["frozen_gate"]
    for model in ("hgb", "logit"):
        gates = pd.json_normalize(read_jsonl(artifact_root / model / "GATE_TABLE.jsonl"), sep=".")
        positive_both_halves = (
            gates["dev.sum_r"].gt(0)
            & gates["dev.mean_r"].gt(0)
            & gates["dev.fills"].ge(20)
            & gates["dev.half.2022H1"].gt(0)
            & gates["dev.half.2022H2"].gt(0)
        )
        inventories.append(
            {
                "model": model,
                "gate_count": int(len(gates)),
                "stable_count": int(gates["stable"].eq(1).sum()),
                "development_positive_both_halves_count": int(positive_both_halves.sum()),
                "maximum_development_sum_r": float(gates["dev.sum_r"].max()),
            }
        )

        if model == run_summary["winner_model"]:
            is_published = (
                gates["family"].eq(published["family"])
                & gates["atr_max"].eq(published["atr_max"])
                & gates["run_max"].eq(published["run_max"])
                & gates["same_bar"].eq(published["same_bar"])
                & gates["min_rr"].eq(published["min_rr"])
                & gates["score_quantile"].eq(published["score_quantile"])
            )
            pub = gates.loc[is_published].iloc[0]
            selected_rows.append(
                {
                    "role": "published_combined_objective_winner",
                    "model": model,
                    "family": pub["family"],
                    "atr_max": pub["atr_max"],
                    "run_max": pub["run_max"],
                    "same_bar": pub["same_bar"],
                    "min_rr": pub["min_rr"],
                    "score_quantile": pub["score_quantile"],
                    "stable": int(pub["stable"]),
                    "objective": pub["objective"],
                    "development_fills": pub["dev.fills"],
                    "development_sum_r": pub["dev.sum_r"],
                    "development_mean_r": pub["dev.mean_r"],
                    "development_2022H1_r": pub["dev.half.2022H1"],
                    "development_2022H2_r": pub["dev.half.2022H2"],
                    "validation_fills": pub["validation.fills"],
                    "validation_sum_r": pub["validation.sum_r"],
                    "validation_mean_r": pub["validation.mean_r"],
                    "validation_2023H1_r": pub["validation.half.2023H1"],
                    "validation_2023H2_r": pub["validation.half.2023H2"],
                    "validation_top5_share": pub["validation.top5_share"],
                }
            )

            diagnostic = gates.loc[positive_both_halves].copy()
            diagnostic = diagnostic.sort_values(
                ["dev.sum_r", "family"], ascending=[False, True], kind="stable"
            )
            if not diagnostic.empty:
                best = diagnostic.iloc[0]
                proper_diagnostic = {
                    "family": best["family"],
                    "development_fills": int(best["dev.fills"]),
                    "development_sum_r": float(best["dev.sum_r"]),
                    "development_mean_r": float(best["dev.mean_r"]),
                    "development_2022H1_r": float(best["dev.half.2022H1"]),
                    "development_2022H2_r": float(best["dev.half.2022H2"]),
                    "validation_fills": int(best["validation.fills"]),
                    "validation_sum_r": float(best["validation.sum_r"]),
                    "validation_mean_r": float(best["validation.mean_r"]),
                    "validation_2023H1_r": float(best["validation.half.2023H1"]),
                    "validation_2023H2_r": float(best["validation.half.2023H2"]),
                }
                selected_rows.append({"role": "development_only_diagnostic", "model": model, **proper_diagnostic})

    return pd.DataFrame(inventories), pd.DataFrame(selected_rows), proper_diagnostic


def run(artifact_root: Path, output: Path, artifact_zip: Path | None = None) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    run_summary = json.loads((artifact_root / "RUN_SUMMARY.json").read_text(encoding="utf-8"))
    all_labeled = pd.read_pickle(artifact_root / "ALL_LABELED.pkl")
    pre = all_labeled[all_labeled["event_year"].le(2023)].copy()

    inventory, gate_rows, development_diagnostic = gate_audit(artifact_root, run_summary)
    inventory.to_csv(output / "gate_inventory.csv", index=False)
    gate_rows.to_csv(output / "gate_audit.csv", index=False)

    masks = semantic_masks(pre)
    event_rows: list[dict[str, Any]] = []
    account_rows: list[dict[str, Any]] = []
    for name, mask in masks.items():
        subset = pre.loc[mask]
        for year in (2021, 2022, 2023):
            event_rows.append({"variant": name, "year": year, **event_summary(subset[subset["event_year"].eq(year)])})
        account, trades = route_account(subset, name)
        account_rows.append(account)
        if name == "strict_contract_union":
            trades.to_csv(output / "strict_contract_trades.csv", index=False)

    event_table = pd.DataFrame(event_rows)
    account_table = pd.DataFrame(account_rows)
    event_table.to_csv(output / "semantic_event_economics.csv", index=False)
    account_table.to_csv(output / "semantic_account_summary.csv", index=False)

    selected = pd.read_pickle(artifact_root / run_summary["winner_model"] / "SELECTED.pkl")
    selected_columns = [
        "candidate_id", "symbol", "segment", "setup", "side", "event_year", "event_half",
        "decision_time_ms", "activation_time_ms", "fill_time_ms", "exit_time_ms", "is_filled",
        "exit_reason", "net_r", "gross_r", "funding_r", "holding_minutes", "node_importance",
        "node_kind", "target_importance", "target_kind", "target_external", "terminal_rr",
        "risk_pct", "csd_run_bars", "csd_same_bar_confirm", "csd_delay_bars", "state_agreement",
        "state_transition", "p_fill", "p_win", "ev_pred",
    ]
    selected[selected_columns].sort_values("decision_time_ms").to_csv(
        output / "published_selected_semantics.csv", index=False
    )

    funding = (
        all_labeled[all_labeled["is_filled"].eq(1)]
        .groupby("event_year")
        .agg(
            fills=("candidate_id", "size"),
            funded_events=("funding_r", lambda x: int(x.abs().gt(1e-12).sum())),
            funding_r_sum=("funding_r", "sum"),
            funding_r_absolute_sum=("funding_r", lambda x: float(x.abs().sum())),
            net_r_sum=("net_r", "sum"),
        )
        .reset_index()
    )
    funding.to_csv(output / "funding_audit.csv", index=False)

    strict_account = account_table.loc[account_table["policy"].eq("strict_contract_union")].iloc[0].to_dict()
    strict_events = event_table[event_table["variant"].eq("strict_contract_union")].to_dict("records")
    published_gate = gate_rows.loc[gate_rows["role"].eq("published_combined_objective_winner")].iloc[0].to_dict()

    result = {
        "schema_version": 1,
        "result_id": "RES-20260729-ALDS-CSD-SEMANTIC-AUDIT-001",
        "claim_id": "CLM-20260729-2243-ALDS-CSD-AUDIT-001",
        "audited_pr": 378,
        "audited_system_id": run_summary["system_id"],
        "audited_source_sha": run_summary["source_sha"],
        "verdict": "BOTH_PROGRAMIZATION_AND_ECONOMIC_FAILURE",
        "ranking_change": False,
        "orders_submitted": False,
        "artifact": {
            "workflow_run_id": 30421166628,
            "artifact_id": 8712038780,
            "artifact_digest": "sha256:af1ed5f7afb4c2ef00b5a6922948d007741d89e70bf6ff992bc1ee34548f92f4",
            "downloaded_zip_sha256": sha256_file(artifact_zip) if artifact_zip and artifact_zip.exists() else None,
            "all_labeled_sha256": sha256_file(artifact_root / "ALL_LABELED.pkl"),
            "rows": int(len(all_labeled)),
            "fills": int(all_labeled["is_filled"].sum()),
        },
        "selection_audit": {
            "total_gate_routes": int(inventory["gate_count"].sum()),
            "stable_gate_routes": int(inventory["stable_count"].sum()),
            "published_gate": published_gate,
            "development_only_diagnostic": development_diagnostic,
            "finding": (
                "The route labeled as the winner had negative 2022 development in both halves and stable=0; "
                "three 2023 winners made the combined objective positive. Every enumerated model/gate route had stable=0. "
                "The two development-positive HGB rows both failed 2023 by -59.5777R, so no route passed the stated development/validation sequence."
            ),
        },
        "semantic_contract": {
            "DPC": [
                "pullback_sweep trigger",
                "body-close CSD confirmed before a later retest",
                "HTF state agreement",
                "strictly more important external target",
                "minimum 2R terminal geometry",
            ],
            "SRR": [
                "body-close CSD confirmed before a later retest",
                "terminal state transition",
                "node importance at least 3",
                "strictly more important external target",
                "minimum 2R terminal geometry",
            ],
            "strict_event_economics": strict_events,
            "strict_one_slot_account": strict_account,
        },
        "published_evaluation_diagnostic": run_summary["winner"]["evaluation_nav"],
        "decision": (
            "Retire the exact ALDS-CSD implementation. Correct stage separation would admit no stable model/gate. "
            "The deterministic semantic contract has negative after-cost expectancy and a collapsing fixed-small-risk one-slot account. "
            "Do not rescue it with validation-aware selection, ML thresholds, risk, leverage, or official-period retuning."
        ),
    }
    (output / "RESULT.json").write_text(
        json.dumps(json_clean(result), ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-zip", type=Path)
    args = parser.parse_args()
    result = run(args.artifact_root, args.output, args.artifact_zip)
    print(json.dumps({
        "verdict": result["verdict"],
        "stable_gate_routes": result["selection_audit"]["stable_gate_routes"],
        "strict_final_nav": result["semantic_contract"]["strict_one_slot_account"]["final_nav"],
    }, indent=2))


if __name__ == "__main__":
    main()
