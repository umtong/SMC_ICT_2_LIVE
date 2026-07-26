from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import hashlib
import json
import math
import os
import statistics
import time
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import requests

ROOT = Path(__file__).resolve().parent
PREREG_PATH = ROOT / "preregistration.json"
BASE_URL = "https://public.bybit.com/trading"
DISCOVERY_DATES = ("2023-06-11", "2023-09-17", "2023-12-17")
VALIDATION_DATES = ("2023-07-15", "2023-08-15", "2023-10-15", "2023-11-15")
PAIRS = (("BTC", "BTCPERP", "BTCUSDT"), ("ETH", "ETHPERP", "ETHUSDT"))
FAMILIES = (
    "usdc_move_continuation",
    "usdc_residual_continuation",
    "usdc_residual_reversal",
    "usdc_flow_continuation",
)
SIGNAL_QUANTILES = (0.90, 0.97)
NOTIONAL_QUANTILES = (0.50, 0.90)
MIN_IMBALANCES = (0.50, 0.80)
MAX_PREMOVE_RATIOS = (0.50, 1.00)
HORIZONS = (1, 5, 15, 60, 300)
COSTS = (12.0, 18.0, 24.0)
LATENCY_NS = 100_000_000
SYMBOL_RANK = {"BTCUSDT": 0, "ETHUSDT": 1}


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def timestamp_ns(value: str) -> int:
    raw = value.strip()
    try:
        x = float(raw)
    except ValueError as exc:
        raise ValueError(f"unsupported timestamp {value!r}") from exc
    ax = abs(x)
    if ax < 1e11:
        return int(round(x * 1_000_000_000))
    if ax < 1e14:
        return int(round(x * 1_000_000))
    if ax < 1e17:
        return int(round(x * 1_000))
    return int(round(x))


def quantile(values: Iterable[float], q: float) -> float:
    ordered = sorted(float(x) for x in values if math.isfinite(float(x)))
    if not ordered:
        raise ValueError("cannot estimate a quantile from no finite observations")
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * q
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def sign(value: float) -> int:
    return 1 if value > 0.0 else -1 if value < 0.0 else 0


def archive_url(symbol: str, date: str) -> str:
    return f"{BASE_URL}/{symbol}/{symbol}{date}.csv.gz"


def download_archive(session: requests.Session, cache: Path, symbol: str, date: str) -> tuple[Path, str, int]:
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / f"{symbol}{date}.csv.gz"
    if not target.exists() or target.stat().st_size == 0:
        url = archive_url(symbol, date)
        temporary = target.with_suffix(target.suffix + ".part")
        last_error: Exception | None = None
        for attempt in range(1, 5):
            try:
                with session.get(url, stream=True, timeout=(30, 600)) as response:
                    response.raise_for_status()
                    with temporary.open("wb") as handle:
                        for chunk in response.iter_content(chunk_size=1024 * 1024):
                            if chunk:
                                handle.write(chunk)
                os.replace(temporary, target)
                break
            except Exception as exc:
                last_error = exc
                temporary.unlink(missing_ok=True)
                if attempt == 4:
                    raise RuntimeError(f"download failed after four attempts: {url}") from exc
                time.sleep(float(attempt))
        if last_error is not None and not target.exists():
            raise RuntimeError(f"download failed: {url}") from last_error
    with gzip.open(target, "rb") as handle:
        while handle.read(1024 * 1024):
            pass
    return target, sha256_file(target), target.stat().st_size


def open_csv(path: Path) -> tuple[csv.reader, Any, dict[str, int]]:
    handle = gzip.open(path, "rt", encoding="utf-8-sig", newline="")
    reader = csv.reader(handle)
    try:
        header = next(reader)
    except StopIteration:
        handle.close()
        raise ValueError(f"empty archive: {path}")
    index = {name.strip().lower(): position for position, name in enumerate(header)}
    required = {"timestamp", "symbol", "side", "size", "price", "trdmatchid"}
    missing = sorted(required - set(index))
    if missing:
        handle.close()
        raise ValueError(f"missing required columns {missing} in {path}; header={header}")
    return reader, handle, index


