from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import math
import random
import re
import statistics
import time
import urllib.parse
from collections import defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import orjson
import pyarrow.parquet as pq
import requests

COINS = ("BTC", "ETH", "SOL", "XRP")
SIDE = {"B": 1, "A": -1}
FILE_RE = re.compile(r"^data/node_fills_by_block_hourly_(20\d{6})_(\d{1,2})\.parquet$")
ROLE_BY_DATE = {
    "2025-07-27": "warmup",
    "2025-07-28": "fit",
    "2025-07-29": "fit",
    "2025-07-30": "fit",
    "2025-07-31": "development_a",
    "2025-08-01": "development_a",
    "2025-08-02": "development_a",
    "2025-08-03": "development_b",
    "2025-08-04": "development_b",
    "2025-08-05": "validation",
    "2025-08-06": "validation",
}
PREVALIDATION = {"warmup", "fit", "development_a", "development_b"}
DEV_ROLES = {"development_a", "development_b"}
VALIDATION = {"validation"}
HORIZONS = (60, 300)
MIN_EPISODES = (20, 50)
SHRINK = (50, 200)
TAILS = (0.02, 0.05)


class GateError(RuntimeError):
    pass


@dataclass(frozen=True)
class SourceFile:
    path: str
    date: str
    hour: int
    role: str
    size: int
    sha256: str
    xet_hash: str


@dataclass(frozen=True)
class Observation:
    date: str
    role: str
    coin: str
    wallet: str
    mark60: float | None
    mark300: float | None


@dataclass(frozen=True)
class Snapshot:
    date: str
    role: str
    coin: str
    eligible: tuple[tuple[str, float, int, float], ...]
    top: tuple[str, ...]
    bottom: tuple[str, ...]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def get_json(url: str, retries: int = 5) -> tuple[Any, requests.Response]:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            response = requests.get(
                url,
                timeout=120,
                headers={"Accept": "application/json", "User-Agent": "SMC-ICT-2-LIVE/wallet-skill-gate"},
            )
            response.raise_for_status()
            return response.json(), response
        except Exception as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(min(2**attempt, 12))
    raise GateError(f"GET failed: {url}: {last}")


def next_link(header: str | None) -> str | None:
    if not header:
        return None
    for part in header.split(","):
        if 'rel="next"' in part:
            match = re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None


def resolve_manifest(selection: dict[str, Any], output: Path) -> list[SourceFile]:
    repository = selection["source"]["repository"]
    revision = selection["source"]["revision"]
    expected_dates = {date for dates in selection["partitions"].values() for date in dates}
    url = (
        f"https://huggingface.co/api/datasets/{repository}/tree/"
        f"{urllib.parse.quote(revision, safe='')}/data?recursive=false&expand=false&limit=100"
    )
    items: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    seen: set[str] = set()
    while url:
        if url in seen:
            raise GateError("Repeated source pagination URL")
        seen.add(url)
        payload, response = get_json(url)
        if not isinstance(payload, list):
            raise GateError("Unexpected source tree response")
        pages.append({
            "url": url,
            "status": response.status_code,
            "items": len(payload),
            "sha256": hashlib.sha256(response.content).hexdigest(),
        })
        items.extend(item for item in payload if isinstance(item, dict))
        url = next_link(response.headers.get("Link"))
        if len(pages) > 50:
            raise GateError("Unexpected source pagination depth")

    records: list[SourceFile] = []
    for item in items:
        path = item.get("path")
        if not isinstance(path, str):
            continue
        match = FILE_RE.match(path)
        if not match:
            continue
        raw_date, raw_hour = match.groups()
        date = f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:]}"
        hour = int(raw_hour)
        if date not in expected_dates or hour not in {12, 13, 14, 15}:
            continue
        lfs = item.get("lfs") if isinstance(item.get("lfs"), dict) else {}
        size = item.get("size") if isinstance(item.get("size"), int) else lfs.get("size")
        oid = lfs.get("oid")
        xet = item.get("xetHash") or item.get("xet_hash")
        if not isinstance(size, int) or not isinstance(oid, str) or not isinstance(xet, str):
            raise GateError(f"Missing immutable source fields: {path}")
        records.append(SourceFile(path, date, hour, ROLE_BY_DATE[date], size, oid, xet))
    records.sort(key=lambda item: (item.date, item.hour, item.path))
    canonical = "".join(
        f"{item.path}\t{item.size}\t{item.sha256}\t{item.xet_hash}\n" for item in records
    )
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    if len(records) != int(selection["expected_file_count"]):
        raise GateError(f"File count mismatch: {len(records)}")
    if sum(item.size for item in records) != int(selection["expected_total_bytes"]):
        raise GateError("Source byte total mismatch")
    if digest != selection["expected_canonical_manifest_sha256"]:
        raise GateError("Canonical manifest hash mismatch")
    write_json(output / "SOURCE_MANIFEST.json", {
        "repository": repository,
        "revision": revision,
        "pages": pages,
        "file_count": len(records),
        "total_bytes": sum(item.size for item in records),
        "canonical_sha256": digest,
        "files": [asdict(item) for item in records],
        "rows_read": False,
    })
    (output / "SOURCE_MANIFEST.tsv").write_text(canonical, encoding="utf-8")
    return records


