from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
import time
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import orjson
import pyarrow.parquet as pq
import requests

TARGET_COINS = ("BTC", "ETH", "SOL", "XRP")
TWAP_ALIASES = ("twapId", "twap_id")
SIDE_VALUES = {"B", "A"}


class ProbeError(RuntimeError):
    pass


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_exact(config: dict[str, Any], target: Path) -> dict[str, Any]:
    source = config["source"]
    expected_size = int(source["bytes"])
    expected_sha = str(source["lfs_sha256"])
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and target.stat().st_size == expected_size and sha256_file(target) == expected_sha:
        return {"cached": True, "bytes": expected_size, "sha256": expected_sha}
    temp = target.with_suffix(target.suffix + ".part")
    last: Exception | None = None
    for attempt in range(5):
        if temp.exists():
            temp.unlink()
        try:
            url = (
                f"https://huggingface.co/datasets/{source['repository']}/resolve/"
                f"{urllib.parse.quote(source['revision'], safe='')}/"
                f"{urllib.parse.quote(source['path'], safe='/')}?download=true"
            )
            digest = hashlib.sha256()
            size = 0
            with requests.get(
                url,
                stream=True,
                timeout=(30, 300),
                headers={"User-Agent": "SMC-ICT-2-LIVE/twap-schema-probe"},
            ) as response:
                response.raise_for_status()
                with temp.open("wb") as handle:
                    for chunk in response.iter_content(8 * 1024 * 1024):
                        if not chunk:
                            continue
                        handle.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
            actual_sha = digest.hexdigest()
            if size != expected_size or actual_sha != expected_sha:
                raise ProbeError(
                    f"Source mismatch: size={size}/{expected_size} sha={actual_sha}/{expected_sha}"
                )
            temp.replace(target)
            return {"cached": False, "bytes": size, "sha256": actual_sha}
        except Exception as exc:
            last = exc
            if attempt + 1 < 5:
                time.sleep(min(2**attempt, 16))
    raise ProbeError(f"Download failed: {last}")


def normalize_identifier(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)) or float(value) == 0:
            return None
        return str(int(value)) if float(value).is_integer() else str(value)
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "0", "0.0"}:
        return None
    return text


def quantiles(values: list[float]) -> dict[str, float | None]:
    if not values:
        return {"min": None, "p25": None, "median": None, "p75": None, "p90": None, "p99": None, "max": None}
    ordered = sorted(float(value) for value in values)
    def q(probability: float) -> float:
        if len(ordered) == 1:
            return ordered[0]
        position = probability * (len(ordered) - 1)
        lower = int(math.floor(position))
        upper = int(math.ceil(position))
        if lower == upper:
            return ordered[lower]
        weight = position - lower
        return ordered[lower] * (1 - weight) + ordered[upper] * weight
    return {
        "min": ordered[0],
        "p25": q(0.25),
        "median": q(0.50),
        "p75": q(0.75),
        "p90": q(0.90),
        "p99": q(0.99),
        "max": ordered[-1],
    }


def new_group() -> dict[str, Any]:
    return {
        "count": 0,
        "min_time": None,
        "max_time": None,
        "times": [],
        "side_counts": Counter(),
        "oids": set(),
    }


def add_group(group: dict[str, Any], timestamp: int, side: str, oid: str | None) -> None:
    group["count"] += 1
    group["min_time"] = timestamp if group["min_time"] is None else min(group["min_time"], timestamp)
    group["max_time"] = timestamp if group["max_time"] is None else max(group["max_time"], timestamp)
    group["times"].append(timestamp)
    group["side_counts"][side] += 1
    if oid is not None:
        group["oids"].add(oid)


