#!/usr/bin/env python3
"""V5 programization authority for issue #581.

Corrections relative to the quarantined V4 evaluator:
- post-entry execution fields and the future fill price are never model features;
- high/low range trees are built once per symbol rather than once per action;
- a completed state-loss exit at a minute open precedes later intraminute
  target/stop touches; only a stop gap already present at that open overrides it.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_dense_edge_v4 as b  # noqa: E402


class CachedRangeTree:
    _cache: dict[tuple[int, str], "CachedRangeTree"] = {}

    def __new__(cls, values: np.ndarray, mode: str):
        key = (id(values), mode)
        if key in cls._cache:
            return cls._cache[key]
        obj = super().__new__(cls)
        cls._cache[key] = obj
        obj._ready = False
        return obj

    def __init__(self, values: np.ndarray, mode: str):
        if self._ready:
            return
        original = _ORIGINAL_RANGE_TREE(values, mode)
        self.n, self.mode, self.tree = original.n, original.mode, original.tree
        self._ready = True

    def first(self, left: int, threshold: float, relation: str) -> int:
        neutral_fail = (lambda v: v < threshold) if relation == "ge" else (lambda v: v > threshold)
        def rec(node: int, lo: int, hi: int) -> int:
            if hi <= left or neutral_fail(self.tree[node]):
                return -1
            if hi - lo == 1:
                return lo
            mid = (lo + hi) // 2
            x = rec(node * 2, lo, mid)
            return x if x >= 0 else rec(node * 2 + 1, mid, hi)
        return rec(1, 0, self.n)


_ORIGINAL_RANGE_TREE = b.RangeTree
b.RangeTree = CachedRangeTree


def resolve_action(event: pd.Series, action: str, sd: b.SymbolData, pools: pd.DataFrame) -> dict | None:
    entry_ts = pd.Timestamp(event["entry_ts"])
    decision = pd.Timestamp(event["decision_ts"])
    entry = float(event["entry_price"])
    level_side = int(event["level_side"])
    level = float(event["level"])
    atr = float(event["atr15m20"])
    if not np.isfinite(entry) or not np.isfinite(atr) or atr <= 0:
        return None
    if action == "CONTINUE":
        direction = level_side
        target = b.choose_target(pools, direction, level, decision, entry_ts)
        stop = level - direction * 0.25 * atr
        state_level = level
        relation = "lt" if direction > 0 else "gt"
    else:
        direction = -level_side
        target = float(event["prior_day_mid"])
        extreme = float(event["sensor_high"] if level_side > 0 else event["sensor_low"])
        stop = extreme + level_side * 0.25 * atr
        state_level = extreme
        relation = "gt" if level_side > 0 else "lt"
    if not np.isfinite(target) or direction * (target - entry) <= 0 or direction * (entry - stop) <= 0:
        return None

    ph = float(event["post_entry_minute_high"])
    pl = float(event["post_entry_minute_low"])
    stop_touch = pl <= stop if direction > 0 else ph >= stop
    target_touch = ph >= target if direction > 0 else pl <= target
    exit_ts = pd.NaT
    exit_px = math.nan
    reason = "UNRESOLVED"
    if stop_touch:
        exit_ts = pd.Timestamp(event["post_entry_minute_last_ts"])
        exit_px, reason = stop, "STOP"
    elif target_touch:
        exit_ts = pd.Timestamp(event["post_entry_minute_last_ts"])
        exit_px, reason = target, "TARGET"
    else:
        start_min = entry_ts.floor("min") + pd.Timedelta(minutes=1)
        start = int(np.searchsorted(sd.minute_ns, start_min.value, side="left"))
        if start < len(sd.price):
            hi_tree = CachedRangeTree(sd.high, "max")
            lo_tree = CachedRangeTree(sd.low, "min")
            stop_i = lo_tree.first(start, stop, "le") if direction > 0 else hi_tree.first(start, stop, "ge")
            target_i = hi_tree.first(start, target, "ge") if direction > 0 else lo_tree.first(start, target, "le")
            state_i = b.first_state_index(sd, entry_ts, state_level, relation)
            valid = [i for i in (stop_i, target_i, state_i) if 0 <= i < len(sd.price)]
            if valid:
                i0 = min(valid)
                o = float(sd.open_[i0])
                # A state exit is executable at this minute's open and therefore
                # precedes later high/low touches in the same minute.
                if state_i == i0:
                    exit_ts = pd.Timestamp(sd.price.iloc[i0]["ts"])
                    if (direction > 0 and o <= stop) or (direction < 0 and o >= stop):
                        exit_px, reason = o, "STOP_GAP"
                    else:
                        exit_px, reason = o, "STATE"
                elif stop_i == i0:
                    exit_ts = pd.Timestamp(sd.price.iloc[i0]["ts"])
                    exit_px = o if ((direction > 0 and o <= stop) or (direction < 0 and o >= stop)) else stop
                    reason = "STOP"
                else:
                    exit_ts = pd.Timestamp(sd.price.iloc[i0]["ts"])
                    exit_px, reason = target, "TARGET"

    result = {
        "event_id": event["event_id"], "symbol": event["symbol"], "action": action,
        "direction": direction, "decision_ts": decision, "entry_ts": entry_ts,
        "entry": entry, "stop": stop, "target": target,
        "exit_ts": exit_ts, "exit": exit_px, "exit_reason": reason,
    }
    if pd.notna(exit_ts):
        fsum = b.funding_sum(sd, entry_ts, exit_ts)
        gross = direction * (exit_px / entry - 1.0)
        result["funding_sum"] = fsum
        for bp in b.COSTS_BP:
            c = bp / 10000.0
            lev = min(b.CAP, b.RISK / max(abs(entry - stop) / entry + c, 1e-12))
            result[f"leverage_{int(bp)}"] = lev
            result[f"notional_ret_{int(bp)}"] = gross - c - direction * fsum
            result[f"account_ret_{int(bp)}"] = lev * result[f"notional_ret_{int(bp)}"]
    else:
        result["funding_sum"] = math.nan
        for bp in b.COSTS_BP:
            result[f"leverage_{int(bp)}"] = min(b.CAP, b.RISK / max(abs(entry - stop) / entry + bp / 10000.0, 1e-12))
            result[f"notional_ret_{int(bp)}"] = math.nan
            result[f"account_ret_{int(bp)}"] = math.nan
    return result


def sha(path: Path) -> str:
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--features", type=Path, required=True)
    ap.add_argument("--canonical", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    events = pd.read_csv(args.features)
    for c in ["event_ts", "decision_ts", "entry_ts", "post_entry_minute_last_ts"]:
        events[c] = pd.to_datetime(events[c], utc=True)
    symbol_data = {s: b.load_symbol(args.canonical, s) for s in ["BTCUSDT", "ETHUSDT"]}
    pools = {s: b.pool_consumed(symbol_data[s]) for s in symbol_data}

    enriched = []
    for _, e in events.iterrows():
        sd = symbol_data[str(e["symbol"])]
        peer = symbol_data["ETHUSDT" if e["symbol"] == "BTCUSDT" else "BTCUSDT"]
        enriched.append({**e.to_dict(), **b.canonical_features(sd, peer, pd.Timestamp(e["decision_ts"])), "is_eth": float(e["symbol"] == "ETHUSDT")})
    events = pd.DataFrame(enriched)

    action_rows = []
    for _, e in events.iterrows():
        for action in ["CONTINUE", "REJECT"]:
            r = resolve_action(e, action, symbol_data[str(e["symbol"])], pools[str(e["symbol"])])
            if r is not None:
                r.update(e.to_dict())
                r["action"] = action
                r["direction"] = int(level_direction := (int(e["level_side"]) if action == "CONTINUE" else -int(e["level_side"])))
                r["is_continue"] = float(action == "CONTINUE")
                action_rows.append(r)
    actions = pd.DataFrame(action_rows)
    if actions.empty:
        raise RuntimeError("no valid action rows")
    for c in ["decision_ts", "entry_ts", "exit_ts"]:
        actions[c] = pd.to_datetime(actions[c], utc=True)

    forbidden_exact = {
        "event_id", "symbol", "event_day", "event_ts", "sensor_end_ts", "decision_ts", "activation_ts", "entry_ts",
        "post_entry_minute_last_ts", "action", "exit_ts", "exit_reason", "model_tag", "prediction",
        "entry", "entry_price", "exit", "stop", "target", "funding_sum",
    }
    feature_cols = []
    for c in actions.columns:
        if c in forbidden_exact or c.startswith(("account_ret_", "notional_ret_", "leverage_", "post_entry_minute_")):
            continue
        if pd.api.types.is_numeric_dtype(actions[c]):
            feature_cols.append(c)
    prohibited = [c for c in feature_cols if c.startswith("post_entry") or c in {"entry_price", "exit", "target", "stop", "funding_sum"}]
    if prohibited:
        raise RuntimeError(f"future/execution fields in features: {prohibited}")

    raw = {}
    for action in ["CONTINUE", "REJECT"]:
        z = actions[actions["action"] == action].copy()
        z["prediction"] = 1.0
        led, marks = b.route(z, symbol_data, 24.0)
        raw[action] = {
            "may_aug": b.metrics(led, marks, 24.0, b.FIT_END, b.REFIT_END),
            "sep_dec": b.metrics(led, marks, 24.0, b.REFIT_END, b.END),
        }

    model1 = b.fit_model(actions, feature_cols, b.FIT_END)
    stage1 = b.score_stage(actions, model1, feature_cols, b.FIT_END, b.REFIT_END, "FIT_JAN_APR")
    model2 = b.fit_model(actions, feature_cols, b.REFIT_END)
    stage2 = b.score_stage(actions, model2, feature_cols, b.REFIT_END, b.END, "REFIT_THROUGH_AUG")
    selected = pd.concat([stage1, stage2], ignore_index=True).sort_values(["entry_ts", "prediction"], ascending=[True, False])

    result = {
        "result_id": "RES-20260730-DENSE-LIQUIDITY-EDGE-MICROFLOW-001",
        "status": "PENDING_DECISION",
        "programization_version": "V5_POST_ENTRY_EXACT_STATE_OPEN_PRIORITY",
        "source_events": int(len(events)), "action_rows": int(len(actions)),
        "resolved_before_may": int(np.sum(pd.notna(actions["exit_ts"]) & (actions["exit_ts"] < b.FIT_END))),
        "resolved_before_sep": int(np.sum(pd.notna(actions["exit_ts"]) & (actions["exit_ts"] < b.REFIT_END))),
        "selected_stage1": int(len(stage1)), "selected_stage2": int(len(stage2)),
        "feature_columns": feature_cols, "raw_24bp": raw, "costs": {},
    }
    ledgers = {}
    for bp in b.COSTS_BP:
        ledger, marks = b.route(selected, symbol_data, bp)
        ledgers[bp] = ledger
        pos = ledger[pd.notna(ledger["exit_ts"]) & (ledger[f"account_ret_{int(bp)}"] > 0)]
        k = max(1, int(math.ceil(0.10 * len(pos)))) if len(pos) else 0
        removed = set(pos.nlargest(k, f"account_ret_{int(bp)}")["event_id"]) if k else set()
        wr_ledger, wr_marks = b.route(selected, symbol_data, bp, removed)
        result["costs"][str(int(bp))] = {
            "may_jun": b.metrics(ledger, marks, bp, b.FIT_END, pd.Timestamp("2023-07-01T00:00Z")),
            "jul_aug": b.metrics(ledger, marks, bp, pd.Timestamp("2023-07-01T00:00Z"), b.REFIT_END),
            "may_aug": b.metrics(ledger, marks, bp, b.FIT_END, b.REFIT_END),
            "sep_oct": b.metrics(ledger, marks, bp, b.REFIT_END, pd.Timestamp("2023-11-01T00:00Z")),
            "nov_dec": b.metrics(ledger, marks, bp, pd.Timestamp("2023-11-01T00:00Z"), b.END),
            "sep_dec": b.metrics(ledger, marks, bp, b.REFIT_END, b.END),
            "continuous_may_dec": b.metrics(ledger, marks, bp, b.FIT_END, b.END),
            "winner_removed_may_aug": b.metrics(wr_ledger, wr_marks, bp, b.FIT_END, b.REFIT_END),
            "winner_removed_sep_dec": b.metrics(wr_ledger, wr_marks, bp, b.REFIT_END, b.END),
            "removed_event_count": int(len(removed)),
        }

    g = result["costs"]["24"]
    def eligible(name: str, first_half: str, second_half: str, wr: str) -> bool:
        m = g[name]
        return bool(
            m["entries"] >= 60 and m["multiple"] > 1 and m["pf"] > 1 and m["median"] >= 0
            and g[first_half]["multiple"] > 1 and g[second_half]["multiple"] > 1 and g[wr]["multiple"] > 1
        )
    passed = eligible("may_aug", "may_jun", "jul_aug", "winner_removed_may_aug") and eligible("sep_dec", "sep_oct", "nov_dec", "winner_removed_sep_dec")
    result["gate_pass"] = passed
    result["status"] = "PRE2024_GATE_PASS_OFFICIAL_AUTHORIZED" if passed else "RETIRED_PRE2024_NEGATIVE_SPARSE_UNSTABLE_OR_WINNER_DEPENDENT"
    result["official_2024_2026_opened"] = False

    actions.to_csv(args.out / "actions.csv.gz", index=False, compression="gzip")
    selected.to_csv(args.out / "selected_candidates.csv.gz", index=False, compression="gzip")
    ledgers[24.0].to_csv(args.out / "ledger_24bp.csv.gz", index=False, compression="gzip")
    (args.out / "RESULT.json").write_text(json.dumps(b.clean_json(result), indent=2, sort_keys=True), encoding="utf-8")
    report = [
        "# Dense official-Bybit liquidity-edge microflow", "",
        f"Status: `{result['status']}`", f"Programization: `{result['programization_version']}`",
        f"Source events: {len(events):,}", f"Action rows: {len(actions):,}",
        f"Selected May-Aug: {len(stage1):,}", f"Selected Sep-Dec: {len(stage2):,}",
        "", "## 24 bp forward partitions", "",
    ]
    for name in ["may_jun", "jul_aug", "may_aug", "sep_oct", "nov_dec", "sep_dec", "continuous_may_dec", "winner_removed_may_aug", "winner_removed_sep_dec"]:
        report.append(f"- {name}: `{json.dumps(b.clean_json(g[name]), sort_keys=True)}`")
    report += ["", "Raw actions and all 12/18/24-bp paths are in RESULT.json. Official 2024-2026 and risk/leverage research remain closed unless the frozen gate passes."]
    (args.out / "REPORT.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    manifest = {p.name: sha(p) for p in sorted(args.out.iterdir()) if p.is_file()}
    (args.out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": result["status"], "events": len(events), "actions": len(actions)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