def download_one(record: SourceFile, repository: str, revision: str, raw_root: Path) -> dict[str, Any]:
    target = raw_root / record.path
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == record.size and sha256_file(target) == record.sha256:
        return {"path": record.path, "bytes": record.size, "sha256": record.sha256, "cached": True}
    temp = target.with_suffix(target.suffix + ".part")
    last: Exception | None = None
    for attempt in range(5):
        if temp.exists():
            temp.unlink()
        try:
            url = (
                f"https://huggingface.co/datasets/{repository}/resolve/"
                f"{urllib.parse.quote(revision, safe='')}/{urllib.parse.quote(record.path, safe='/')}?download=true"
            )
            digest = hashlib.sha256()
            size = 0
            with requests.get(url, stream=True, timeout=(30, 300), headers={"User-Agent": "SMC-ICT-2-LIVE/wallet-skill-gate"}) as response:
                response.raise_for_status()
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(8 * 1024 * 1024):
                        if chunk:
                            handle.write(chunk)
                            digest.update(chunk)
                            size += len(chunk)
            if size != record.size or digest.hexdigest() != record.sha256:
                raise GateError(f"Downloaded source hash mismatch: {record.path}")
            temp.replace(target)
            return {"path": record.path, "bytes": size, "sha256": digest.hexdigest(), "cached": False}
        except Exception as exc:
            last = exc
            if attempt + 1 < 5:
                time.sleep(min(2**attempt, 16))
    raise GateError(f"Download failed: {record.path}: {last}")


def download_files(records: Sequence[SourceFile], selection: dict[str, Any], raw_root: Path, output: Path, workers: int) -> None:
    repository = selection["source"]["repository"]
    revision = selection["source"]["revision"]
    results: list[dict[str, Any]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(download_one, item, repository, revision, raw_root): item for item in records}
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps({"downloaded": result["path"], "bytes": result["bytes"]}), flush=True)
    results.sort(key=lambda item: item["path"])
    write_json(output / "DOWNLOAD_MANIFEST.json", {"files": results, "rows_read": False})


def is_liquidation(fill: dict[str, Any]) -> bool:
    return any(fill.get(key) not in (None, False, 0, "", {}, []) for key in ("liquidation", "isLiquidation", "is_liquidation"))


def first_after(series: tuple[np.ndarray, np.ndarray] | None, target: int, tolerance: int = 5000) -> float | None:
    if series is None:
        return None
    times, prices = series
    index = int(np.searchsorted(times, target, side="left"))
    if index >= len(times) or int(times[index]) > target + tolerance:
        return None
    return float(prices[index])


