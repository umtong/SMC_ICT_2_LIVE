from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

import strict_guard as strict

CORRECTION_ID = "CORRECTION-20260727-ML-STABLECOIN-SIMULTANEOUS-AVAILABILITY-003"
ENGINE = "ML_STABLECOIN_ISSUANCE_FIRST_PASSAGE_STRICT_CAUSAL_V4"
_ORIGINAL_BUILD_ROWS = strict.strict_build_rows


def _strict_prior_features(events: pd.DataFrame, delay: int) -> pd.DataFrame:
    """Compute source-history features from timestamps strictly earlier than each event.

    Events with an identical finalized availability second are simultaneous. None may
    enter another event's prior-state features merely because its row or log index was
    encountered first.
    """

    if delay not in (12, 64):
        raise ValueError("delay must be 12 or 64")
    event_time_col = f"available_timestamp_{delay}"
    required = {"event_id", "direction", "amount_usd", event_time_col}
    missing = sorted(required.difference(events.columns))
    if missing:
        raise ValueError(f"missing event columns: {missing}")
    if events["event_id"].astype(str).duplicated().any():
        duplicates = sorted(
            events.loc[events["event_id"].astype(str).duplicated(False), "event_id"]
            .astype(str)
            .unique()
            .tolist()
        )
        raise ValueError(f"duplicate event_id values: {duplicates[:10]}")

    ordered = events.loc[:, ["event_id", "direction", "amount_usd", event_time_col]].copy()
    ordered["event_id"] = ordered["event_id"].astype(str)
    ordered[event_time_col] = pd.to_numeric(
        ordered[event_time_col], errors="raise"
    ).astype(np.int64)
    ordered["amount_usd"] = pd.to_numeric(
        ordered["amount_usd"], errors="raise"
    ).astype(float)
    amounts_raw = ordered["amount_usd"].to_numpy(float)
    if (~np.isfinite(amounts_raw)).any() or (ordered["amount_usd"] < 0).any():
        raise ValueError("amount_usd must be finite and non-negative")
    directions = ordered["direction"].astype(str).str.upper()
    ordered["sign"] = np.where(
        directions.eq("MINT"),
        1.0,
        np.where(directions.eq("BURN"), -1.0, np.nan),
    )
    if ordered["sign"].isna().any():
        bad = sorted(ordered.loc[ordered["sign"].isna(), "direction"].astype(str).unique())
        raise ValueError(f"unsupported direction values: {bad}")

    ordered = ordered.sort_values(
        [event_time_col, "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    times = ordered[event_time_col].to_numpy(np.int64)
    amounts = ordered["amount_usd"].to_numpy(float)
    signs = ordered["sign"].to_numpy(float)

    prefix_mint = np.concatenate(
        ([0.0], np.cumsum(np.where(signs > 0, amounts, 0.0)))
    )
    prefix_burn = np.concatenate(
        ([0.0], np.cumsum(np.where(signs < 0, amounts, 0.0)))
    )
    prefix_net = np.concatenate(([0.0], np.cumsum(amounts * signs)))

    prior_same = np.zeros(len(ordered), dtype=float)
    prior_net = np.zeros(len(ordered), dtype=float)
    for index, timestamp in enumerate(times):
        # side='left' at the right edge excludes every event with the same
        # availability second, irrespective of row or log ordering.
        end = int(np.searchsorted(times, timestamp, side="left"))
        start_60m = int(np.searchsorted(times, timestamp - 3_600, side="left"))
        start_24h = int(np.searchsorted(times, timestamp - 86_400, side="left"))
        prefix = prefix_mint if signs[index] > 0 else prefix_burn
        prior_same[index] = float(prefix[end] - prefix[start_60m])
        prior_net[index] = float(prefix_net[end] - prefix_net[start_24h])

    output = pd.DataFrame(
        {
            "event_id": ordered["event_id"],
            "prior_60m_same_direction_event_notional": np.log1p(
                np.maximum(prior_same, 0.0)
            ),
            "prior_24h_net_issuance": np.where(
                prior_net == 0.0,
                0.0,
                np.sign(prior_net) * np.log1p(np.abs(prior_net)),
            ),
        }
    )
    return output.set_index("event_id")


def simultaneous_invariant_build_rows(
    events: pd.DataFrame,
    bars: dict[str, pd.DataFrame],
    funding: dict[str, pd.DataFrame],
    delay: int = 12,
) -> pd.DataFrame:
    event_time_col = f"available_timestamp_{delay}"
    ordered = events.copy()
    ordered["event_id"] = ordered["event_id"].astype(str)
    ordered = ordered.sort_values(
        [event_time_col, "event_id"], kind="mergesort"
    ).reset_index(drop=True)
    rows = _ORIGINAL_BUILD_ROWS(ordered, bars, funding, delay)
    if rows.empty:
        return rows
    prior = _strict_prior_features(ordered, delay)
    event_ids = rows["event_id"].astype(str)
    for column in (
        "prior_60m_same_direction_event_notional",
        "prior_24h_net_issuance",
    ):
        values = event_ids.map(prior[column])
        if values.isna().any():
            missing = sorted(event_ids.loc[values.isna()].unique().tolist())
            raise AssertionError(
                f"prior feature mapping missing event ids: {missing[:10]}"
            )
        rows[column] = values.to_numpy(float)
    return rows.sort_values(
        ["decision_ms", "event_id", "symbol"], kind="mergesort"
    ).reset_index(drop=True)


def _install_patch() -> None:
    strict.strict_build_rows = simultaneous_invariant_build_rows
    strict.causal.build_rows = simultaneous_invariant_build_rows


def _augment_result(output: Path) -> dict[str, Any]:
    guard = strict.audit_result(output)
    guard.update(
        {
            "simultaneous_availability_correction_id": CORRECTION_ID,
            "simultaneous_availability_second_excluded_from_prior_features": True,
            "same_timestamp_row_permutation_invariant": True,
        }
    )
    for name in ("RESULT.json", "FULL_RESULT.json"):
        path = output / name
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["engine"] = ENGINE
        payload["strict_causal_guard"] = guard
        strict._write_json(path, payload)
    strict._refresh_hashes(output)
    return guard


def self_test() -> None:
    strict.self_test()
    base_time = int(pd.Timestamp("2021-01-01 03:10:30", tz="UTC").timestamp())
    events = pd.DataFrame(
        [
            {
                "event_id": "prior-mint",
                "direction": "MINT",
                "amount_usd": 10_000_000.0,
                "available_timestamp_12": base_time - 1_800,
                "available_timestamp_64": base_time - 1_176,
            },
            {
                "event_id": "same-mint-a",
                "direction": "MINT",
                "amount_usd": 20_000_000.0,
                "available_timestamp_12": base_time,
                "available_timestamp_64": base_time + 624,
            },
            {
                "event_id": "same-burn",
                "direction": "BURN",
                "amount_usd": 40_000_000.0,
                "available_timestamp_12": base_time,
                "available_timestamp_64": base_time + 624,
            },
            {
                "event_id": "same-mint-b",
                "direction": "MINT",
                "amount_usd": 30_000_000.0,
                "available_timestamp_12": base_time,
                "available_timestamp_64": base_time + 624,
            },
        ]
    )
    first = _strict_prior_features(events, 12).sort_index()
    second = _strict_prior_features(
        events.sample(frac=1.0, random_state=20260727), 12
    ).sort_index()
    pd.testing.assert_frame_equal(first, second, check_exact=True)
    expected_same = math.log1p(10_000_000.0)
    expected_net = math.log1p(10_000_000.0)
    for event_id in ("same-mint-a", "same-mint-b"):
        if not math.isclose(
            float(
                first.loc[event_id, "prior_60m_same_direction_event_notional"]
            ),
            expected_same,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise AssertionError(first.loc[event_id])
        if not math.isclose(
            float(first.loc[event_id, "prior_24h_net_issuance"]),
            expected_net,
            rel_tol=0.0,
            abs_tol=1e-12,
        ):
            raise AssertionError(first.loc[event_id])
    if (
        float(
            first.loc[
                "same-burn", "prior_60m_same_direction_event_notional"
            ]
        )
        != 0.0
    ):
        raise AssertionError(first.loc["same-burn"])
    if not math.isclose(
        float(first.loc["same-burn", "prior_24h_net_issuance"]),
        expected_net,
        rel_tol=0.0,
        abs_tol=1e-12,
    ):
        raise AssertionError(first.loc["same-burn"])
    print("stablecoin simultaneous-availability invariance self-test passed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--events", type=Path, required=True)
    run_parser.add_argument("--market-cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    _install_patch()
    if args.command == "self-test":
        self_test()
        return 0
    strict.run(args)
    guard = _augment_result(args.output)
    print(json.dumps({"strict_causal_guard": guard}, indent=2, sort_keys=True))
    if guard["fatal_validity_violation"]:
        return 2
    result = json.loads(
        (args.output / "RESULT.json").read_text(encoding="utf-8")
    )
    return (
        0
        if result.get("status")
        == "PRE2024_SURVIVOR_READY_FOR_SEQUENTIAL_2024H1"
        else 2
    )


if __name__ == "__main__":
    raise SystemExit(main())