def parse_usdt(path: Path) -> tuple[array, array, int]:
    reader, handle, idx = open_csv(path)
    timestamps = array("q")
    prices = array("d")
    count = 0
    last_ts = -1
    try:
        for row in reader:
            if not row:
                continue
            ts = timestamp_ns(row[idx["timestamp"]])
            price = float(row[idx["price"]])
            if not math.isfinite(price) or price <= 0.0:
                continue
            if ts < last_ts:
                raise ValueError(f"USDT archive is not time ordered: {path} row={count + 2}")
            timestamps.append(ts)
            prices.append(price)
            last_ts = ts
            count += 1
    finally:
        handle.close()
    if not timestamps:
        raise ValueError(f"no usable USDT trades in {path}")
    return timestamps, prices, count


@dataclass(frozen=True)
class USDCEvent:
    timestamp_ns: int
    price: float
    notional: float
    imbalance: float


def parse_usdc_events(path: Path) -> tuple[list[USDCEvent], int]:
    reader, handle, idx = open_csv(path)
    events: list[USDCEvent] = []
    count = 0
    current_ts: int | None = None
    current_price = 0.0
    total_notional = 0.0
    signed_notional = 0.0
    last_ts = -1

    def flush() -> None:
        nonlocal current_ts, current_price, total_notional, signed_notional
        if current_ts is not None and total_notional > 0.0 and current_price > 0.0:
            events.append(USDCEvent(current_ts, current_price, total_notional, signed_notional / total_notional))
        current_ts = None
        current_price = 0.0
        total_notional = 0.0
        signed_notional = 0.0

    try:
        for row in reader:
            if not row:
                continue
            ts = timestamp_ns(row[idx["timestamp"]])
            price = float(row[idx["price"]])
            size = float(row[idx["size"]])
            if not all(math.isfinite(x) for x in (price, size)) or price <= 0.0 or size <= 0.0:
                continue
            if ts < last_ts:
                raise ValueError(f"USDC archive is not time ordered: {path} row={count + 2}")
            if current_ts is None or ts != current_ts:
                flush()
                current_ts = ts
            side = row[idx["side"]].strip().lower()
            aggressor = 1.0 if side == "buy" else -1.0 if side == "sell" else 0.0
            notional = price * size
            current_price = price
            total_notional += notional
            signed_notional += aggressor * notional
            last_ts = ts
            count += 1
        flush()
    finally:
        handle.close()
    if len(events) < 2:
        raise ValueError(f"fewer than two usable USDC events in {path}")
    return events, count


def last_at_or_before(timestamps: array, prices: array, timestamp: int) -> tuple[int, float] | None:
    index = bisect.bisect_right(timestamps, timestamp) - 1
    if index < 0:
        return None
    return int(timestamps[index]), float(prices[index])


def first_at_or_after(timestamps: array, prices: array, timestamp: int) -> tuple[int, float] | None:
    index = bisect.bisect_left(timestamps, timestamp)
    if index >= len(timestamps):
        return None
    return int(timestamps[index]), float(prices[index])


def build_labeled_events(base: str, date: str, usdc_events: list[USDCEvent], usdt_timestamps: array, usdt_prices: array) -> list[dict[str, Any]]:
    execution_symbol = f"{base}USDT"
    labeled: list[dict[str, Any]] = []
    previous = usdc_events[0]
    for current in usdc_events[1:]:
        if current.price <= 0.0 or previous.price <= 0.0 or current.timestamp_ns <= previous.timestamp_ns:
            previous = current
            continue
        previous_usdt = last_at_or_before(usdt_timestamps, usdt_prices, previous.timestamp_ns)
        current_usdt = last_at_or_before(usdt_timestamps, usdt_prices, current.timestamp_ns)
        entry = first_at_or_after(usdt_timestamps, usdt_prices, current.timestamp_ns + LATENCY_NS)
        if previous_usdt is None or current_usdt is None or entry is None:
            previous = current
            continue
        usdc_move_bps = 10_000.0 * math.log(current.price / previous.price)
        usdt_pre_move_bps = 10_000.0 * math.log(current_usdt[1] / previous_usdt[1])
        residual_bps = usdc_move_bps - usdt_pre_move_bps
        ratio = math.inf if abs(usdc_move_bps) < 1e-12 else abs(usdt_pre_move_bps) / abs(usdc_move_bps)
        exits: dict[str, dict[str, float | int]] = {}
        for horizon in HORIZONS:
            exit_mark = first_at_or_after(usdt_timestamps, usdt_prices, entry[0] + horizon * 1_000_000_000)
            if exit_mark is None:
                continue
            exits[str(horizon)] = {
                "timestamp_ns": exit_mark[0],
                "price": exit_mark[1],
                "markout_bps": 10_000.0 * math.log(exit_mark[1] / entry[1]),
            }
        if exits:
            labeled.append({
                "date": date,
                "base": base,
                "symbol": execution_symbol,
                "event_timestamp_ns": current.timestamp_ns,
                "entry_timestamp_ns": entry[0],
                "entry_price": entry[1],
                "event_notional": current.notional,
                "event_imbalance": current.imbalance,
                "usdc_move_bps": usdc_move_bps,
                "usdt_pre_move_bps": usdt_pre_move_bps,
                "residual_bps": residual_bps,
                "pre_move_ratio": ratio,
                "exits": exits,
            })
        previous = current
    return labeled


