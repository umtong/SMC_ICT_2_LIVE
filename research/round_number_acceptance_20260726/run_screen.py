from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
import os
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd
import requests

CLAIM_ID = "CLM-20260726-0535-ROUND-NUMBER-001"
RESULT_ID = "RES-20260726-ROUND-NUMBER-FATAL-001"
SYMBOLS = ("BTCUSDT", "ETHUSDT")
FIT_DATES = ("2023-01-15", "2023-03-19", "2023-05-21")
DEVELOPMENT_DATES = ("2023-07-16", "2023-09-17", "2023-11-19")
ALL_DATES = FIT_DATES + DEVELOPMENT_DATES
BASE_URL = "https://public.bybit.com/trading"
GRID_MULTIPLIERS = (0.5, 1.0, 2.0)
CONFIRM_SECONDS = (1.0, 3.0, 10.0)
CLOSE_FRACTIONS = (0.005, 0.02)
FLOW_THRESHOLDS = (0.0, 0.3)
THROUGH_THRESHOLDS = (0.6, 0.7)
HORIZONS_SECONDS = (120, 300, 900, 1800)
COSTS_BPS = (12.0, 18.0, 24.0)
COOLDOWN_SECONDS = 30.0
ENTRY_LATENCY_SECONDS = 0.1
MIN_CONFIRM_TRADES = 5
EXPECTED_CANDIDATES = (
    len(GRID_MULTIPLIERS)
    * len(CONFIRM_SECONDS)
    * 2
    * len(CLOSE_FRACTIONS)
    * len(FLOW_THRESHOLDS)
    * len(THROUGH_THRESHOLDS)
    * len(HORIZONS_SECONDS)
)