def summarize_groups(groups: dict[tuple[str, ...], dict[str, Any]]) -> dict[str, Any]:
    fill_counts: list[float] = []
    durations: list[float] = []
    positive_intervals: list[float] = []
    purities: list[float] = []
    unique_oid_counts: list[float] = []
    thresholds = {2: 0, 3: 0, 5: 0, 10: 0}
    duration_thresholds = {30: 0, 60: 0, 120: 0, 300: 0}
    purity_09 = 0
    for group in groups.values():
        count = int(group["count"])
        duration = max(0.0, (int(group["max_time"]) - int(group["min_time"])) / 1000.0)
        purity = max(group["side_counts"].values()) / count if count else 0.0
        fill_counts.append(float(count))
        durations.append(duration)
        purities.append(purity)
        unique_oid_counts.append(float(len(group["oids"])))
        for threshold in thresholds:
            if count >= threshold:
                thresholds[threshold] += 1
        for threshold in duration_thresholds:
            if duration >= threshold:
                duration_thresholds[threshold] += 1
        if purity >= 0.9:
            purity_09 += 1
        ordered_times = sorted(set(int(value) for value in group["times"]))
        positive_intervals.extend(
            (right - left) / 1000.0
            for left, right in zip(ordered_times, ordered_times[1:])
            if right > left
        )
    return {
        "group_count": len(groups),
        "groups_with_at_least_n_fills": {str(key): value for key, value in thresholds.items()},
        "groups_lasting_at_least_seconds": {str(key): value for key, value in duration_thresholds.items()},
        "groups_with_same_side_purity_at_least_0_9": purity_09,
        "fill_count_distribution": quantiles(fill_counts),
        "duration_seconds_distribution": quantiles(durations),
        "positive_interarrival_seconds_distribution": quantiles(positive_intervals),
        "same_side_purity_distribution": quantiles(purities),
        "unique_oid_count_distribution": quantiles(unique_oid_counts),
    }