def family_signal(event: dict[str, Any], family: str) -> float:
    if family == "usdc_move_continuation":
        return float(event["usdc_move_bps"])
    if family in ("usdc_residual_continuation", "usdc_residual_reversal"):
        return float(event["residual_bps"])
    if family == "usdc_flow_continuation":
        return float(event["event_imbalance"])
    raise KeyError(family)


def family_direction(event: dict[str, Any], family: str) -> int:
    value = family_signal(event, family)
    return -sign(value) if family == "usdc_residual_reversal" else sign(value)


def learn_thresholds(discovery_events: list[dict[str, Any]]) -> dict[str, Any]:
    thresholds: dict[str, Any] = {}
    for symbol in ("BTCUSDT", "ETHUSDT"):
        subset = [event for event in discovery_events if event["symbol"] == symbol]
        if not subset:
            raise ValueError(f"no discovery events for {symbol}")
        thresholds[symbol] = {
            "notional": {f"{q:.2f}": quantile((event["event_notional"] for event in subset), q) for q in NOTIONAL_QUANTILES},
            "signals": {},
            "observation_count": len(subset),
        }
        for family in FAMILIES:
            absolute_signals = [abs(family_signal(event, family)) for event in subset if family_signal(event, family) != 0.0]
            thresholds[symbol]["signals"][family] = {f"{q:.2f}": quantile(absolute_signals, q) for q in SIGNAL_QUANTILES}
    return thresholds


def candidate_grid() -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for family in FAMILIES:
        for signal_q in SIGNAL_QUANTILES:
            for notional_q in NOTIONAL_QUANTILES:
                for imbalance in MIN_IMBALANCES:
                    for ratio in MAX_PREMOVE_RATIOS:
                        for horizon in HORIZONS:
                            spec = {
                                "family": family,
                                "signal_q": signal_q,
                                "notional_q": notional_q,
                                "minimum_abs_imbalance": imbalance,
                                "maximum_pre_move_ratio": ratio,
                                "horizon": horizon,
                            }
                            spec["candidate_id"] = hashlib.sha256(canonical_json(spec)).hexdigest()[:20]
                            candidates.append(spec)
    if len(candidates) != 320:
        raise AssertionError(f"candidate count {len(candidates)} != 320")
    return candidates


def eligible_events(validation_events: list[dict[str, Any]], thresholds: dict[str, Any], spec: dict[str, Any]) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    horizon_key = str(spec["horizon"])
    for event in validation_events:
        if horizon_key not in event["exits"]:
            continue
        signal_value = family_signal(event, spec["family"])
        direction = family_direction(event, spec["family"])
        if direction == 0:
            continue
        symbol_thresholds = thresholds[event["symbol"]]
        if abs(signal_value) < symbol_thresholds["signals"][spec["family"]][f"{spec['signal_q']:.2f}"]:
            continue
        if float(event["event_notional"]) < symbol_thresholds["notional"][f"{spec['notional_q']:.2f}"]:
            continue
        if abs(float(event["event_imbalance"])) < float(spec["minimum_abs_imbalance"]):
            continue
        if float(event["pre_move_ratio"]) > float(spec["maximum_pre_move_ratio"]):
            continue
        exit_mark = event["exits"][horizon_key]
        selected.append({
            "date": event["date"],
            "symbol": event["symbol"],
            "event_timestamp_ns": event["event_timestamp_ns"],
            "entry_timestamp_ns": event["entry_timestamp_ns"],
            "exit_timestamp_ns": int(exit_mark["timestamp_ns"]),
            "direction": direction,
            "gross_bps": direction * float(exit_mark["markout_bps"]),
        })
    selected.sort(key=lambda row: (int(row["entry_timestamp_ns"]), SYMBOL_RANK[row["symbol"]], int(row["event_timestamp_ns"])))
    return selected


