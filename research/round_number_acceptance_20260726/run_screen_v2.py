from __future__ import annotations

import argparse
import csv
import gzip
import math
import os
import shutil
import time
from pathlib import Path
from typing import Any

import pandas as pd
import requests

import run_screen as core


def safe_download_archive(symbol: str, date: str, cache: Path) -> tuple[Path, dict[str, Any]]:
    """Preserve exact Bybit gzip bytes even when HTTP adds Content-Encoding."""
    cache.mkdir(parents=True, exist_ok=True)
    filename = f"{symbol}{date}.csv.gz"
    path = cache / symbol / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    url = f"{core.BASE_URL}/{symbol}/{filename}"
    if not path.is_file() or path.stat().st_size == 0:
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.unlink(missing_ok=True)
        last_error: Exception | None = None
        for attempt in range(1, 5):
            try:
                with requests.get(url, stream=True, timeout=(20, 180)) as response:
                    response.raise_for_status()
                    response.raw.decode_content = False
                    with temporary.open("wb") as handle:
                        shutil.copyfileobj(response.raw, handle, length=1 << 20)
                if temporary.read_bytes()[:2] != b"\x1f\x8b":
                    raise core.ContractError(f"downloaded object is not raw gzip: {url}")
                os.replace(temporary, path)
                break
            except Exception as exc:
                last_error = exc
                temporary.unlink(missing_ok=True)
                if attempt == 4:
                    raise core.ContractError(f"download failed for {url}: {exc}") from exc
                time.sleep(attempt * 2)
        if not path.exists() and last_error is not None:
            raise core.ContractError(str(last_error))
    if path.read_bytes()[:2] != b"\x1f\x8b":
        raise core.ContractError(f"cached object is not raw gzip: {path}")
    digest = core.sha256_file(path)
    try:
        with gzip.open(path, "rt", newline="") as handle:
            reader = csv.reader(handle)
            header = next(reader)
            rows = sum(1 for _ in reader)
    except Exception as exc:
        raise core.ContractError(f"gzip/CSV integrity failed for {path}: {exc}") from exc
    required = {"timestamp", "symbol", "side", "size", "price"}
    if not required.issubset(set(header)):
        raise core.ContractError(f"missing required fields in {path}: {header}")
    if rows <= 0:
        raise core.ContractError(f"empty archive: {path}")
    return path, {
        "symbol": symbol,
        "date": date,
        "url": url,
        "sha256": digest,
        "compressed_bytes": path.stat().st_size,
        "rows": rows,
        "header": header,
    }


def snapshot(row: pd.Series | None) -> dict[str, Any] | None:
    if row is None:
        return None
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
    output = {key: core.finite(row[key]) for key in specification_keys}
    output["cost_metrics"] = {
        str(int(cost)): {
            key: core.finite(row[f"development_{int(cost)}_{key}"])
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
        for cost in core.COSTS_BPS
    }
    return output


def best_row(results: pd.DataFrame, minimum_trades: int) -> pd.Series | None:
    pool = results.loc[results["development_18_trades"] >= minimum_trades].copy()
    if pool.empty:
        return None
    return pool.sort_values(
        ["development_18_total_return", "development_18_trades", "candidate_id"],
        ascending=[False, False, True],
        kind="mergesort",
    ).iloc[0]


_original_evaluate = core.evaluate


def evaluate_with_sample_tiers(events: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, Any]]:
    results, original_summary = _original_evaluate(events)
    summary = {
        key: value for key, value in original_summary.items() if key != "best_raw_candidate"
    }
    summary["best_any_nonzero_candidate"] = snapshot(best_row(results, 1))
    summary["best_at_least_10_trades"] = snapshot(best_row(results, 10))
    summary["best_at_least_60_trades"] = snapshot(best_row(results, 60))
    return results, summary


def self_test() -> None:
    core.self_test()
    synthetic = pd.DataFrame(
        {
            "candidate_id": ["one", "ten", "sixty"],
            "development_18_trades": [1, 10, 60],
            "development_18_total_return": [0.10, 0.05, -0.01],
        }
    )
    assert best_row(synthetic, 1)["candidate_id"] == "one"
    assert best_row(synthetic, 10)["candidate_id"] == "ten"
    assert best_row(synthetic, 60)["candidate_id"] == "sixty"
    print("V2_TRANSPORT_AND_SAMPLE_TIER_TEST_PASS")


def main() -> int:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("self-test")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--cache", type=Path, required=True)
    run_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    core.download_archive = safe_download_archive
    core.evaluate = evaluate_with_sample_tiers
    if args.command == "self-test":
        self_test()
        return 0
    if args.command == "run":
        core.run(args.cache, args.output)
        return 0
    raise AssertionError(args.command)


if __name__ == "__main__":
    raise SystemExit(main())
