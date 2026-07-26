from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
import urllib.parse
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import orjson
import pyarrow.parquet as pq
import requests

TARGET_COINS = ("BTC", "ETH", "SOL", "XRP")
SIDES = {"B", "A"}


class ProbeError(RuntimeError):
    pass


@dataclass(frozen=True)
class ChildOrder:
    wallet: str
    coin: str
    side: str
    oid: str
    time_ms: int
    cloid: str | None


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str), encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def normalize_identifier(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        if not math.isfinite(number) or number == 0:
            return None
        return str(int(number)) if number.is_integer() else str(value)
    text = str(value).strip()
    if not text or text.lower() in {"none", "null", "nan", "0", "0.0"}:
        return None
    return text


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
                headers={"User-Agent": "SMC-ICT-2-LIVE/parent-cadence-probe"},
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


def parse_child_orders(parquet_path: Path) -> tuple[list[ChildOrder], dict[str, Any]]:
    parquet = pq.ParquetFile(parquet_path)
    if "events" not in parquet.schema_arrow.names:
        raise ProbeError("Frozen source lacks events column")
    counters: Counter[str] = Counter()
    cloid_presence_by_coin: Counter[str] = Counter()
    # Collapse partial fills by observable child-order identity.
    collapsed: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for batch in parquet.iter_batches(batch_size=25000, columns=["events"]):
        for raw in batch.column(0).to_pylist():
            counters["block_rows"] += 1
            if raw is None:
                counters["null_rows"] += 1
                continue
            try:
                events = orjson.loads(raw)
            except Exception:
                counters["json_errors"] += 1
                continue
            if not isinstance(events, list):
                counters["non_list_rows"] += 1
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
                coin = fill.get("coin")
                side = str(fill.get("side", "")).upper()
                if coin not in TARGET_COINS or fill.get("crossed") is not True or side not in SIDES:
                    continue
                oid = normalize_identifier(fill.get("oid"))
                try:
                    timestamp = int(fill["time"])
                except Exception:
                    counters["invalid_time"] += 1
                    continue
                if oid is None:
                    counters["invalid_oid"] += 1
                    continue
                wallet = wallet_raw.lower()
                cloid = normalize_identifier(fill.get("cloid"))
                counters["eligible_target_crossed_fills"] += 1
                if cloid is not None:
                    cloid_presence_by_coin[str(coin)] += 1
                key = (wallet, str(coin), side, oid)
                existing = collapsed.get(key)
                if existing is None:
                    collapsed[key] = {"time_ms": timestamp, "cloids": Counter([cloid]) if cloid else Counter()}
                else:
                    existing["time_ms"] = min(int(existing["time_ms"]), timestamp)
                    if cloid is not None:
                        existing["cloids"][cloid] += 1
                    counters["collapsed_partial_fills"] += 1
    child_orders: list[ChildOrder] = []
    ambiguous_cloid_orders = 0
    for (wallet, coin, side, oid), record in collapsed.items():
        cloids: Counter[str] = record["cloids"]
        cloid = None
        if cloids:
            most_common = cloids.most_common()
            cloid = most_common[0][0]
            if len(most_common) > 1:
                ambiguous_cloid_orders += 1
        child_orders.append(ChildOrder(wallet, coin, side, oid, int(record["time_ms"]), cloid))
    child_orders.sort(key=lambda item: (item.wallet, item.coin, item.time_ms, item.oid, item.side))
    return child_orders, {
        "parquet_schema_names": parquet.schema_arrow.names,
        "counters": dict(sorted(counters.items())),
        "normalized_child_order_count": len(child_orders),
        "ambiguous_cloid_child_orders": ambiguous_cloid_orders,
        "child_orders_with_cloid_by_coin": {coin: cloid_presence_by_coin[coin] for coin in TARGET_COINS},
    }


def cloid_test(child_orders: list[ChildOrder], config: dict[str, Any]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(
        lambda: {"times": [], "oids": set(), "sides": Counter()}
    )
    for order in child_orders:
        if order.cloid is None:
            continue
        group = groups[(order.wallet, order.coin, order.cloid)]
        group["times"].append(order.time_ms)
        group["oids"].add(order.oid)
        group["sides"][order.side] += 1
    candidate_groups = 0
    candidate_by_coin: Counter[str] = Counter()
    repeated_distinct_oid_groups = 0
    duration_20_groups = 0
    group_summaries: list[dict[str, Any]] = []
    for (wallet, coin, cloid), group in groups.items():
        times = sorted(group["times"])
        distinct_oids = len(group["oids"])
        duration = (times[-1] - times[0]) / 1000.0 if times else 0.0
        count = len(times)
        purity = max(group["sides"].values()) / count if count else 0.0
        if distinct_oids >= 2:
            repeated_distinct_oid_groups += 1
        if duration >= 20:
            duration_20_groups += 1
        candidate = distinct_oids >= 2 and duration >= 20 and purity >= 0.9
        if candidate:
            candidate_groups += 1
            candidate_by_coin[coin] += 1
        group_summaries.append({
            "coin": coin,
            "child_order_count": count,
            "distinct_oid_count": distinct_oids,
            "duration_seconds": duration,
            "same_side_purity": purity,
            "candidate": candidate,
        })
    group_summaries.sort(
        key=lambda item: (-item["duration_seconds"], -item["distinct_oid_count"], item["coin"])
    )
    gate_contract = config["cloid_parent_test"]["promotion_gate"]
    coins_represented = sum(1 for coin in TARGET_COINS if candidate_by_coin[coin] > 0)
    checks = {
        "minimum_candidate_groups": candidate_groups >= int(gate_contract["minimum_candidate_groups"]),
        "minimum_target_coins_represented": coins_represented >= int(gate_contract["minimum_target_coins_represented"]),
    }
    return {
        "cloid_group_count": len(groups),
        "groups_with_at_least_two_distinct_oids": repeated_distinct_oid_groups,
        "groups_lasting_at_least_20_seconds": duration_20_groups,
        "candidate_parent_groups": candidate_groups,
        "candidate_parent_groups_by_coin": {coin: candidate_by_coin[coin] for coin in TARGET_COINS},
        "candidate_target_coins_represented": coins_represented,
        "top_structural_groups": group_summaries[:50],
        "gate": checks,
        "gate_passed": all(checks.values()),
    }


def in_cadence(gap_ms: int, lower_seconds: int, upper_seconds: int) -> bool:
    return lower_seconds * 1000 <= gap_ms <= upper_seconds * 1000


def cadence_test(child_orders: list[ChildOrder], config: dict[str, Any]) -> dict[str, Any]:
    rule = config["cadence_sequence_test"]
    lower, upper = [int(value) for value in rule["cadence_gap_seconds_inclusive"]]
    file_end_ms = 1753617599999  # frozen 2025-07-27T12:59:59.999Z
    censor_cutoff = file_end_ms - upper * 1000
    grouped: dict[tuple[str, str], list[ChildOrder]] = defaultdict(list)
    for order in child_orders:
        grouped[(order.wallet, order.coin)].append(order)

    detectable_runs = 0
    continued_runs = 0
    detectable_by_coin: Counter[str] = Counter()
    continued_by_coin: Counter[str] = Counter()
    run_length_counts: Counter[int] = Counter()
    detection_times: list[int] = []
    control_anchors = 0
    control_successes = 0
    control_by_coin: Counter[str] = Counter()
    control_success_by_coin: Counter[str] = Counter()

    for (_wallet, coin), orders in grouped.items():
        orders.sort(key=lambda item: (item.time_ms, item.oid, item.side))
        # Maximal consecutive same-side cadence runs.
        run: list[ChildOrder] = []
        for order in orders:
            if not run:
                run = [order]
                continue
            gap = order.time_ms - run[-1].time_ms
            if order.side == run[-1].side and in_cadence(gap, lower, upper):
                run.append(order)
            else:
                if len(run) >= 3 and run[2].time_ms <= censor_cutoff:
                    detectable_runs += 1
                    detectable_by_coin[coin] += 1
                    detection_times.append(run[2].time_ms)
                    run_length_counts[len(run)] += 1
                    if len(run) >= 4:
                        continued_runs += 1
                        continued_by_coin[coin] += 1
                run = [order]
        if len(run) >= 3 and run[2].time_ms <= censor_cutoff:
            detectable_runs += 1
            detectable_by_coin[coin] += 1
            detection_times.append(run[2].time_ms)
            run_length_counts[len(run)] += 1
            if len(run) >= 4:
                continued_runs += 1
                continued_by_coin[coin] += 1

        # Same-side three-order activity controls whose prior two gaps are not both cadence-like.
        for index in range(2, len(orders) - 1):
            previous2, previous1, anchor, future = orders[index - 2], orders[index - 1], orders[index], orders[index + 1]
            if anchor.time_ms > censor_cutoff:
                continue
            if not (previous2.side == previous1.side == anchor.side):
                continue
            gap1 = previous1.time_ms - previous2.time_ms
            gap2 = anchor.time_ms - previous1.time_ms
            if in_cadence(gap1, lower, upper) and in_cadence(gap2, lower, upper):
                continue
            control_anchors += 1
            control_by_coin[coin] += 1
            future_gap = future.time_ms - anchor.time_ms
            if future.side == anchor.side and in_cadence(future_gap, lower, upper):
                control_successes += 1
                control_success_by_coin[coin] += 1

    continuation_rate = continued_runs / detectable_runs if detectable_runs else 0.0
    control_rate = control_successes / control_anchors if control_anchors else 0.0
    absolute_lift = continuation_rate - control_rate
    rate_ratio = continuation_rate / control_rate if control_rate > 0 else (math.inf if continuation_rate > 0 else 0.0)
    coins_with_runs = sum(1 for coin in TARGET_COINS if detectable_by_coin[coin] > 0)
    gate_contract = rule["promotion_gate"]
    checks = {
        "minimum_detectable_runs": detectable_runs >= int(gate_contract["minimum_detectable_runs"]),
        "minimum_continued_runs": continued_runs >= int(gate_contract["minimum_continued_runs"]),
        "minimum_continuation_rate": continuation_rate >= float(gate_contract["minimum_continuation_rate"]),
        "minimum_control_anchors": control_anchors >= int(gate_contract["minimum_control_anchors"]),
        "minimum_absolute_lift_over_control": absolute_lift >= float(gate_contract["minimum_absolute_lift_over_control"]),
        "minimum_rate_ratio_over_control": rate_ratio >= float(gate_contract["minimum_rate_ratio_over_control"]),
        "minimum_target_coins_with_detectable_runs": coins_with_runs >= int(gate_contract["minimum_target_coins_with_detectable_runs"]),
    }
    return {
        "detectable_runs": detectable_runs,
        "continued_runs": continued_runs,
        "continuation_rate": continuation_rate,
        "detectable_runs_by_coin": {coin: detectable_by_coin[coin] for coin in TARGET_COINS},
        "continued_runs_by_coin": {coin: continued_by_coin[coin] for coin in TARGET_COINS},
        "run_length_counts": {str(key): value for key, value in sorted(run_length_counts.items())},
        "detection_time_count": len(detection_times),
        "conditional_control_anchors": control_anchors,
        "conditional_control_successes": control_successes,
        "conditional_control_rate": control_rate,
        "conditional_control_anchors_by_coin": {coin: control_by_coin[coin] for coin in TARGET_COINS},
        "conditional_control_successes_by_coin": {coin: control_success_by_coin[coin] for coin in TARGET_COINS},
        "absolute_lift_over_control": absolute_lift,
        "rate_ratio_over_control": rate_ratio if math.isfinite(rate_ratio) else "Infinity",
        "target_coins_with_detectable_runs": coins_with_runs,
        "gate": checks,
        "gate_passed": all(checks.values()),
    }


def self_test() -> None:
    assert normalize_identifier(None) is None
    assert normalize_identifier(0) is None
    assert normalize_identifier("abc") == "abc"
    base = 1753614000000
    orders = [
        ChildOrder("w", "BTC", "B", str(index), base + offset * 1000, "parent")
        for index, offset in enumerate((0, 30, 60, 90), start=1)
    ]
    config = {
        "cadence_sequence_test": {
            "cadence_gap_seconds_inclusive": [20, 40],
            "promotion_gate": {
                "minimum_detectable_runs": 1,
                "minimum_continued_runs": 1,
                "minimum_continuation_rate": 0.5,
                "minimum_control_anchors": 0,
                "minimum_absolute_lift_over_control": 0.2,
                "minimum_rate_ratio_over_control": 2.0,
                "minimum_target_coins_with_detectable_runs": 1,
            },
        }
    }
    result = cadence_test(orders, config)
    assert result["detectable_runs"] == 1
    assert result["continued_runs"] == 1
    assert result["continuation_rate"] == 1.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preregistration", type=Path)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        print("parent cadence structural self-test passed")
        return 0
    if not args.preregistration or not args.work_dir or not args.output:
        parser.error("--preregistration, --work-dir and --output are required")
    config = json.loads(args.preregistration.read_text(encoding="utf-8"))
    if config.get("stage") != "PRE_2026_PARENT_ORDER_CADENCE_STRUCTURE_GATE":
        raise ProbeError("Unexpected preregistration stage")
    args.work_dir.mkdir(parents=True, exist_ok=True)
    args.output.mkdir(parents=True, exist_ok=True)
    target = args.work_dir / Path(config["source"]["path"]).name
    download = download_exact(config, target)
    child_orders, parse_report = parse_child_orders(target)
    cloid = cloid_test(child_orders, config)
    cadence = cadence_test(child_orders, config)
    passed = bool(cloid["gate_passed"] or cadence["gate_passed"])
    report = {
        "claim_id": config["claim_id"],
        "stage": config["stage"],
        "source": config["source"],
        "download": download,
        "parse": parse_report,
        "cloid_parent_test": cloid,
        "cadence_sequence_test": cadence,
        "promotion_gate_passed": passed,
        "decision": "PROMOTE_TO_CAUSAL_PARENT_ORDER_PRICE_SCREEN" if passed else "RETIRE_DIRECT_PARENT_ORDER_CONTINUATION_FOR_THIS_SOURCE",
        "price_values_accessed": False,
        "size_values_accessed": False,
        "price_or_size_values_serialized": False,
        "return_or_markout_computed": False,
        "strategy_pnl_computed": False,
        "bybit_execution_opened": False,
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    write_json(args.output / "PARENT_CADENCE_STRUCTURE_REPORT.json", report)
    print(json.dumps({
        "normalized_child_orders": parse_report["normalized_child_order_count"],
        "cloid_candidate_groups": cloid["candidate_parent_groups"],
        "detectable_runs": cadence["detectable_runs"],
        "continued_runs": cadence["continued_runs"],
        "continuation_rate": cadence["continuation_rate"],
        "control_rate": cadence["conditional_control_rate"],
        "absolute_lift": cadence["absolute_lift_over_control"],
        "rate_ratio": cadence["rate_ratio_over_control"],
        "promotion_gate_passed": passed,
        "decision": report["decision"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