def apply_global_slot(raw_events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    release = -1
    for event in raw_events:
        if int(event["entry_timestamp_ns"]) < release:
            continue
        accepted.append(event)
        release = int(event["exit_timestamp_ns"])
    return accepted


def compounded_return(net_bps: Iterable[float]) -> float:
    return math.exp(sum(float(value) / 10_000.0 for value in net_bps)) - 1.0


def maximum_drawdown(net_bps: Iterable[float]) -> float:
    equity = 1.0
    peak = 1.0
    maximum = 0.0
    for value in net_bps:
        equity *= math.exp(float(value) / 10_000.0)
        peak = max(peak, equity)
        maximum = max(maximum, 1.0 - equity / peak)
    return maximum


def cost_metrics(accepted: list[dict[str, Any]], cost: float) -> dict[str, Any]:
    net = [float(event["gross_bps"]) - cost for event in accepted]
    positive = [value for value in net if value > 0.0]
    negative = [value for value in net if value < 0.0]
    segment_keys = [f"{date}|{symbol}" for date in VALIDATION_DATES for symbol in ("BTCUSDT", "ETHUSDT")]
    segment_values: dict[str, list[float]] = {key: [] for key in segment_keys}
    for event, value in zip(accepted, net):
        segment_values[f"{event['date']}|{event['symbol']}"].append(value)
    segment_returns = {key: compounded_return(values) for key, values in segment_values.items()}
    positive_fraction = sum(value > 0.0 for value in segment_returns.values()) / len(segment_returns)
    remove_count = min(len(positive), int(math.ceil(0.10 * len(net)))) if net else 0
    removed = sorted(positive, reverse=True)[:remove_count]
    remaining = list(net)
    for value in removed:
        remaining.remove(value)
    positive_sum = sum(positive)
    top_five_share = None if positive_sum <= 0.0 else sum(sorted(positive, reverse=True)[:5]) / positive_sum
    return {
        "trade_count": len(net),
        "mean_net_bps": statistics.fmean(net) if net else None,
        "median_net_bps": statistics.median(net) if net else None,
        "total_return": compounded_return(net),
        "maximum_drawdown": maximum_drawdown(net),
        "profit_factor": None if not negative else sum(positive) / abs(sum(negative)),
        "top_10_percent_removed_return": compounded_return(remaining),
        "top_five_positive_share": top_five_share,
        "positive_symbol_date_fraction": positive_fraction,
        "symbol_date_returns": segment_returns,
    }


def evaluate_candidate(validation_events: list[dict[str, Any]], thresholds: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    raw = eligible_events(validation_events, thresholds, spec)
    accepted = apply_global_slot(raw)
    metrics = {str(int(cost)): cost_metrics(accepted, cost) for cost in COSTS}
    reasons: list[str] = []
    if metrics["18"]["trade_count"] < 40:
        reasons.append("trade_count_lt_40")
    if metrics["18"]["mean_net_bps"] is None or metrics["18"]["mean_net_bps"] <= 0.0:
        reasons.append("mean_18bp_not_positive")
    if metrics["12"]["median_net_bps"] is None or metrics["12"]["median_net_bps"] <= 0.0:
        reasons.append("median_12bp_not_positive")
    if metrics["24"]["total_return"] <= 0.0:
        reasons.append("total_24bp_not_positive")
    if metrics["18"]["top_10_percent_removed_return"] <= 0.0:
        reasons.append("top10_removed_18bp_not_positive")
    if metrics["18"]["positive_symbol_date_fraction"] < 2.0 / 3.0:
        reasons.append("positive_symbol_date_fraction_lt_two_thirds")
    share = metrics["18"]["top_five_positive_share"]
    if share is None or share > 0.50:
        reasons.append("top_five_share_gt_50pct")
    return {
        "candidate_id": spec["candidate_id"],
        "specification": {key: value for key, value in spec.items() if key != "candidate_id"},
        "raw_eligible_event_count": len(raw),
        "accepted_trade_count": len(accepted),
        "cost_metrics": metrics,
        "gate_pass": not reasons,
        "gate_reasons": reasons,
    }


def result_sort_key(candidate: dict[str, Any]) -> tuple[float, float, int]:
    metrics = candidate["cost_metrics"]
    return (float(metrics["18"]["total_return"]), float(metrics["24"]["total_return"]), int(metrics["18"]["trade_count"]))


def run(cache: Path, output: Path) -> None:
    prereg = json.loads(PREREG_PATH.read_text(encoding="utf-8"))
    if tuple(prereg["data_contract"]["discovery_dates_already_opened"]) != DISCOVERY_DATES:
        raise AssertionError("discovery dates differ from the frozen contract")
    if tuple(prereg["data_contract"]["frozen_validation_dates_unopened_at_preregistration"]) != VALIDATION_DATES:
        raise AssertionError("validation dates differ from the frozen contract")
    output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "SMC-ICT-2-LIVE-USDC-leadlag/1.0"})
    discovery_events: list[dict[str, Any]] = []
    validation_events: list[dict[str, Any]] = []
    archives: list[dict[str, Any]] = []

    for role, dates in (("discovery", DISCOVERY_DATES), ("frozen_validation", VALIDATION_DATES)):
        for date in dates:
            for base, usdc_symbol, usdt_symbol in PAIRS:
                usdc_path, usdc_sha, usdc_bytes = download_archive(session, cache, usdc_symbol, date)
                usdt_path, usdt_sha, usdt_bytes = download_archive(session, cache, usdt_symbol, date)
                usdt_timestamps, usdt_prices, usdt_rows = parse_usdt(usdt_path)
                usdc_groups, usdc_rows = parse_usdc_events(usdc_path)
                labeled = build_labeled_events(base, date, usdc_groups, usdt_timestamps, usdt_prices)
                (discovery_events if role == "discovery" else validation_events).extend(labeled)
                archives.extend([
                    {"role": role, "date": date, "symbol": usdc_symbol, "url": archive_url(usdc_symbol, date), "retrieved_bytes": usdc_bytes, "row_count": usdc_rows, "sha256": usdc_sha},
                    {"role": role, "date": date, "symbol": usdt_symbol, "url": archive_url(usdt_symbol, date), "retrieved_bytes": usdt_bytes, "row_count": usdt_rows, "sha256": usdt_sha},
                ])
                print("PAIR " + json.dumps({"role": role, "date": date, "base": base, "usdc_rows": usdc_rows, "usdc_events": len(usdc_groups), "usdt_rows": usdt_rows, "labeled_events": len(labeled)}, sort_keys=True), flush=True)
                del usdt_timestamps, usdt_prices, usdc_groups

    if len(archives) != 28:
        raise AssertionError(f"archive count {len(archives)} != 28")
    thresholds = learn_thresholds(discovery_events)
    candidates = [evaluate_candidate(validation_events, thresholds, spec) for spec in candidate_grid()]
    survivors = [candidate for candidate in candidates if candidate["gate_pass"]]
    best_raw = max(candidates, key=result_sort_key)
    sample_candidates = [candidate for candidate in candidates if candidate["cost_metrics"]["18"]["trade_count"] >= 40]
    best_sample = max(sample_candidates, key=result_sort_key) if sample_candidates else None
    positive_counts = {str(int(cost)): sum(candidate["cost_metrics"][str(int(cost))]["total_return"] > 0.0 for candidate in candidates) for cost in COSTS}
    implementation_sha = sha256_file(Path(__file__))
    contract_sha = sha256_file(PREREG_PATH)
    dataset_fingerprint = sha256_bytes(canonical_json(sorted(archives, key=lambda row: (row["date"], row["symbol"]))))
    result = {
        "schema_version": 1,
        "result_id": prereg["provisional_result_id"],
        "claim_id": prereg["claim_id"],
        "screen_id": prereg["screen_id"],
        "status": "FROZEN_VALIDATION_SURVIVOR" if survivors else "TESTED_BELOW_GATE",
        "qualification": "FATAL_ALPHA_SCREEN_ONLY_NOT_RANK_ELIGIBLE",
        "candidate_count": len(candidates),
        "validation_gate_pass_count": len(survivors),
        "positive_total_return_candidate_count": positive_counts,
        "discovery_labeled_event_count": len(discovery_events),
        "validation_labeled_event_count": len(validation_events),
        "best_raw_candidate": best_raw,
        "best_minimum_sample_candidate": best_sample,
        "survivor_candidate_ids": [candidate["candidate_id"] for candidate in survivors],
        "latency_ms": 100,
        "one_global_slot_enforced_within_each_candidate_horizon": True,
        "official_periods_opened": {"2024": False, "2025": False, "2026": False},
        "orders_submitted": False,
        "cost_profiles_bps": list(COSTS),
        "evaluation_contract_sha256": contract_sha,
        "dataset_fingerprint": dataset_fingerprint,
        "implementation_sha256": implementation_sha,
        "limitations": [
            "Sparse seven-date pre-2024 discovery and frozen-validation screen, not an account strategy result.",
            "Entry and exit marks use next observed trades with explicit latency and all-in cost stress but no historical BBO/depth replay.",
            "Any survivor requires broader pre-2024 reconstruction and a newly frozen selection contract before opening 2024.",
        ],
    }
    manifest = {
        "schema_version": 1,
        "claim_id": prereg["claim_id"],
        "result_id": prereg["provisional_result_id"],
        "screen_id": prereg["screen_id"],
        "source": "Bybit public historical trades",
        "base_url": BASE_URL,
        "archive_count": len(archives),
        "archives": archives,
        "discovery_dates": list(DISCOVERY_DATES),
        "frozen_validation_dates": list(VALIDATION_DATES),
        "later_periods_opened": False,
        "orders_submitted": False,
        "dataset_fingerprint": dataset_fingerprint,
        "implementation_sha256": implementation_sha,
    }
    write_json(output / "fit_thresholds.json", thresholds)
    write_json(output / "candidate_results.json", candidates)
    write_json(output / "result_summary.json", result)
    write_json(output / "source_manifest.json", manifest)
    inventory = []
    for path in sorted(output.glob("*")):
        if path.is_file() and path.name != "artifact_inventory.json":
            inventory.append({"name": path.name, "bytes": path.stat().st_size, "sha256": sha256_file(path)})
    write_json(output / "artifact_inventory.json", {"files": inventory})
    print("USDC_LEADLAG_RESULT=" + json.dumps(result, sort_keys=True, separators=(",", ":")), flush=True)