class ContractError(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def stable_id(payload: dict[str, Any]) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(raw).hexdigest()[:20]


def finite(value: Any) -> Any:
    if isinstance(value, (np.integer, int)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        value = float(value)
        return value if math.isfinite(value) else None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    return value


def download_archive(symbol: str, date: str, cache: Path) -> tuple[Path, dict[str, Any]]:
    cache.mkdir(parents=True, exist_ok=True)
    filename = f"{symbol}{date}.csv.gz"
    path = cache / symbol / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{BASE_URL}/{symbol}/{filename}"
    if not path.is_file() or path.stat().st_size == 0:
        temporary = path.with_suffix(path.suffix + ".part")
        if temporary.exists():
            temporary.unlink()
        last_error: Exception | None = None
        for attempt in range(1, 5):
            try:
                with requests.get(url, stream=True, timeout=(20, 180)) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as handle:
                        for block in response.iter_content(chunk_size=1 << 20):
                            if block:
                                handle.write(block)
                os.replace(temporary, path)
                break
            except Exception as exc:
                last_error = exc
                if temporary.exists():
                    temporary.unlink()
                if attempt == 4:
                    raise ContractError(f"download failed for {url}: {exc}") from exc
                time.sleep(attempt * 2)
        if not path.exists() and last_error is not None:
            raise ContractError(str(last_error))
    digest = sha256_file(path)
    try:
        with gzip.open(path, "rt", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            rows = sum(1 for _ in reader)
    except Exception as exc:
        raise ContractError(f"gzip/CSV integrity failed for {path}: {exc}") from exc
    required = {"timestamp", "symbol", "side", "size", "price"}
    if not required.issubset(set(header)):
        raise ContractError(f"missing required fields in {path}: {header}")
    if rows <= 0:
        raise ContractError(f"empty archive: {path}")
    return path, {
        "symbol": symbol,
        "date": date,
        "url": url,
        "sha256": digest,
        "compressed_bytes": path.stat().st_size,
        "rows": rows,
        "header": header,
    }


def load_trades(path: Path, expected_symbol: str) -> pd.DataFrame:
    frame = pd.read_csv(
        path,
        compression="gzip",
        usecols=["timestamp", "symbol", "side", "size", "price"],
        dtype={"timestamp": "float64", "symbol": "string", "side": "string", "size": "float64", "price": "float64"},
    )
    if frame.empty:
        raise ContractError(f"no trades in {path}")
    if frame[["timestamp", "size", "price"]].isna().any().any():
        raise ContractError(f"non-finite core field in {path}")
    if not (frame["symbol"] == expected_symbol).all():
        raise ContractError(f"unexpected symbol in {path}")
    if not frame["side"].isin(["Buy", "Sell"]).all():
        raise ContractError(f"unexpected side in {path}")
    if (frame["size"] <= 0).any() or (frame["price"] <= 0).any():
        raise ContractError(f"non-positive trade field in {path}")
    timestamps = frame["timestamp"].to_numpy(dtype=np.float64)
    if np.any(np.diff(timestamps) < 0):
        raise ContractError(f"timestamps not nondecreasing in {path}")
    return frame


def adaptive_base_step(first_price: float) -> float:
    if not math.isfinite(first_price) or first_price <= 0:
        raise ContractError("invalid first price")
    return float(10 ** (math.floor(math.log10(first_price)) - 2))


def crossed_levels(previous_bin: int, current_bin: int) -> Iterable[tuple[int, int]]:
    if current_bin > previous_bin:
        for level_index in range(previous_bin + 1, current_bin + 1):
            yield level_index, 1
    elif current_bin < previous_bin:
        for level_index in range(previous_bin, current_bin, -1):
            yield level_index, -1


def build_events(frame: pd.DataFrame, symbol: str, date: str, stage: str) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    timestamps = frame["timestamp"].to_numpy(dtype=np.float64)
    prices = frame["price"].to_numpy(dtype=np.float64)
    sizes = frame["size"].to_numpy(dtype=np.float64)
    sides = np.where(frame["side"].to_numpy() == "Buy", 1.0, -1.0)
    notionals = prices * sizes
    base_step = adaptive_base_step(float(prices[0]))
    event_rows: list[dict[str, Any]] = []
    inventory: list[dict[str, Any]] = []

    for grid_multiplier in GRID_MULTIPLIERS:
        step = base_step * grid_multiplier
        bins = np.floor(prices / step).astype(np.int64)
        changed = np.flatnonzero(np.diff(bins) != 0) + 1
        last_cross_by_level: dict[int, float] = {}
        raw_crossings = 0
        accepted_crossings = 0
        for index in changed:
            for level_index, crossing_direction in crossed_levels(int(bins[index - 1]), int(bins[index])):
                raw_crossings += 1
                crossing_time = float(timestamps[index])
                prior = last_cross_by_level.get(level_index, -math.inf)
                if crossing_time - prior < COOLDOWN_SECONDS:
                    continue
                last_cross_by_level[level_index] = crossing_time
                accepted_crossings += 1
                level = float(level_index * step)
                for confirm_seconds in CONFIRM_SECONDS:
                    decision_time = crossing_time + confirm_seconds
                    decision_index = int(np.searchsorted(timestamps, decision_time, side="right") - 1)
                    entry_index = int(np.searchsorted(timestamps, decision_time + ENTRY_LATENCY_SECONDS, side="left"))
                    if decision_index < index or entry_index >= len(frame):
                        continue
                    confirm_count = decision_index - index + 1
                    if confirm_count < MIN_CONFIRM_TRADES:
                        continue
                    section = slice(index, decision_index + 1)
                    section_notional = notionals[section]
                    total_notional = float(section_notional.sum())
                    if not math.isfinite(total_notional) or total_notional <= 0:
                        continue
                    directional_offsets = crossing_direction * (prices[section] - level)
                    flow = float(crossing_direction * np.sum(sides[section] * section_notional) / total_notional)
                    destination_mask = directional_offsets >= 0.0
                    through_ratio = float(section_notional[destination_mask].sum() / total_notional)
                    close_fraction = float(crossing_direction * (prices[decision_index] - level) / step)
                    max_destination_fraction = float(np.max(directional_offsets) / step)
                    max_origin_fraction = float(np.max(-directional_offsets) / step)
                    entry_time = float(timestamps[entry_index])
                    row: dict[str, Any] = {
                        "event_id": stable_id(
                            {
                                "symbol": symbol,
                                "date": date,
                                "grid_multiplier": grid_multiplier,
                                "level_index": level_index,
                                "crossing_time": crossing_time,
                                "crossing_direction": crossing_direction,
                                "confirm_seconds": confirm_seconds,
                            }
                        ),
                        "stage": stage,
                        "symbol": symbol,
                        "date": date,
                        "grid_multiplier": grid_multiplier,
                        "grid_step": step,
                        "level": level,
                        "crossing_time": crossing_time,
                        "crossing_direction": crossing_direction,
                        "confirm_seconds": confirm_seconds,
                        "decision_time": decision_time,
                        "entry_time": entry_time,
                        "entry_price": float(prices[entry_index]),
                        "confirm_trades": confirm_count,
                        "confirm_notional": total_notional,
                        "aligned_flow": flow,
                        "through_ratio": through_ratio,
                        "close_fraction": close_fraction,
                        "max_destination_fraction": max_destination_fraction,
                        "max_origin_fraction": max_origin_fraction,
                    }
                    for horizon in HORIZONS_SECONDS:
                        exit_index = int(np.searchsorted(timestamps, entry_time + horizon, side="left"))
                        if exit_index >= len(frame):
                            row[f"exit_time_{horizon}"] = np.nan
                            row[f"gross_cross_bp_{horizon}"] = np.nan
                        else:
                            row[f"exit_time_{horizon}"] = float(timestamps[exit_index])
                            row[f"gross_cross_bp_{horizon}"] = float(
                                crossing_direction * (prices[exit_index] / prices[entry_index] - 1.0) * 1e4
                            )
                    event_rows.append(row)
        inventory.append(
            {
                "stage": stage,
                "symbol": symbol,
                "date": date,
                "first_price": float(prices[0]),
                "base_step": base_step,
                "grid_multiplier": grid_multiplier,
                "grid_step": step,
                "raw_boundary_crossings": raw_crossings,
                "cooldown_accepted_crossings": accepted_crossings,
            }
        )
    return pd.DataFrame(event_rows), inventory


def candidate_grid() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for grid_multiplier in GRID_MULTIPLIERS:
        for confirm_seconds in CONFIRM_SECONDS:
            for family in ("acceptance_continuation", "rejection_reversal"):
                for close_fraction in CLOSE_FRACTIONS:
                    for flow_threshold in FLOW_THRESHOLDS:
                        for through_threshold in THROUGH_THRESHOLDS:
                            for horizon_seconds in HORIZONS_SECONDS:
                                specification = {
                                    "grid_multiplier": grid_multiplier,
                                    "confirm_seconds": confirm_seconds,
                                    "family": family,
                                    "close_fraction": close_fraction,
                                    "flow_threshold": flow_threshold,
                                    "through_threshold": through_threshold,
                                    "horizon_seconds": horizon_seconds,
                                }
                                specification["candidate_id"] = stable_id(specification)
                                candidates.append(specification)
    if len(candidates) != EXPECTED_CANDIDATES:
        raise ContractError(f"candidate-grid mismatch: {len(candidates)}")
    return candidates


def candidate_mask(events: pd.DataFrame, specification: dict[str, Any]) -> np.ndarray:
    base = (
        np.isclose(events["grid_multiplier"].to_numpy(dtype=float), float(specification["grid_multiplier"]))
        & np.isclose(events["confirm_seconds"].to_numpy(dtype=float), float(specification["confirm_seconds"]))
    )
    close_fraction = events["close_fraction"].to_numpy(dtype=float)
    flow = events["aligned_flow"].to_numpy(dtype=float)
    through = events["through_ratio"].to_numpy(dtype=float)
    max_destination = events["max_destination_fraction"].to_numpy(dtype=float)
    close_threshold = float(specification["close_fraction"])
    flow_threshold = float(specification["flow_threshold"])
    through_threshold = float(specification["through_threshold"])
    if specification["family"] == "acceptance_continuation":
        return base & (close_fraction >= close_threshold) & (flow >= flow_threshold) & (through >= through_threshold)
    if specification["family"] == "rejection_reversal":
        return (
            base
            & (max_destination >= close_threshold)
            & (close_fraction <= -close_threshold)
            & (flow <= -flow_threshold)
            & (through <= 1.0 - through_threshold)
        )
    raise ContractError(f"unknown family: {specification['family']}")


def select_global_slot(events: pd.DataFrame, specification: dict[str, Any]) -> pd.DataFrame:
    if events.empty:
        return events.copy()
    mask = candidate_mask(events, specification)
    horizon = int(specification["horizon_seconds"])
    gross_column = f"gross_cross_bp_{horizon}"
    exit_column = f"exit_time_{horizon}"
    selected = events.loc[mask & events[gross_column].notna() & events[exit_column].notna()].copy()
    if selected.empty:
        return selected
    selected = selected.sort_values(["entry_time", "symbol", "event_id"], kind="mergesort")
    keep: list[int] = []
    busy_until = -math.inf
    for index, row in selected.iterrows():
        entry_time = float(row["entry_time"])
        if entry_time < busy_until:
            continue
        keep.append(index)
        busy_until = float(row[exit_column])
    selected = selected.loc[keep].copy()
    direction_multiplier = 1.0 if specification["family"] == "acceptance_continuation" else -1.0
    selected["gross_strategy_bp"] = direction_multiplier * selected[gross_column].to_numpy(dtype=float)
    return selected


def path_metrics(selected: pd.DataFrame, cost_bps: float, all_stage_dates: tuple[str, ...]) -> dict[str, Any]:
    if selected.empty:
        return {
            "trades": 0,
            "mean_net_bp": 0.0,
            "median_net_bp": 0.0,
            "profit_factor": 0.0,
            "multiple": 1.0,
            "total_return": 0.0,
            "geometric_daily_growth": 0.0,
            "maximum_drawdown": 0.0,
            "top_five_positive_share": 1.0,
            "top_10_percent_removed_return": 0.0,
            "positive_date_fraction": 0.0,
            "positive_symbol_date_fraction": 0.0,
            "date_multiples": {date: 1.0 for date in all_stage_dates},
            "symbol_date_multiples": {f"{symbol}|{date}": 1.0 for date in all_stage_dates for symbol in SYMBOLS},
        }
    net_bp = selected["gross_strategy_bp"].to_numpy(dtype=float) - cost_bps
    simple = net_bp / 1e4
    if np.any(simple <= -1.0):
        raise ContractError("trade return <= -100% in fatal screen")
    equity = np.cumprod(1.0 + simple)
    path = np.concatenate(([1.0], equity))
    peak = np.maximum.accumulate(path)
    maximum_drawdown = float(np.max(1.0 - path / peak))
    positives = net_bp[net_bp > 0.0]
    negatives = net_bp[net_bp < 0.0]
    profit_factor = float(positives.sum() / max(-negatives.sum(), 1e-12)) if len(positives) else 0.0
    top_n = min(5, len(positives))
    top_five_share = float(np.sort(positives)[-top_n:].sum() / max(positives.sum(), 1e-12)) if top_n else 1.0
    remove_n = max(1, int(math.ceil(0.10 * len(net_bp))))
    remove_indices = np.argsort(net_bp)[-remove_n:]
    keep = np.ones(len(net_bp), dtype=bool)
    keep[remove_indices] = False
    removed_return = float(np.prod(1.0 + simple[keep]) - 1.0) if keep.any() else 0.0

    date_multiples: dict[str, float] = {}
    selected_dates = selected["date"].astype(str).to_numpy()
    selected_symbols = selected["symbol"].astype(str).to_numpy()
    for date in all_stage_dates:
        date_multiples[date] = float(np.prod(1.0 + simple[selected_dates == date]))
    symbol_date_multiples: dict[str, float] = {}
    for date in all_stage_dates:
        for symbol in SYMBOLS:
            group_mask = (selected_dates == date) & (selected_symbols == symbol)
            symbol_date_multiples[f"{symbol}|{date}"] = float(np.prod(1.0 + simple[group_mask]))
    geometric_daily_growth = float(np.prod(list(date_multiples.values())) ** (1.0 / len(all_stage_dates)) - 1.0)
    return {
        "trades": int(len(net_bp)),
        "mean_net_bp": float(np.mean(net_bp)),
        "median_net_bp": float(np.median(net_bp)),
        "profit_factor": profit_factor,
        "multiple": float(equity[-1]),
        "total_return": float(equity[-1] - 1.0),
        "geometric_daily_growth": geometric_daily_growth,
        "maximum_drawdown": maximum_drawdown,
        "top_five_positive_share": top_five_share,
        "top_10_percent_removed_return": removed_return,
        "positive_date_fraction": float(np.mean(np.asarray(list(date_multiples.values())) > 1.0)),
        "positive_symbol_date_fraction": float(np.mean(np.asarray(list(symbol_date_multiples.values())) > 1.0)),
        "date_multiples": date_multiples,
        "symbol_date_multiples": symbol_date_multiples,
    }


def passes_development_gate(cost_metrics: dict[str, dict[str, Any]]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    m12 = cost_metrics["12"]
    m18 = cost_metrics["18"]
    m24 = cost_metrics["24"]
    if int(m18["trades"]) < 60:
        failures.append("minimum_trades_at_18bp")
    if float(m18["mean_net_bp"]) <= 0.0:
        failures.append("mean_net_markout_at_18bp")
    if float(m12["median_net_bp"]) <= 0.0:
        failures.append("median_net_markout_at_12bp")
    if float(m24["total_return"]) <= 0.0:
        failures.append("total_return_at_24bp")
    if float(m18["top_10_percent_removed_return"]) <= 0.0:
        failures.append("top_10_percent_removed_return_at_18bp")
    if float(m18["positive_date_fraction"]) < (2.0 / 3.0):
        failures.append("positive_date_fraction_at_18bp")
    if float(m18["positive_symbol_date_fraction"]) < 0.5:
        failures.append("positive_symbol_date_fraction_at_18bp")
    if float(m18["top_five_positive_share"]) > 0.5:
        failures.append("top_five_positive_trade_share_at_18bp")
    return not failures, failures


def evaluate(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for specification in candidate_grid():
        record = dict(specification)
        for stage, dates in (("fit", FIT_DATES), ("development", DEVELOPMENT_DATES)):
            stage_events = events.loc[events["stage"] == stage]
            selected = select_global_slot(stage_events, specification)
            for cost in COSTS_BPS:
                metrics = path_metrics(selected, cost, dates)
                for key, value in metrics.items():
                    if key in ("date_multiples", "symbol_date_multiples"):
                        record[f"{stage}_{int(cost)}_{key}"] = json.dumps(value, sort_keys=True, separators=(",", ":"))
                    else:
                        record[f"{stage}_{int(cost)}_{key}"] = value
        development_metrics = {
            str(int(cost)): {
                key: record[f"development_{int(cost)}_{key}"]
                for key in (
                    "trades",
                    "mean_net_bp",
                    "median_net_bp",
                    "profit_factor",
                    "multiple",
                    "total_return",
                    "geometric_daily_growth",
                    "maximum_drawdown",
                    "top_five_positive_share",
                    "top_10_percent_removed_return",
                    "positive_date_fraction",
                    "positive_symbol_date_fraction",
                )
            }
            for cost in COSTS_BPS
        }
        passed, failures = passes_development_gate(development_metrics)
        record["development_gate"] = passed
        record["gate_failures"] = ";".join(failures)
        records.append(record)
    results = pd.DataFrame(records)
    if len(results) != EXPECTED_CANDIDATES:
        raise ContractError("evaluation candidate count mismatch")
    survivors = results.loc[results["development_gate"]].copy()
    nonzero = results.loc[results["development_18_trades"] > 0].copy()
    if nonzero.empty:
        best: dict[str, Any] | None = None
    else:
        eligible = nonzero.loc[nonzero["development_18_trades"] >= 10]
        pool = eligible if not eligible.empty else nonzero
        best_row = pool.sort_values(
            ["development_18_total_return", "development_18_trades", "candidate_id"],
            ascending=[False, False, True],
            kind="mergesort",
        ).iloc[0]
        specification_keys = (
            "candidate_id",
            "grid_multiplier",
            "confirm_seconds",
            "family",
            "close_fraction",
            "flow_threshold",
            "through_threshold",
            "horizon_seconds",
            "development_gate",
            "gate_failures",
        )
        best = {key: finite(best_row[key]) for key in specification_keys}
        best["cost_metrics"] = {
            str(int(cost)): {
                key: finite(best_row[f"development_{int(cost)}_{key}"])
                for key in (
                    "trades",
                    "mean_net_bp",
                    "median_net_bp",
                    "profit_factor",
                    "multiple",
                    "total_return",
                    "geometric_daily_growth",
                    "maximum_drawdown",
                    "top_five_positive_share",
                    "top_10_percent_removed_return",
                    "positive_date_fraction",
                    "positive_symbol_date_fraction",
                )
            }
            for cost in COSTS_BPS
        }
    summary = {
        "candidate_count": int(len(results)),
        "development_gate_count": int(len(survivors)),
        "positive_total_return_candidate_count": {
            str(int(cost)): int((results[f"development_{int(cost)}_total_return"] > 0.0).sum()) for cost in COSTS_BPS
        },
        "positive_after_top10_removal_candidate_count": {
            str(int(cost)): int((results[f"development_{int(cost)}_top_10_percent_removed_return"] > 0.0).sum()) for cost in COSTS_BPS
        },
        "maximum_development_trades": int(results["development_18_trades"].max()),
        "best_raw_candidate": best,
    }
    return results, summary


def write_sha_manifest(output: Path) -> None:
    rows: list[str] = []
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "SHA256SUMS.txt":
            rows.append(f"{sha256_file(path)}  {path.relative_to(output).as_posix()}")
    (output / "SHA256SUMS.txt").write_text("\n".join(rows) + "\n", encoding="utf-8")


def run(cache: Path, output: Path) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    source_rows: list[dict[str, Any]] = []
    event_frames: list[pd.DataFrame] = []
    event_inventory: list[dict[str, Any]] = []
    for date in ALL_DATES:
        stage = "fit" if date in FIT_DATES else "development"
        for symbol in SYMBOLS:
            archive, source = download_archive(symbol, date, cache)
            frame = load_trades(archive, symbol)
            source["first_timestamp"] = float(frame["timestamp"].iloc[0])
            source["last_timestamp"] = float(frame["timestamp"].iloc[-1])
            source["stage"] = stage
            source_rows.append(source)
            events, inventory = build_events(frame, symbol, date, stage)
            event_frames.append(events)
            event_inventory.extend(inventory)
            del frame
    events = pd.concat(event_frames, ignore_index=True) if event_frames else pd.DataFrame()
    if events.empty:
        raise ContractError("no round-number events")
    events = events.sort_values(["entry_time", "symbol", "event_id"], kind="mergesort").reset_index(drop=True)
    results, screen = evaluate(events)
    survivors = results.loc[results["development_gate"]].copy()

    events.to_csv(output / "event_ledger.csv.gz", index=False, compression="gzip")
    pd.DataFrame(event_inventory).to_csv(output / "event_inventory.csv", index=False)
    results.to_csv(output / "candidate_results.csv", index=False)
    survivors.to_csv(output / "development_survivors.csv", index=False)
    source_manifest = {
        "schema_version": 1,
        "claim_id": CLAIM_ID,
        "source": "Bybit public USDT linear perpetual historical trade archives",
        "base_url": BASE_URL,
        "symbols": list(SYMBOLS),
        "fit_dates": list(FIT_DATES),
        "development_dates": list(DEVELOPMENT_DATES),
        "archives": source_rows,
        "later_periods_opened": False,
        "orders_submitted": False,
    }
    (output / "source_manifest.json").write_text(json.dumps(source_manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    result = {
        "schema_version": 1,
        "result_id": RESULT_ID,
        "claim_id": CLAIM_ID,
        "status": "FATAL_SCREEN_SURVIVOR_REQUIRES_BBO_RECONSTRUCTION" if screen["development_gate_count"] else "TESTED_BELOW_GATE",
        "hard_validity_status": "PRELIMINARY_CAUSAL_PASS_TRADES_ONLY_FATAL_SCREEN",
        "economic_status": "CANDIDATE" if screen["development_gate_count"] else "BELOW_GATE",
        "ranking_role": "FATAL_SCREEN_ONLY_NOT_RANKED",
        "hypothesis": "Adaptive absolute round-number crossings may continue only when the destination side is causally accepted with aligned aggressor flow; crossings that are promptly rejected with opposite flow may mean-revert over 2-30 minutes.",
        "event_count": int(len(events)),
        "event_count_by_stage": {str(key): int(value) for key, value in events.groupby("stage").size().items()},
        "screen": screen,
        "data_limitations": [
            "The fatal screen uses historical public trade prints and first-trade-after-latency marks rather than executable bid/ask or depth.",
            "Only six sparse 2023 dates and BTCUSDT/ETHUSDT are opened; 2024-2026 remain sealed.",
            "Fixed markout horizons diagnose payoff persistence and are not a deployment exit rule."
        ],
        "conditional_next_stage": (
            "Reconstruct exact Bybit BBO/depth for a single frozen survivor, add structural exit and NAV risk sizing, then expand pre-2024 coverage before any 2024 opening."
            if screen["development_gate_count"]
            else "Close this exact round-number acceptance/rejection formulation as reusable negative evidence and move to a materially different source or payoff."
        ),
        "2024_opened": False,
        "2025_opened": False,
        "2026_opened": False,
        "orders_submitted": False
    }
    (output / "result_summary.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_sha_manifest(output)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)
    return result


def self_test() -> None:
    times = np.asarray([0.0, 0.5, 1.0, 1.2, 1.5, 2.1, 3.2, 4.0, 6.0, 11.2, 31.2, 121.2, 301.2, 901.2, 1801.2])
    prices = np.asarray([99.0, 99.5, 100.0, 100.5, 100.2, 99.5, 99.0, 98.8, 98.5, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0])
    sides = ["Buy", "Buy", "Buy", "Buy", "Sell", "Sell", "Sell", "Sell", "Sell", "Sell", "Sell", "Sell", "Sell", "Sell", "Sell"]
    frame = pd.DataFrame({"timestamp": times, "symbol": ["TEST"] * len(times), "side": sides, "size": np.ones(len(times)), "price": prices})
    events, _ = build_events(frame, "TEST", "2023-01-01", "development")
    target = events.loc[
        np.isclose(events["grid_multiplier"], 2.0)
        & np.isclose(events["level"], 100.0)
        & (events["crossing_direction"] == 1)
        & np.isclose(events["confirm_seconds"], 3.0)
    ]
    assert len(target) == 1
    row = target.iloc[0]
    assert float(row["decision_time"]) == 4.0
    assert float(row["entry_time"]) >= 4.1
    assert float(row["close_fraction"]) < 0.0
    assert float(row["aligned_flow"]) < 0.0
    spec = {
        "grid_multiplier": 2.0,
        "confirm_seconds": 3.0,
        "family": "rejection_reversal",
        "close_fraction": 0.005,
        "flow_threshold": 0.0,
        "through_threshold": 0.6,
        "horizon_seconds": 120,
    }
    selected = select_global_slot(events, spec)
    assert len(selected) >= 1
    assert (selected["entry_time"] >= selected["decision_time"] + ENTRY_LATENCY_SECONDS).all()
    m12 = path_metrics(selected, 12.0, ("2023-01-01",))
    m18 = path_metrics(selected, 18.0, ("2023-01-01",))
    m24 = path_metrics(selected, 24.0, ("2023-01-01",))
    assert m12["total_return"] >= m18["total_return"] >= m24["total_return"]

    extended = pd.concat(
        [frame, pd.DataFrame({"timestamp": [4000.0], "symbol": ["TEST"], "side": ["Buy"], "size": [1.0], "price": [110.0]})],
        ignore_index=True,
    )
    extended_events, _ = build_events(extended, "TEST", "2023-01-01", "development")
    common = ["event_id", "decision_time", "entry_time", "close_fraction", "aligned_flow", "through_ratio"]
    left = events.loc[events["entry_time"] < 3000.0, common].sort_values("event_id").reset_index(drop=True)
    right = extended_events.loc[extended_events["event_id"].isin(left["event_id"]), common].sort_values("event_id").reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right, check_exact=True)

    assert EXPECTED_CANDIDATES == 576
    assert len(candidate_grid()) == 576
    print("SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "run":
        run(args.cache, args.output)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
