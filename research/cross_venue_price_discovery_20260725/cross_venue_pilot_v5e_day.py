from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import cross_venue_pilot as v1
import cross_venue_pilot_v5d as v5d
import cross_venue_signals_v5d as signals


def semantic_group_key(config: v1.Config) -> tuple[Any, ...]:
    """Return the frozen gross-path identity available before market outcomes."""
    return (
        signals.signal_signature(config),
        int(config.latency_ms),
        int(config.hold_ms),
        float(config.stop_spreads),
    )


def partition_configs(
    shard_count: int,
) -> tuple[list[v1.Config], list[list[v1.Config]], list[int]]:
    if shard_count < 1:
        raise ValueError("shard_count must be positive")
    configs = list(v1.pilot_grid())
    original_order = {config.config_id: index for index, config in enumerate(configs)}
    groups: dict[tuple[Any, ...], list[v1.Config]] = {}
    for config in configs:
        groups.setdefault(semantic_group_key(config), []).append(config)

    def encoded_key(item: tuple[tuple[Any, ...], list[v1.Config]]) -> str:
        return json.dumps(item[0], sort_keys=True, separators=(",", ":"), default=str)

    ordered_groups = sorted(groups.items(), key=encoded_key)
    shards: list[list[v1.Config]] = [[] for _ in range(shard_count)]
    group_counts = [0 for _ in range(shard_count)]
    for number, (_, members) in enumerate(ordered_groups):
        shard_index = number % shard_count
        shards[shard_index].extend(members)
        group_counts[shard_index] += 1
    for shard in shards:
        shard.sort(key=lambda config: original_order[config.config_id])

    ids = [config.config_id for shard in shards for config in shard]
    if len(ids) != len(configs) or len(set(ids)) != len(configs):
        raise AssertionError("semantic config partition is not an exact disjoint cover")
    return configs, shards, group_counts


def run(
    day: str,
    output: Path,
    cache: Path,
    shard_index: int,
    shard_count: int,
) -> dict:
    if day not in v1.PILOT_DAYS:
        raise ValueError(f"day is not in the frozen pilot set: {day}")
    full_configs, shards, group_counts = partition_configs(shard_count)
    if shard_index < 0 or shard_index >= shard_count:
        raise ValueError(f"shard_index must be in [0, {shard_count})")
    selected = shards[shard_index]
    if not selected:
        raise ValueError(f"empty config shard {shard_index}/{shard_count}")

    original_grid = v1.pilot_grid
    v1.pilot_grid = lambda: list(selected)
    try:
        result = v5d.run(output, cache, (day,))
    finally:
        v1.pilot_grid = original_grid

    selected_ids = [config.config_id for config in selected]
    result.update({
        "parallel_shard_day": day,
        "config_shard_index": shard_index,
        "config_shard_count": shard_count,
        "total_configurations": len(full_configs),
        "total_semantic_execution_paths": sum(group_counts),
        "shard_semantic_execution_paths": group_counts[shard_index],
        "shard_config_ids_sha256": hashlib.sha256(
            "\n".join(selected_ids).encode()
        ).hexdigest(),
        "parallel_shard_contract": (
            "one frozen UTC sample day and a disjoint set of complete semantic "
            "signal/execution groups; every registered config ID is evaluated once "
            "per day and no global slot can cross either a config or date boundary"
        ),
        "performance_contract": (
            f"this shard preserves {len(selected)} registered config IDs in "
            f"{group_counts[shard_index]} complete semantic gross-path groups; "
            "all dates, signals, fills, stops, exits, costs and account rules are unchanged"
        ),
    })
    path = output / "PILOT_RESULT.json"
    path.write_text(
        json.dumps(result, indent=2, sort_keys=True, default=str) + "\n",
        encoding="utf-8",
    )
    (output / "PILOT_RESULT.sha256").write_text(
        f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n",
        encoding="utf-8",
    )
    return result


def self_test() -> None:
    configs, shards, group_counts = partition_configs(4)
    assert len(configs) == 768
    assert sum(group_counts) == 288
    assert max(group_counts) - min(group_counts) <= 1
    assert {config.config_id for shard in shards for config in shard} == {
        config.config_id for config in configs
    }
    for shard in shards:
        keys = [semantic_group_key(config) for config in shard]
        unique = set(keys)
        for key in unique:
            members = [
                config.config_id
                for config in configs
                if semantic_group_key(config) == key
            ]
            selected = [
                config.config_id
                for config in shard
                if semantic_group_key(config) == key
            ]
            assert selected == members
    print("V5D_SEMANTIC_CONFIG_SHARD_SELF_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--day", required=True)
    run_parser.add_argument("--shard-index", type=int, required=True)
    run_parser.add_argument("--shard-count", type=int, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--cache", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "self-test":
        self_test()
        return 0
    result = run(
        args.day,
        args.output,
        args.cache,
        args.shard_index,
        args.shard_count,
    )
    print(json.dumps({
        "day": args.day,
        "config_shard_index": args.shard_index,
        "config_shard_count": args.shard_count,
        "causal_engine_version": result["causal_engine_version"],
        "configurations_in_shard": result["configurations"],
        "semantic_paths_in_shard": result["shard_semantic_execution_paths"],
        "fatal_edge_pass_count_on_shard": result["fatal_edge_pass_count"],
        "orders_submitted": result["orders_submitted"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