def parse_date(records: Sequence[SourceFile], raw_root: Path, output: Path) -> tuple[list[Observation], dict[str, Any]]:
    date = records[0].date
    role = records[0].role
    dedup: set[tuple[Any, ...]] = set()
    market_raw: dict[str, dict[int, list[Any]]] = {coin: {} for coin in COINS}
    episodes: dict[tuple[str, str, int], list[float]] = {}
    stats: defaultdict[str, int] = defaultdict(int)
    for record in sorted(records, key=lambda item: item.hour):
        parquet = pq.ParquetFile(raw_root / record.path)
        if "events" not in parquet.schema_arrow.names:
            raise GateError(f"Missing events column: {record.path}")
        for batch in parquet.iter_batches(batch_size=25000, columns=["events"]):
            for raw in batch.column(0).to_pylist():
                stats["block_rows"] += 1
                if raw is None:
                    continue
                try:
                    events = orjson.loads(raw)
                except Exception:
                    stats["json_errors"] += 1
                    continue
                if not isinstance(events, list):
                    stats["shape_errors"] += 1
                    continue
                for event in events:
                    stats["event_items"] += 1
                    if not isinstance(event, list) or len(event) != 2 or not isinstance(event[0], str) or not isinstance(event[1], dict):
                        stats["shape_errors"] += 1
                        continue
                    wallet, fill = event[0].lower(), event[1]
                    coin = fill.get("coin")
                    if coin not in COINS or fill.get("crossed") is not True or is_liquidation(fill):
                        continue
                    side = SIDE.get(str(fill.get("side", "")).upper())
                    try:
                        price = float(fill["px"])
                        size = float(fill["sz"])
                        ts = int(fill["time"])
                        tid = int(fill["tid"])
                        oid = int(fill["oid"])
                    except Exception:
                        stats["numeric_errors"] += 1
                        continue
                    if side is None or not (price > 0 and size > 0 and math.isfinite(price) and math.isfinite(size)):
                        stats["numeric_errors"] += 1
                        continue
                    key = (wallet, coin, ts, tid, oid, price, size, side)
                    if key in dedup:
                        stats["duplicates"] += 1
                        continue
                    dedup.add(key)
                    stats["retained"] += 1
                    entry = market_raw[coin].get(tid)
                    if entry is None:
                        market_raw[coin][tid] = [ts, price, None]
                    else:
                        entry[0] = min(int(entry[0]), ts)
                        if entry[2] is None and float(entry[1]) != price:
                            entry[2] = [float(entry[1]), price]
                        elif isinstance(entry[2], list):
                            entry[2].append(price)
                    notional = price * size
                    bin_ms = (ts // 5000) * 5000
                    episode_key = (coin, wallet, bin_ms)
                    current = episodes.get(episode_key)
                    if current is None:
                        episodes[episode_key] = [side * notional, notional, price * notional]
                    else:
                        current[0] += side * notional
                        current[1] += notional
                        current[2] += price * notional
    market: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for coin in COINS:
        rows: list[tuple[int, int, float]] = []
        for tid, (ts, first_price, prices) in market_raw[coin].items():
            price = float(first_price) if prices is None else float(statistics.median(prices))
            rows.append((int(ts), int(tid), price))
        rows.sort(key=lambda item: (item[0], item[1]))
        market[coin] = (
            np.array([item[0] for item in rows], dtype=np.int64),
            np.array([item[2] for item in rows], dtype=np.float64),
        )
    observations: list[Observation] = []
    for (coin, wallet, bin_ms), (signed, absolute, price_weighted) in episodes.items():
        direction = 1 if signed > 0 else -1 if signed < 0 else 0
        if direction == 0 or absolute <= 0:
            continue
        episode_price = price_weighted / absolute
        marks: list[float | None] = []
        for horizon in HORIZONS:
            future = first_after(market.get(coin), bin_ms + 5000 + horizon * 1000)
            if future is None:
                marks.append(None)
            else:
                marks.append(float(np.clip(direction * 10000 * math.log(future / episode_price), -200, 200)))
        if marks[0] is not None or marks[1] is not None:
            observations.append(Observation(date, role, coin, wallet, marks[0], marks[1]))
    result = {
        "date": date,
        "role": role,
        "files": [item.path for item in records],
        "stats": dict(stats),
        "dedup_keys": len(dedup),
        "episode_count": len(episodes),
        "observation_count": len(observations),
        "market_trade_count": {coin: len(market[coin][0]) for coin in COINS},
    }
    write_json(output / f"PARSE_{date}.json", result)
    print(json.dumps({"parsed_date": date, "retained": stats["retained"], "observations": len(observations)}), flush=True)
    return observations, result


def parse_dates(records: Sequence[SourceFile], raw_root: Path, output: Path) -> tuple[dict[str, list[Observation]], dict[str, Any]]:
    grouped: dict[str, list[SourceFile]] = defaultdict(list)
    for item in records:
        grouped[item.date].append(item)
    observations: dict[str, list[Observation]] = {}
    reports: dict[str, Any] = {}
    for date in sorted(grouped):
        observations[date], reports[date] = parse_date(grouped[date], raw_root, output)
    return observations, reports


def mark_for(observation: Observation, horizon: int) -> float | None:
    return observation.mark60 if horizon == 60 else observation.mark300


def candidate_id(values: tuple[int, int, int, float]) -> str:
    horizon, minimum, shrink, tail = values
    return f"h{horizon}-n{minimum}-s{shrink}-q{int(tail*1000):03d}"


def remove_top_positive(values: Sequence[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values, reverse=True)
    remove = int(math.ceil(0.10 * len(ordered)))
    kept_positive_removed = ordered[remove:]
    return float(np.mean(kept_positive_removed)) if kept_positive_removed else None


def correlation(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) < 5 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    result = float(np.corrcoef(np.array(xs), np.array(ys))[0, 1])
    return result if math.isfinite(result) else None


def summarize(records: Sequence[dict[str, Any]]) -> dict[str, Any]:
    correlations = [
        float(item["correlation"])
        for item in records
        if item.get("record_type") == "correlation" and item.get("correlation") is not None
    ]
    wallet_records = [item for item in records if item.get("record_type") == "wallet"]
    signed = [float(item["signed_markout"]) for item in wallet_records]
    top = [float(item["current_markout"]) for item in wallet_records if item["cohort"] == "top"]
    bottom = [float(item["current_markout"]) for item in wallet_records if item["cohort"] == "bottom"]
    return {
        "wallet_day_count": len(wallet_records),
        "top_wallet_day_count": len(top),
        "bottom_wallet_day_count": len(bottom),
        "mean_signed_markout_bp": float(np.mean(signed)) if signed else None,
        "median_signed_markout_bp": float(np.median(signed)) if signed else None,
        "top_10pct_positive_removed_mean_signed_bp": remove_top_positive(signed),
        "mean_top_markout_bp": float(np.mean(top)) if top else None,
        "mean_bottom_markout_bp": float(np.mean(bottom)) if bottom else None,
        "top_minus_bottom_spread_bp": float(np.mean(top) - np.mean(bottom)) if top and bottom else None,
        "mean_score_return_correlation": float(np.mean(correlations)) if correlations else None,
        "correlation_cell_count": len(correlations),
        "dates": sorted({item["date"] for item in wallet_records}),
        "coins": sorted({item["coin"] for item in wallet_records}),
        "date_means": {
            date: float(np.mean([item["signed_markout"] for item in wallet_records if item["date"] == date]))
            for date in sorted({item["date"] for item in wallet_records})
        },
    }


def value(summary: dict[str, Any], key: str) -> float:
    item = summary.get(key)
    return float(item) if item is not None else -math.inf


def development_gate(parts: dict[str, dict[str, Any]]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    for role in ("development_a", "development_b"):
        summary = parts.get(role, {})
        if summary.get("wallet_day_count", 0) < 60:
            failures.append(f"{role}_minimum_wallet_days")
        if len(summary.get("coins", [])) < 2:
            failures.append(f"{role}_minimum_two_coins")
        if value(summary, "mean_signed_markout_bp") <= 0:
            failures.append(f"{role}_mean_signed_positive")
        if value(summary, "top_minus_bottom_spread_bp") < 4:
            failures.append(f"{role}_spread_at_least_4bp")
        if value(summary, "mean_score_return_correlation") <= 0:
            failures.append(f"{role}_correlation_positive")
    combined = parts.get("combined", {})
    if combined.get("wallet_day_count", 0) < 150:
        failures.append("combined_minimum_wallet_days")
    if value(combined, "median_signed_markout_bp") <= 0:
        failures.append("combined_median_signed_positive")
    if value(combined, "top_10pct_positive_removed_mean_signed_bp") <= 0:
        failures.append("combined_top10_removed_positive")
    return not failures, failures


def validation_gate(summary: dict[str, Any]) -> tuple[bool, list[str]]:
    failures: list[str] = []
    if summary.get("wallet_day_count", 0) < 40:
        failures.append("minimum_wallet_days")
    if len(summary.get("coins", [])) < 2:
        failures.append("minimum_two_coins")
    if len(summary.get("dates", [])) < 2:
        failures.append("both_dates_present")
    if value(summary, "mean_signed_markout_bp") <= 0:
        failures.append("mean_signed_positive")
    if value(summary, "median_signed_markout_bp") <= 0:
        failures.append("median_signed_positive")
    if value(summary, "top_minus_bottom_spread_bp") < 4:
        failures.append("spread_at_least_4bp")
    if value(summary, "mean_score_return_correlation") <= 0:
        failures.append("correlation_positive")
    if value(summary, "top_10pct_positive_removed_mean_signed_bp") <= 0:
        failures.append("top10_removed_positive")
    for date, mean in summary.get("date_means", {}).items():
        if mean <= 0:
            failures.append(f"date_{date}_mean_signed_positive")
    return not failures, failures


def evaluate_candidate(
    values: tuple[int, int, int, float],
    dates: Sequence[str],
    observations: dict[str, list[Observation]],
    evaluate_roles: set[str],
    include_snapshots: bool = False,
) -> tuple[dict[str, Any], list[Snapshot]]:
    horizon, minimum, shrink, tail_fraction = values
    sums: defaultdict[tuple[str, str], float] = defaultdict(float)
    counts: defaultdict[tuple[str, str], int] = defaultdict(int)
    output_records: list[dict[str, Any]] = []
    snapshots: list[Snapshot] = []
    for date in dates:
        role = ROLE_BY_DATE[date]
        current_by_coin_wallet: dict[tuple[str, str], list[float]] = defaultdict(list)
        for observation in observations.get(date, []):
            mark = mark_for(observation, horizon)
            if mark is not None:
                current_by_coin_wallet[(observation.coin, observation.wallet)].append(mark)
        for coin in COINS:
            ranked = sorted(
                (
                    (wallet, sums[(coin, wallet)] / (count + shrink), count)
                    for (record_coin, wallet), count in counts.items()
                    if record_coin == coin and count >= minimum
                ),
                key=lambda item: (item[1], item[0]),
            )
            if len(ranked) < 20:
                continue
            tail = max(10, int(math.ceil(tail_fraction * len(ranked))))
            if tail * 2 > len(ranked):
                continue
            top = tuple(item[0] for item in ranked[-tail:])
            bottom = tuple(item[0] for item in ranked[:tail])
            current_means = {
                wallet: float(np.mean(current_by_coin_wallet[(coin, wallet)]))
                for wallet, _score, _count in ranked
                if current_by_coin_wallet.get((coin, wallet))
            }
            if role in evaluate_roles:
                score_values: list[float] = []
                current_values: list[float] = []
                eligible_snapshot: list[tuple[str, float, int, float]] = []
                for wallet, score, count in ranked:
                    current = current_means.get(wallet)
                    if current is None:
                        continue
                    score_values.append(score)
                    current_values.append(current)
                    eligible_snapshot.append((wallet, score, count, current))
                corr = correlation(score_values, current_values)
                if corr is not None:
                    output_records.append({
                        "record_type": "correlation",
                        "date": date,
                        "role": role,
                        "coin": coin,
                        "correlation": corr,
                    })
                top_set, bottom_set = set(top), set(bottom)
                for wallet, current in current_means.items():
                    if wallet in top_set:
                        cohort, signed = "top", current
                    elif wallet in bottom_set:
                        cohort, signed = "bottom", -current
                    else:
                        continue
                    output_records.append({
                        "record_type": "wallet",
                        "date": date,
                        "role": role,
                        "coin": coin,
                        "wallet": wallet,
                        "cohort": cohort,
                        "current_markout": current,
                        "signed_markout": signed,
                    })
                if include_snapshots:
                    observed = set(current_means)
                    snapshots.append(Snapshot(
                        date,
                        role,
                        coin,
                        tuple(eligible_snapshot),
                        tuple(wallet for wallet in top if wallet in observed),
                        tuple(wallet for wallet in bottom if wallet in observed),
                    ))
        for observation in observations.get(date, []):
            mark = mark_for(observation, horizon)
            if mark is not None:
                sums[(observation.coin, observation.wallet)] += mark
                counts[(observation.coin, observation.wallet)] += 1
    parts: dict[str, dict[str, Any]] = {}
    for role in sorted(evaluate_roles):
        parts[role] = summarize([item for item in output_records if item["role"] == role])
    parts["combined"] = summarize(output_records)
    passed, failures = development_gate(parts) if evaluate_roles == DEV_ROLES else validation_gate(parts["combined"])
    result = {
        "candidate_id": candidate_id(values),
        "parameters": {
            "skill_horizon_seconds": horizon,
            "minimum_prior_episodes": minimum,
            "shrinkage_n0": shrink,
            "cohort_tail_fraction": tail_fraction,
        },
        "parameter_tuple": list(values),
        "parts": parts,
        "gate_passed": passed,
        "gate_failures": failures,
    }
    return result, snapshots


def rank_candidates(results: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(results, key=lambda item: (
        0 if item["gate_passed"] else 1,
        -min(
            value(item["parts"].get("development_a", {}), "top_minus_bottom_spread_bp"),
            value(item["parts"].get("development_b", {}), "top_minus_bottom_spread_bp"),
        ),
        -value(item["parts"]["combined"], "mean_signed_markout_bp"),
        -value(item["parts"]["combined"], "top_10pct_positive_removed_mean_signed_bp"),
        -item["parts"]["combined"].get("wallet_day_count", 0),
        item["candidate_id"],
    ))


def activity_matched(
    rng: random.Random,
    eligible: Sequence[tuple[str, float, int, float]],
    targets: Sequence[str],
    excluded: set[str],
) -> set[str]:
    counts = {wallet: count for wallet, _score, count, _current in eligible}
    pools: dict[int, list[str]] = defaultdict(list)
    for wallet, _score, count, _current in eligible:
        if wallet not in excluded:
            pools[int(math.floor(math.log2(max(1, count))))].append(wallet)
    for pool in pools.values():
        pool.sort()
    chosen: set[str] = set()
    for target in sorted(targets, key=lambda wallet: counts.get(wallet, 0)):
        target_bin = int(math.floor(math.log2(max(1, counts.get(target, 1)))))
        options = sorted(pools, key=lambda item: (abs(item - target_bin), item))
        candidate: str | None = None
        for bucket in options:
            available = [wallet for wallet in pools[bucket] if wallet not in chosen]
            if available:
                candidate = available[rng.randrange(len(available))]
                break
        if candidate is None:
            break
        chosen.add(candidate)
    return chosen


def placebo_test(winner: dict[str, Any], snapshots: Sequence[Snapshot], repeats: int = 500) -> dict[str, Any]:
    true_mean = value(winner["parts"]["combined"], "mean_signed_markout_bp")
    placebo_means: list[float] = []
    for repeat in range(repeats):
        rng = random.Random(20260726 + repeat)
        signed: list[float] = []
        for snapshot in snapshots:
            top = activity_matched(rng, snapshot.eligible, snapshot.top, set())
            bottom = activity_matched(rng, snapshot.eligible, snapshot.bottom, top)
            if len(top) != len(snapshot.top) or len(bottom) != len(snapshot.bottom):
                continue
            current = {wallet: mark for wallet, _score, _count, mark in snapshot.eligible}
            signed.extend(current[wallet] for wallet in top if wallet in current)
            signed.extend(-current[wallet] for wallet in bottom if wallet in current)
        placebo_means.append(float(np.mean(signed)) if signed else -math.inf)
    finite = np.array([item for item in placebo_means if math.isfinite(item)], dtype=np.float64)
    p95 = float(np.quantile(finite, 0.95)) if len(finite) else math.inf
    return {
        "repeats": repeats,
        "finite_repeats": int(len(finite)),
        "true_mean_signed_markout_bp": true_mean,
        "placebo_p95_mean_signed_markout_bp": p95,
        "passed": true_mean > p95,
        "means_sha256": hashlib.sha256(json.dumps(placebo_means, separators=(",", ":")).encode()).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--download-workers", type=int, default=4)
    args = parser.parse_args()
    selection = json.loads(args.selection.read_text())
    prereg = json.loads(args.preregistration.read_text())
    if prereg.get("stage") != "PRE_2026_WALLET_SKILL_PERSISTENCE_GATE":
        raise GateError("Unexpected preregistration stage")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    raw_root = args.work_dir / "raw"

    source = resolve_manifest(selection, args.output)
    pre_files = [item for item in source if item.role in PREVALIDATION]
    val_files = [item for item in source if item.role in VALIDATION]
    download_files(pre_files, selection, raw_root, args.output / "prevalidation_download", args.download_workers)
    observations, pre_parse = parse_dates(pre_files, raw_root, args.output / "prevalidation_parse")
    pre_dates = sorted({item.date for item in pre_files})

    results: list[dict[str, Any]] = []
    for horizon in HORIZONS:
        for minimum in MIN_EPISODES:
            for shrink in SHRINK:
                for tail in TAILS:
                    result, _ = evaluate_candidate((horizon, minimum, shrink, tail), pre_dates, observations, DEV_ROLES)
                    results.append(result)
    ranked = rank_candidates(results)
    write_json(args.output / "DEVELOPMENT_CANDIDATES.json", ranked)
    winner = ranked[0]
    winner_detail, snapshots = evaluate_candidate(tuple(winner["parameter_tuple"]), pre_dates, observations, DEV_ROLES, True)
    placebo = {"status": "NOT_RUN_NO_GATE_SURVIVOR", "passed": False}
    development_passed = bool(winner_detail["gate_passed"])
    if development_passed:
        placebo = placebo_test(winner_detail, snapshots, repeats=500)
        development_passed = bool(placebo["passed"])
    write_json(args.output / "DEVELOPMENT_PLACEBO.json", placebo)

    validation_result: dict[str, Any] = {"status": "SEALED_NO_DEVELOPMENT_PASS"}
    validation_passed = False
    val_parse: dict[str, Any] | None = None
    if development_passed:
        download_files(val_files, selection, raw_root, args.output / "validation_download", args.download_workers)
        val_observations, val_parse = parse_dates(val_files, raw_root, args.output / "validation_parse")
        all_observations = {**observations, **val_observations}
        all_dates = sorted({item.date for item in source})
        validation_result, _ = evaluate_candidate(tuple(winner["parameter_tuple"]), all_dates, all_observations, VALIDATION)
        validation_passed = bool(validation_result["gate_passed"])
        write_json(args.output / "VALIDATION_RESULT.json", validation_result)

    report = {
        "claim_id": "CLM-20260726-1040-HL-WALLET-FLOW-001",
        "stage": "PRE_2026_WALLET_SKILL_PERSISTENCE_GATE",
        "source_revision": selection["source"]["revision"],
        "source_manifest_sha256": selection["expected_canonical_manifest_sha256"],
        "prevalidation_file_count": len(pre_files),
        "prevalidation_parse": pre_parse,
        "candidate_count": len(results),
        "development_winner": winner_detail,
        "development_placebo": placebo,
        "development_passed": development_passed,
        "validation_file_count_read": len(val_files) if development_passed else 0,
        "validation_parse": val_parse,
        "validation": validation_result,
        "validation_passed": validation_passed,
        "identity_flow_grid_opened": False,
        "strategy_pnl_computed": False,
        "bybit_execution_opened": False,
        "official_rank_eligible": False,
        "official_2026_opened": False,
        "orders_submitted": False,
        "decision": (
            "PROMOTE_TO_PREREGISTERED_IDENTITY_FLOW_GRID"
            if validation_passed
            else "RETIRE_IDENTITY_SKILL_DEPENDENCY_BEFORE_FLOW_OPTIMIZATION"
        ),
    }
    write_json(args.output / "RUN_REPORT.json", report)
    print(json.dumps(report, sort_keys=True, default=str), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