def self_test() -> None:
    assert len(candidate_grid()) == 320
    thresholds = {
        "BTCUSDT": {"notional": {"0.50": 10.0, "0.90": 10.0}, "signals": {family: {"0.90": 1.0, "0.97": 1.0} for family in FAMILIES}},
        "ETHUSDT": {"notional": {"0.50": 10.0, "0.90": 10.0}, "signals": {family: {"0.90": 1.0, "0.97": 1.0} for family in FAMILIES}},
    }
    base_event = {
        "date": VALIDATION_DATES[0], "symbol": "BTCUSDT", "event_timestamp_ns": 1_000_000_000,
        "entry_timestamp_ns": 1_100_000_000, "entry_price": 100.0, "event_notional": 100.0,
        "event_imbalance": 0.9, "usdc_move_bps": 10.0, "usdt_pre_move_bps": 2.0,
        "residual_bps": 8.0, "pre_move_ratio": 0.2,
        "exits": {str(h): {"timestamp_ns": 1_100_000_000 + h * 1_000_000_000, "price": 101.0, "markout_bps": 10.0} for h in HORIZONS},
    }
    spec = candidate_grid()[0]
    raw = eligible_events([base_event, {**base_event, "event_timestamp_ns": 1_200_000_000, "entry_timestamp_ns": 1_300_000_000}], thresholds, spec)
    accepted = apply_global_slot(raw)
    assert all(event["entry_timestamp_ns"] >= event["event_timestamp_ns"] + LATENCY_NS for event in raw)
    assert len(accepted) == 1
    metrics = {cost: cost_metrics(accepted, cost) for cost in COSTS}
    assert metrics[12.0]["total_return"] >= metrics[18.0]["total_return"] >= metrics[24.0]["total_return"]
    print("SELF_TEST_PASS candidate_count=320 latency_and_global_slot=PASS cost_monotonicity=PASS")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--cache", required=True, type=Path)
    run_parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "self-test":
        self_test()
    else:
        run(args.cache, args.output)


if __name__ == "__main__":
    main()
