from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sys
import zipfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT")
CANDIDATE_ID = "021fbab613517a31ad98"
SOURCE_TAR_SHA256 = "614b2029a073aaedf78675889d831d6aefc74f24e9fbd75c1be5e57bf034219f"
SNAPSHOT_ZIP_SHA256 = "fd3c20704cf4b8b1dc80023298920456d4ec7cf2dfe9986237d94ea8cbd51f4c"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_modules(source_root: Path):
    extension = source_root / "extension"
    shutil.copyfile(source_root / "dynamic_factor_residual.py", extension / "dynamic_factor_residual.py")
    sys.path.insert(0, str(extension))
    import state_exit as state  # type: ignore
    return state, state.D, state.R


def verify_sources(research: Path, snapshot_root: Path) -> dict:
    manifest_path = research / "MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    records = []
    for item in manifest["records"]:
        if (
            str(item.get("month", "")).startswith("2023-")
            and item.get("symbol") in SYMBOLS
            and item.get("dtype") in {"fundingRate", "markPriceKlines"}
        ):
            local = research / str(item["path"]).removeprefix("research_artifact/")
            observed = sha256(local)
            row = {
                "path": item["path"], "dtype": item["dtype"], "symbol": item["symbol"],
                "month": item["month"], "bytes": local.stat().st_size,
                "observed_sha256": observed, "expected_sha256": item["sha256"],
                "url": item["url"], "checksum_text": item.get("checksum_text"),
            }
            row["matches"] = observed == item["sha256"] and local.stat().st_size == item["bytes"]
            records.append(row)
    if len(records) != 96 or not all(x["matches"] for x in records):
        raise AssertionError("official funding/mark source verification failed")

    snapshot_checks = []
    self_entry = None
    for line in (snapshot_root / "FILE_MANIFEST.sha256").read_text().strip().splitlines():
        expected, rel = line.split(None, 1)
        rel = rel.strip()
        local_rel = rel.removeprefix("artifacts/cross_asset_leadlag/")
        local = snapshot_root / local_rel
        observed = sha256(local)
        row = {
            "path": rel, "local_path": local_rel, "bytes": local.stat().st_size,
            "expected_sha256": expected, "observed_sha256": observed,
            "matches": expected == observed,
        }
        if local_rel == "FILE_MANIFEST.sha256":
            self_entry = row
        else:
            snapshot_checks.append(row)
    if not all(x["matches"] for x in snapshot_checks):
        raise AssertionError("snapshot scientific file verification failed")
    return {
        "official_archive_count": len(records),
        "official_records": records,
        "official_parent_manifest_sha256": sha256(manifest_path),
        "source_tar_sha256": SOURCE_TAR_SHA256,
        "snapshot_artifact_sha256": SNAPSHOT_ZIP_SHA256,
        "snapshot_verified_files": snapshot_checks,
        "snapshot_self_manifest_note": "Self-entry is the pre-write empty-file hash; all eight scientific/result files match.",
        "snapshot_self_manifest_entry": self_entry,
    }