def parse(config: dict[str, Any], parquet_path: Path) -> dict[str, Any]:
    parquet = pq.ParquetFile(parquet_path)
    if "events" not in parquet.schema_arrow.names:
        raise ProbeError("Frozen file lacks events column")

    counters: Counter[str] = Counter()
    field_frequencies: Counter[str] = Counter()
    eligible_by_coin: Counter[str] = Counter()
    explicit_by_coin: Counter[str] = Counter()
    alias_frequencies: Counter[str] = Counter()
    twap_groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(new_group)
    oid_groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(new_group)
    explicit_ids_by_coin: dict[str, set[str]] = defaultdict(set)

    for batch in parquet.iter_batches(batch_size=25000, columns=["events"]):
        for raw in batch.column(0).to_pylist():
            counters["block_rows"] += 1
            if raw is None:
                counters["null_event_rows"] += 1
                continue
            try:
                events = orjson.loads(raw)
            except Exception:
                counters["json_errors"] += 1
                continue
            if not isinstance(events, list):
                counters["non_list_event_rows"] += 1
                continue
            for event in events:
                counters["event_items"] += 1
                if not isinstance(event, list) or len(event) != 2:
                    counters["malformed_event_shape"] += 1
                    continue
                wallet_raw, fill = event
                if not isinstance(wallet_raw, str) or not isinstance(fill, dict):
                    counters["malformed_event_values"] += 1
                    continue
                for key in fill.keys():
                    field_frequencies[str(key)] += 1
                coin = fill.get("coin")
                if coin not in TARGET_COINS or fill.get("crossed") is not True:
                    continue
                side = str(fill.get("side", "")).upper()
                if side not in SIDE_VALUES:
                    counters["unrecognized_side"] += 1
                    continue
                try:
                    timestamp = int(fill["time"])
                except Exception:
                    counters["invalid_time"] += 1
                    continue
                wallet = wallet_raw.lower()
                oid = normalize_identifier(fill.get("oid"))
                eligible_by_coin[str(coin)] += 1
                counters["eligible_target_crossed_fills"] += 1
                if oid is not None:
                    add_group(oid_groups[(wallet, str(coin), oid)], timestamp, side, oid)

                explicit_id = None
                for alias in TWAP_ALIASES:
                    if alias in fill:
                        alias_frequencies[alias] += 1
                        candidate = normalize_identifier(fill.get(alias))
                        if candidate is not None and explicit_id is None:
                            explicit_id = candidate
                if explicit_id is None:
                    continue
                counters["fills_with_explicit_twap_id"] += 1
                explicit_by_coin[str(coin)] += 1
                explicit_ids_by_coin[str(coin)].add(explicit_id)
                add_group(twap_groups[(wallet, str(coin), explicit_id)], timestamp, side, oid)

    twap_summary = summarize_groups(twap_groups)
    oid_summary = summarize_groups(oid_groups)
    gate_contract = config["promotion_gate"]
    coins_with_explicit = sum(1 for coin in TARGET_COINS if explicit_by_coin[coin] > 0)
    gate_checks = {
        "minimum_distinct_explicit_twap_groups": twap_summary["group_count"] >= int(gate_contract["minimum_distinct_explicit_twap_groups"]),
        "minimum_groups_with_at_least_3_fills": twap_summary["groups_with_at_least_n_fills"]["3"] >= int(gate_contract["minimum_groups_with_at_least_3_fills"]),
        "minimum_groups_lasting_at_least_30_seconds": twap_summary["groups_lasting_at_least_seconds"]["30"] >= int(gate_contract["minimum_groups_lasting_at_least_30_seconds"]),
        "minimum_groups_with_same_side_purity_at_least_0_9": twap_summary["groups_with_same_side_purity_at_least_0_9"] >= int(gate_contract["minimum_groups_with_same_side_purity_at_least_0_9"]),
        "required_target_coins_with_any_explicit_twap": coins_with_explicit >= int(gate_contract["required_target_coins_with_any_explicit_twap"]),
        "all_prices_and_returns_unopened": True,
    }
    return {
        "claim_id": config["claim_id"],
        "stage": config["stage"],
        "source": config["source"],
        "parquet_schema_names": parquet.schema_arrow.names,
        "fill_object_field_frequencies": dict(sorted(field_frequencies.items())),
        "twap_identifier_alias_frequencies": dict(sorted(alias_frequencies.items())),
        "counters": dict(sorted(counters.items())),
        "eligible_target_crossed_fills_by_coin": {coin: eligible_by_coin[coin] for coin in TARGET_COINS},
        "fills_with_explicit_twap_id_by_coin": {coin: explicit_by_coin[coin] for coin in TARGET_COINS},
        "distinct_explicit_twap_ids_by_coin": {coin: len(explicit_ids_by_coin[coin]) for coin in TARGET_COINS},
        "target_coins_with_any_explicit_twap": coins_with_explicit,
        "explicit_twap_groups": twap_summary,
        "repeated_oid_groups_non_promoting_fallback": oid_summary,
        "promotion_gate": gate_checks,
        "promotion_gate_passed": all(gate_checks.values()),
        "decision": "PROMOTE_TO_CAUSAL_TWAP_CONTINUATION_PREREGISTRATION" if all(gate_checks.values()) else "RETIRE_EXPLICIT_TWAP_CONTINUATION_FOR_THIS_SOURCE",
        "price_values_accessed": False,
        "price_or_size_values_serialized": False,
        "return_or_markout_computed": False,
        "strategy_pnl_computed": False,
        "bybit_execution_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }


def self_test() -> None:
    assert normalize_identifier(None) is None
    assert normalize_identifier(0) is None
    assert normalize_identifier("0") is None
    assert normalize_identifier(7) == "7"
    groups: dict[tuple[str, ...], dict[str, Any]] = defaultdict(new_group)
    add_group(groups[("a",)], 1000, "B", "1")
    add_group(groups[("a",)], 31000, "B", "2")
    add_group(groups[("a",)], 61000, "B", "3")
    summary = summarize_groups(groups)
    assert summary["group_count"] == 1
    assert summary["groups_with_at_least_n_fills"]["3"] == 1
    assert summary["groups_lasting_at_least_seconds"]["30"] == 1
    assert summary["groups_with_same_side_purity_at_least_0_9"] == 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("twap schema probe self-test passed")
        return 0
    if not args.preregistration or not args.work_dir or not args.output:
        parser.error("--preregistration, --work-dir and --output are required")
    config = json.loads(args.preregistration.read_text(encoding="utf-8"))
    if config.get("stage") != "PRE_2026_TWAP_IDENTIFIER_SCHEMA_PROBE":
        raise ProbeError("Unexpected preregistration stage")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.work_dir / Path(config["source"]["path"]).name
    download = download_exact(config, target)
    report = parse(config, target)
    report["download"] = download
    write_json(args.output / "TWAP_SCHEMA_REPORT.json", report)
    print(json.dumps({
        "explicit_twap_group_count": report["explicit_twap_groups"]["group_count"],
        "groups_with_at_least_3_fills": report["explicit_twap_groups"]["groups_with_at_least_n_fills"]["3"],
        "groups_lasting_at_least_30_seconds": report["explicit_twap_groups"]["groups_lasting_at_least_seconds"]["30"],
        "target_coins_with_any_explicit_twap": report["target_coins_with_any_explicit_twap"],
        "promotion_gate_passed": report["promotion_gate_passed"],
        "decision": report["decision"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
