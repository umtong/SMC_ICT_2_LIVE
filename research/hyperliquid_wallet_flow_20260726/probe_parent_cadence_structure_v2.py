from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any

import probe_parent_cadence_structure as base


def iso8601_epoch_ms(value: str) -> int:
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        raise base.ProbeError(f"Timestamp must be timezone-aware: {value}")
    utc = parsed.astimezone(timezone.utc)
    epoch = datetime(1970, 1, 1, tzinfo=timezone.utc)
    delta = utc - epoch
    return delta.days * 86_400_000 + delta.seconds * 1_000 + delta.microseconds // 1_000


def cadence_test(
    child_orders: list[base.ChildOrder], config: dict[str, Any]
) -> dict[str, Any]:
    rule = config["cadence_sequence_test"]
    lower, upper = [int(value) for value in rule["cadence_gap_seconds_inclusive"]]
    if lower < 0 or upper < lower:
        raise base.ProbeError("Invalid cadence window")
    source_interval = config.get("source", {}).get("utc_interval")
    if not isinstance(source_interval, list) or len(source_interval) != 2:
        raise base.ProbeError("Frozen source.utc_interval is required")
    file_end_ms = iso8601_epoch_ms(str(source_interval[1]))
    censor_cutoff = file_end_ms - upper * 1_000

    grouped: dict[tuple[str, str], list[base.ChildOrder]] = defaultdict(list)
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

        run: list[base.ChildOrder] = []
        for order in orders:
            if not run:
                run = [order]
                continue
            gap = order.time_ms - run[-1].time_ms
            if order.side == run[-1].side and base.in_cadence(gap, lower, upper):
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

        for index in range(2, len(orders) - 1):
            previous2, previous1, anchor, future = (
                orders[index - 2],
                orders[index - 1],
                orders[index],
                orders[index + 1],
            )
            if anchor.time_ms > censor_cutoff:
                continue
            if not (previous2.side == previous1.side == anchor.side):
                continue
            gap1 = previous1.time_ms - previous2.time_ms
            gap2 = anchor.time_ms - previous1.time_ms
            if base.in_cadence(gap1, lower, upper) and base.in_cadence(
                gap2, lower, upper
            ):
                continue
            control_anchors += 1
            control_by_coin[coin] += 1
            future_gap = future.time_ms - anchor.time_ms
            if future.side == anchor.side and base.in_cadence(
                future_gap, lower, upper
            ):
                control_successes += 1
                control_success_by_coin[coin] += 1

    continuation_rate = continued_runs / detectable_runs if detectable_runs else 0.0
    control_rate = control_successes / control_anchors if control_anchors else 0.0
    absolute_lift = continuation_rate - control_rate
    rate_ratio = (
        continuation_rate / control_rate
        if control_rate > 0
        else (math.inf if continuation_rate > 0 else 0.0)
    )
    coins_with_runs = sum(
        1 for coin in base.TARGET_COINS if detectable_by_coin[coin] > 0
    )
    gate_contract = rule["promotion_gate"]
    checks = {
        "minimum_detectable_runs": detectable_runs
        >= int(gate_contract["minimum_detectable_runs"]),
        "minimum_continued_runs": continued_runs
        >= int(gate_contract["minimum_continued_runs"]),
        "minimum_continuation_rate": continuation_rate
        >= float(gate_contract["minimum_continuation_rate"]),
        "minimum_control_anchors": control_anchors
        >= int(gate_contract["minimum_control_anchors"]),
        "minimum_absolute_lift_over_control": absolute_lift
        >= float(gate_contract["minimum_absolute_lift_over_control"]),
        "minimum_rate_ratio_over_control": rate_ratio
        >= float(gate_contract["minimum_rate_ratio_over_control"]),
        "minimum_target_coins_with_detectable_runs": coins_with_runs
        >= int(gate_contract["minimum_target_coins_with_detectable_runs"]),
    }
    return {
        "file_end_epoch_ms": file_end_ms,
        "right_censor_cutoff_epoch_ms": censor_cutoff,
        "detectable_runs": detectable_runs,
        "continued_runs": continued_runs,
        "continuation_rate": continuation_rate,
        "detectable_runs_by_coin": {
            coin: detectable_by_coin[coin] for coin in base.TARGET_COINS
        },
        "continued_runs_by_coin": {
            coin: continued_by_coin[coin] for coin in base.TARGET_COINS
        },
        "run_length_counts": {
            str(key): value for key, value in sorted(run_length_counts.items())
        },
        "detection_time_count": len(detection_times),
        "conditional_control_anchors": control_anchors,
        "conditional_control_successes": control_successes,
        "conditional_control_rate": control_rate,
        "conditional_control_anchors_by_coin": {
            coin: control_by_coin[coin] for coin in base.TARGET_COINS
        },
        "conditional_control_successes_by_coin": {
            coin: control_success_by_coin[coin] for coin in base.TARGET_COINS
        },
        "absolute_lift_over_control": absolute_lift,
        "rate_ratio_over_control": (
            rate_ratio if math.isfinite(rate_ratio) else "Infinity"
        ),
        "target_coins_with_detectable_runs": coins_with_runs,
        "gate": checks,
        "gate_passed": all(checks.values()),
    }


def self_test() -> None:
    assert iso8601_epoch_ms("2025-07-27T12:59:59.999Z") == 1_753_621_199_999
    base_ms = iso8601_epoch_ms("2025-07-27T12:00:00Z")
    orders = [
        base.ChildOrder("w", "BTC", "B", str(index), base_ms + offset * 1_000, "p")
        for index, offset in enumerate((0, 30, 60, 90), start=1)
    ]
    config = {
        "source": {
            "utc_interval": [
                "2025-07-27T12:00:00Z",
                "2025-07-27T12:59:59.999Z",
            ]
        },
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
        },
    }
    result = cadence_test(orders, config)
    assert result["detectable_runs"] == 1
    assert result["continued_runs"] == 1
    assert result["continuation_rate"] == 1.0
    assert result["file_end_epoch_ms"] == 1_753_621_199_999

    censored_start = result["right_censor_cutoff_epoch_ms"] - 59_000
    censored_orders = [
        base.ChildOrder(
            "c",
            "ETH",
            "A",
            str(index),
            censored_start + offset * 1_000,
            None,
        )
        for index, offset in enumerate((0, 30, 60), start=1)
    ]
    censored = cadence_test(censored_orders, config)
    assert censored["detectable_runs"] == 0


base.cadence_test = cadence_test
base.self_test = self_test


if __name__ == "__main__":
    raise SystemExit(base.main())