def load_funding(research: Path, market, bar_ms: int) -> tuple[dict[str, pd.DataFrame], dict]:
    out, source_counts = {}, {}
    for si, symbol in enumerate(SYMBOLS):
        ff, mm = [], []
        for month in range(1, 13):
            token = f"2023-{month:02d}"
            fp = research / "raw" / "fundingRate" / symbol / "none" / f"{symbol}-fundingRate-{token}.zip"
            mp = research / "raw" / "markPriceKlines" / symbol / "5m" / f"{symbol}-5m-{token}.zip"
            with zipfile.ZipFile(fp) as zf:
                ff.append(pd.read_csv(zf.open(zf.namelist()[0])))
            with zipfile.ZipFile(mp) as zf:
                mm.append(pd.read_csv(zf.open(zf.namelist()[0])))
        funding = pd.concat(ff, ignore_index=True).rename(columns={"calc_time": "time_ms", "last_funding_rate": "rate"})
        funding["time_ms"] = pd.to_numeric(funding["time_ms"], errors="raise").astype("int64")
        funding["rate"] = pd.to_numeric(funding["rate"], errors="raise").astype(float)
        funding = funding.sort_values("time_ms").drop_duplicates("time_ms", keep="last").reset_index(drop=True)
        mark = pd.concat(mm, ignore_index=True)
        mark["open_time"] = pd.to_numeric(mark["open_time"], errors="raise").astype("int64")
        mark["open"] = pd.to_numeric(mark["open"], errors="raise").astype(float)
        mark = mark[["open_time", "open"]].sort_values("open_time").drop_duplicates("open_time", keep="last")
        mt, mo = mark.open_time.to_numpy(np.int64), mark.open.to_numpy(float)
        pos = np.searchsorted(mt, funding.time_ms.to_numpy(np.int64), side="right") - 1
        if (pos < 0).any():
            raise AssertionError(f"{symbol}: no mark at funding event")
        funding["mark_price"] = mo[pos]
        funding["price_time_ms"] = mt[pos]
        funding["price_source"] = "official_mark_open"
        lag = funding.time_ms.to_numpy(np.int64) - funding.price_time_ms.to_numpy(np.int64)
        fallback = lag >= bar_ms
        if fallback.any():
            floor = (funding.loc[fallback, "time_ms"].to_numpy(np.int64) // bar_ms) * bar_ms
            mpos = np.searchsorted(market.times, floor)
            exact = (mpos < len(market.times)) & (market.times[np.minimum(mpos, len(market.times) - 1)] == floor)
            if not exact.all():
                raise AssertionError(f"{symbol}: contract fallback missing")
            contract = market.open[si, mpos]
            if not np.isfinite(contract).all():
                raise AssertionError(f"{symbol}: contract fallback nonfinite")
            funding.loc[fallback, "mark_price"] = contract
            funding.loc[fallback, "price_time_ms"] = floor
            funding.loc[fallback, "price_source"] = "official_contract_open_fallback"
        if (funding.time_ms.to_numpy(np.int64) - funding.price_time_ms.to_numpy(np.int64)).max() >= bar_ms:
            raise AssertionError(f"{symbol}: stale funding price")
        out[symbol] = funding
        source_counts[symbol] = {str(k): int(v) for k, v in funding.price_source.value_counts().items()}
    return out, source_counts


def funding_cash(frame: pd.DataFrame, entry_ms: int, exit_ms: int, side: int, qty: float) -> tuple[float, list[dict]]:
    times = frame.time_ms.to_numpy(np.int64)
    a = int(np.searchsorted(times, entry_ms, side="right"))
    b = int(np.searchsorted(times, exit_ms, side="right"))
    total, details = 0.0, []
    for row in frame.iloc[a:b].itertuples(index=False):
        cash = -side * qty * float(row.mark_price) * float(row.rate)
        total += cash
        details.append({
            "time_ms": int(row.time_ms), "rate": float(row.rate),
            "price": float(row.mark_price), "price_source": str(row.price_source), "cash": float(cash),
        })
    return total, details


def simulate(state, D, market, block, bars, sy, sides, candidate, cost_bps: float, funding_map=None) -> pd.DataFrame:
    times, op, hi, lo, qv, atr = market.times, market.open, market.high, market.low, market.quote, market.atr
    equity, peak, mdd, free = 10_000.0, 10_000.0, 0.0, -1
    rows = []
    for k in range(len(bars)):
        signal = int(bars[k])
        if signal < free:
            continue
        s, side = int(sy[k]), int(sides[k])
        entry_i, timeout_i = signal + 1, signal + 1 + candidate.maximum_hold_bars
        if timeout_i >= len(times) or times[entry_i] != times[signal] + D.BAR_MS:
            continue
        if times[timeout_i] - times[entry_i] != candidate.maximum_hold_bars * D.BAR_MS:
            continue
        entry, current_atr = float(op[s, entry_i]), float(atr[s, signal])
        if not np.isfinite(entry) or not np.isfinite(current_atr) or entry <= 0 or current_atr <= 0:
            continue
        distance = max(candidate.stop_atr * current_atr, entry * 0.0015)
        if distance > entry * 0.05:
            continue
        stop, exit_i, exit_price = entry - side * distance, timeout_i, float(op[s, timeout_i])
        stopped = state_exited = 0
        reason, valid = "timeout", True
        for bar in range(entry_i, timeout_i):
            o, h, l = float(op[s, bar]), float(hi[s, bar]), float(lo[s, bar])
            if not (np.isfinite(o) and np.isfinite(h) and np.isfinite(l)):
                valid = False; break
            if side > 0 and l <= stop:
                exit_i, exit_price, stopped, reason = bar, (o if o < stop else stop), 1, "stop"; break
            if side < 0 and h >= stop:
                exit_i, exit_price, stopped, reason = bar, (o if o > stop else stop), 1, "stop"; break
            if bar - entry_i + 1 < candidate.minimum_hold_bars:
                continue
            signed_rank = side * float(block.cs_score[s, bar])
            signed_flow = side * float(block.flow_z[s, bar])
            if candidate.exit_mode == "flow_decay":
                condition = np.isfinite(signed_flow) and signed_flow < float(candidate.signed_flow_exit_threshold)
            else:
                raise AssertionError("audit is fixed to registered flow_decay candidate")
            if condition:
                exit_i, exit_price, state_exited, reason = bar + 1, float(op[s, bar + 1]), 1, "state_exit"; break
        if not valid or not np.isfinite(exit_price):
            continue
        cost_fraction = cost_bps / 10_000.0
        planned = distance / entry + cost_fraction
        notional = min(equity * 0.005 / planned, equity * 3.0, float(qv[s, signal]) * 0.001)
        if notional <= 0 or not np.isfinite(notional):
            continue
        qty = notional / entry
        price_pnl = side * (exit_price / entry - 1.0) * notional
        cost_pnl = -cost_fraction * notional
        f_pnl, f_details = (0.0, []) if funding_map is None else funding_cash(
            funding_map[SYMBOLS[s]], int(times[entry_i]), int(times[exit_i]), side, qty
        )
        before = equity
        pnl = price_pnl + cost_pnl + f_pnl
        equity = max(1e-12, equity + pnl)
        account_return = pnl / before
        peak, mdd = max(peak, equity), max(mdd, 1 - equity / max(peak, equity))
        rows.append({
            "trade_number": len(rows) + 1, "signal_time_ms": int(times[signal]),
            "entry_time_ms": int(times[entry_i]), "exit_time_ms": int(times[exit_i]),
            "symbol": SYMBOLS[s], "side": side, "entry_price": entry, "exit_price": exit_price,
            "stop_price": stop, "duration_bars": exit_i - entry_i, "notional": notional,
            "quantity": qty, "price_pnl": price_pnl, "cost_pnl": cost_pnl, "funding_pnl": f_pnl,
            "funding_event_count": len(f_details), "funding_details_json": json.dumps(f_details, separators=(",", ":")),
            "trade_pnl": pnl, "account_return": account_return, "equity_before": before,
            "equity_after": equity, "stopped": stopped, "state_exited": state_exited,
            "exit_reason": reason, "max_drawdown_after": mdd,
        })
        free = exit_i + 1
    return pd.DataFrame(rows)


def summary(ledger: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> dict:
    ar, pnl = ledger.account_return.to_numpy(float), ledger.trade_pnl.to_numpy(float)
    pos, neg = pnl[pnl > 0], -pnl[pnl < 0]
    ordered = np.sort(ar); removed = max(1, int(math.ceil(len(ar) * 0.1)))
    dt = pd.to_datetime(ledger.exit_time_ms, unit="ms", utc=True)
    half = start + (end - start) / 2
    monthly = [float(np.prod(1 + ledger.loc[dt.dt.month == m, "account_return"]) - 1) for m in range(1, 13)]
    counts = ledger.symbol.value_counts(); ending = float(ledger.iloc[-1].equity_after)
    days = max(1.0, (end - start).total_seconds() / 86400)
    return {
        "n": int(len(ledger)), "total_return": ending / 10_000 - 1,
        "gmean_daily": math.exp(math.log(ending / 10_000) / days) - 1,
        "profit_factor": float(pos.sum() / neg.sum()), "max_drawdown": float(ledger.max_drawdown_after.max()),
        "top5_positive_share": float(np.sort(pos)[-5:].sum() / pos.sum()),
        "top10pct_removed_return": float(np.prod(1 + ordered[: len(ar) - removed]) - 1),
        "h1_return": float(np.prod(1 + ledger.loc[dt < half, "account_return"]) - 1),
        "h2_return": float(np.prod(1 + ledger.loc[dt >= half, "account_return"]) - 1),
        "positive_month_fraction": sum(x > 0 for x in monthly) / 12,
        "worst_month": min(monthly), "monthly_returns": monthly,
        "traded_symbols": int(len(counts)), "max_single_symbol_trade_share": float(counts.max() / len(ledger)),
        "symbol_counts": {str(k): int(v) for k, v in counts.items()},
        "mean_net_bps": float(ar.mean() * 10_000), "median_net_bps": float(np.median(ar) * 10_000),
        "stop_rate": float(ledger.stopped.mean()), "state_exit_rate": float(ledger.state_exited.mean()),
        "ending_equity": ending, "total_funding_pnl": float(ledger.funding_pnl.sum()),
        "funding_event_count": int(ledger.funding_event_count.sum()),
        "trades_with_funding": int((ledger.funding_event_count > 0).sum()),
    }


def registered_diffs(observed: dict, registered: dict, scenario: str) -> dict:
    if scenario == "base":
        expected = {
            "n": registered["trades"], "total_return": registered["return_12bps"],
            "gmean_daily": registered["gmean_daily"], "profit_factor": registered["profit_factor"],
            "max_drawdown": registered["max_drawdown"], "top5_positive_share": registered["top5_positive_share"],
            "top10pct_removed_return": registered["top10pct_removed_return"], "h1_return": registered["h1_return"],
            "h2_return": registered["h2_return"], "positive_month_fraction": registered["positive_month_fraction"],
            "worst_month": registered["worst_month"], "state_exit_rate": registered["state_exit_rate"],
        }
    else:
        expected = {"total_return": registered["return_18bps" if scenario == "cost18" else "return_24bps"]}
    return {k: float(observed[k] - v) for k, v in expected.items()}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source-root", type=Path, required=True)
    ap.add_argument("--snapshot-root", type=Path, required=True)
    ap.add_argument("--research-artifact", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args(); args.output.mkdir(parents=True, exist_ok=True)
    integrity = verify_sources(args.research_artifact, args.snapshot_root)
    state, D, R = load_modules(args.source_root)
    candidate = next(x for x in state.candidates() if x.candidate_id == CANDIDATE_ID)
    snapshot = args.snapshot_root / "snapshot"
    market = D.load_market(snapshot, "development")
    blocks = R.build_blocks(market); entry = state.ENTRY_RULES[candidate.entry_index]
    block = blocks[(entry.beta_window, entry.residual_horizon)]
    bars, sy, sides = R.events(block, entry, market, "development")
    funding_map, price_counts = load_funding(args.research_artifact, market, D.BAR_MS)
    registered = json.loads((args.source_root / "extension" / "state_exit_result_summary.json").read_text())["best_preregistered_rank"]
    start, end = D.PERIODS["development"]
    report = {
        "schema_version": 1, "candidate_id": CANDIDATE_ID, "candidate": asdict(candidate),
        "integrity": integrity, "registered": registered, "raw_event_count": int(len(bars)),
        "funding_rule": "official fundingRate at calc_time in (entry, exit]; -side*quantity*exact mark open*rate; exact contract-open fallback only when official mark archive lacks the settlement bar",
        "price_source_counts": price_counts, "scenarios": {},
    }
    for cost, key in ((12.0, "base"), (18.0, "cost18"), (24.0, "cost24")):
        nofund = simulate(state, D, market, block, bars, sy, sides, candidate, cost, None)
        funded = simulate(state, D, market, block, bars, sy, sides, candidate, cost, funding_map)
        nsum, fsum = summary(nofund, start, end), summary(funded, start, end)
        diffs = registered_diffs(nsum, registered, key)
        report["scenarios"][key] = {
            "cost_bps": cost, "no_funding": nsum, "with_actual_funding": fsum,
            "no_funding_vs_registered_differences": diffs,
            "max_abs_reproduction_difference": max(abs(v) for v in diffs.values()),
            "funding_effect_on_total_return": fsum["total_return"] - nsum["total_return"],
            "funding_effect_on_gmean_daily": fsum["gmean_daily"] - nsum["gmean_daily"],
        }
        funded.to_csv(args.output / f"ledger_cost{int(cost)}_actual_funding.csv", index=False)
    (args.output / "funding_audit_report.json").write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    files = []
    for path in sorted(args.output.iterdir()):
        if path.is_file() and path.name != "SHA256SUMS.json":
            files.append({"path": path.name, "bytes": path.stat().st_size, "sha256": sha256(path)})
    (args.output / "SHA256SUMS.json").write_text(json.dumps({"schema_version": 1, "files": files}, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: v["with_actual_funding"] for k, v in report["scenarios"].items()}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
