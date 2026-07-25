from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

AGES_MS = (50, 100, 200, 500, 1_000, 2_000)
TOLERANCES_BP = (0.0, 0.05, 0.10, 0.25, 0.50, 1.0, 2.0)


def load_module(path: Path):
    spec = importlib.util.spec_from_file_location("l2_maker_source", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load source module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build_dual_clock_book(module, depth_path: Path) -> pd.DataFrame:
    depth = pd.read_parquet(depth_path, columns=["E", "T", "bids", "asks"])
    bid, bid_qty = module.parse_top_levels(depth["bids"])
    ask, ask_qty = module.parse_top_levels(depth["asks"])
    book = pd.DataFrame(
        {
            "event_time": module.normalize_epoch_ms(depth["E"]),
            "transaction_time": module.normalize_epoch_ms(depth["T"]),
            "bid": bid,
            "bid_qty": bid_qty,
            "ask": ask,
            "ask_qty": ask_qty,
        }
    )
    book = book.dropna().copy()
    for col in ("event_time", "transaction_time"):
        book[col] = book[col].astype(np.int64)
    book = book[
        (book["bid"] > 0)
        & (book["ask"] > book["bid"])
        & (book["bid_qty"] > 0)
        & (book["ask_qty"] > 0)
    ].copy()
    return book.reset_index(drop=True)


def violation_bp(trades: pd.DataFrame, book: pd.DataFrame, indices: np.ndarray) -> np.ndarray:
    safe = np.clip(indices, 0, len(book) - 1)
    price = trades["price"].to_numpy(dtype=float)
    bid = book["bid"].to_numpy(dtype=float)[safe]
    ask = book["ask"].to_numpy(dtype=float)[safe]
    buyer_maker = trades["buyer_maker"].to_numpy(dtype=bool)
    scale = np.maximum(price, 1e-12)
    sell = np.maximum(price - bid, 0.0) / scale * 1e4
    buy = np.maximum(ask - price, 0.0) / scale * 1e4
    return np.where(buyer_maker, sell, buy)


def clock_metrics(book: pd.DataFrame, trades: pd.DataFrame, clock: str) -> dict[str, Any]:
    ordered = book.sort_values(clock).drop_duplicates(clock, keep="last").reset_index(drop=True)
    bt = ordered[clock].to_numpy(dtype=np.int64)
    tt = trades["time"].to_numpy(dtype=np.int64)
    support_mask = (tt >= bt[0]) & (tt <= bt[-1])
    support = trades.loc[support_mask].reset_index(drop=True)
    st = support["time"].to_numpy(dtype=np.int64)
    prior = np.searchsorted(bt, st, side="right") - 1
    safe_prior = np.clip(prior, 0, len(ordered) - 1)
    age = st - bt[safe_prior]
    violation = violation_bp(support, ordered, prior)

    metrics: dict[str, Any] = {
        "clock": clock,
        "book_updates": int(len(ordered)),
        "support_start_ms": int(bt[0]),
        "support_end_ms": int(bt[-1]),
        "support_duration_hours": float((bt[-1] - bt[0]) / 3_600_000),
        "all_trade_count": int(len(trades)),
        "support_trade_count": int(len(support)),
        "support_fraction_of_day_trades": float(len(support) / max(len(trades), 1)),
        "negative_prior_age_count": int(np.sum(age < 0)),
        "depth_gap_p50_ms": float(np.quantile(np.diff(bt), 0.50)) if len(bt) > 1 else None,
        "depth_gap_p95_ms": float(np.quantile(np.diff(bt), 0.95)) if len(bt) > 1 else None,
        "depth_gap_p99_ms": float(np.quantile(np.diff(bt), 0.99)) if len(bt) > 1 else None,
        "depth_gap_max_ms": int(np.max(np.diff(bt))) if len(bt) > 1 else None,
    }
    for age_limit in AGES_MS:
        mask = (prior >= 0) & (age >= 0) & (age <= age_limit)
        prefix = f"prior_{age_limit}ms"
        count = int(mask.sum())
        metrics[f"{prefix}_count"] = count
        metrics[f"{prefix}_coverage_support"] = float(count / max(len(support), 1))
        metrics[f"{prefix}_age_p99_ms"] = float(np.quantile(age[mask], 0.99)) if count else None
        for tol in TOLERANCES_BP:
            label = str(tol).replace(".", "p")
            metrics[f"{prefix}_compatible_le_{label}bp"] = float((violation[mask] <= tol + 1e-12).mean()) if count else 0.0
        if count:
            for q in (0.50, 0.90, 0.95, 0.99, 0.999):
                label = str(q).replace(".", "p")
                metrics[f"{prefix}_violation_q{label}_bp"] = float(np.quantile(violation[mask], q))
            metrics[f"{prefix}_violation_max_bp"] = float(np.max(violation[mask]))

    # Non-causal diagnostic only: quantify whether a following depth event resolves
    # apparent impossible prints. These fields never enter a strategy or gate.
    next_idx = np.searchsorted(bt, st, side="left")
    valid_next = next_idx < len(bt)
    safe_next = np.clip(next_idx, 0, len(bt) - 1)
    lead = bt[safe_next] - st
    next_violation = violation_bp(support, ordered, safe_next)
    for lead_limit in (25, 50, 100, 200):
        mask = valid_next & (lead >= 0) & (lead <= lead_limit)
        prefix = f"diagnostic_next_{lead_limit}ms"
        metrics[f"{prefix}_coverage_support"] = float(mask.sum() / max(len(support), 1))
        metrics[f"{prefix}_strict_compatibility"] = float((next_violation[mask] <= 1e-12).mean()) if mask.any() else 0.0

    return metrics


def process(module, symbol: str, date: str, cache: Path) -> dict[str, Any]:
    depth_path = Path(
        module.hf_hub_download(
            repo_id=module.HF_REPO,
            repo_type="dataset",
            revision=module.HF_REVISION,
            filename=f"{symbol}/{date}_{symbol}_depth20.parquet",
            cache_dir=str(cache / "hf"),
        )
    )
    raw = cache / "binance"
    source = module.download_binance_verified(symbol, date, "aggTrades", raw)
    trades_path = raw / "aggTrades" / symbol / f"{symbol}-aggTrades-{date}.zip"
    trades = module.read_aggtrades(trades_path)
    book = build_dual_clock_book(module, depth_path)
    return {
        "symbol": symbol,
        "date": date,
        "depth_sha256": module.sha256_file(depth_path),
        "official_aggtrades_sha256": source.sha256,
        "transaction_clock": clock_metrics(book, trades, "transaction_time"),
        "event_clock": clock_metrics(book, trades, "event_time"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cache", type=Path, required=True)
    parser.add_argument("--symbols", nargs="+", default=["BTCUSDT", "ETHUSDT"])
    parser.add_argument("--dates", nargs="+", default=["2026-03-05", "2026-03-09", "2026-03-13", "2026-03-16"])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    module = load_module(args.source)
    rows = []
    failures = []
    for date in args.dates:
        for symbol in args.symbols:
            print(f"AUDIT {symbol} {date}", flush=True)
            try:
                rows.append(process(module, symbol, date, args.cache))
            except Exception as exc:
                failures.append({"symbol": symbol, "date": date, "error": repr(exc)})
    payload = {
        "study": "L2_DEPTH_OFFICIAL_TRADE_ALIGNMENT_AUDIT_V1",
        "strategy_outcomes_opened": False,
        "orders_simulated": False,
        "rows": rows,
        "failures": failures,
    }
    (args.output / "alignment_audit.json").write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    flat = []
    for row in rows:
        base = {"symbol": row["symbol"], "date": row["date"], "depth_sha256": row["depth_sha256"], "official_aggtrades_sha256": row["official_aggtrades_sha256"]}
        for clock_name in ("transaction_clock", "event_clock"):
            flat.append({**base, **row[clock_name]})
    pd.DataFrame(flat).to_csv(args.output / "alignment_audit.csv", index=False)
    print(json.dumps({"rows": len(rows), "failures": len(failures)}, sort_keys=True))
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
