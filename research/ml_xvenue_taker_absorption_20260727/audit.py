from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

COSTS = (12, 18, 24)
EXPECTED_EXIT_REASONS = {
    "resting_structural_stop",
    "resting_structural_target",
    "external_reference_reversal",
    "opposite_displacement",
    "boundary_nav_mark_open_exposure",
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def close(a: float, b: float, tol: float = 1e-10) -> bool:
    return bool(abs(a - b) <= tol * max(1.0, abs(a), abs(b)))


def audit(root: Path, research_root: Path) -> dict:
    result_path = root / "RESULT.json"
    result = json.loads(result_path.read_text())
    assert result["claim_id"] == "CLM-20260727-ML-XVENUE-TAKER-ABSORPTION-001"
    assert result["result_id"] == "RES-20260727-ML-XVENUE-TAKER-ABSORPTION-001"
    assert result["official_2024h1_opened"] is False
    assert result["orders_submitted"] is False
    contract = result["contract"]
    assert contract["order_latency_ms"] == 500
    assert contract["discretionary_exit_latency_ms"] == 500
    assert contract["one_global_slot"] is True
    assert contract["elapsed_time_exit"] is False

    checks: list[str] = []
    trade_summaries = {}
    for cost in COSTS:
        path = root / f"trades_confirmation_{cost}bp.csv"
        if not path.exists() or path.stat().st_size == 0:
            df = pd.DataFrame()
        else:
            df = pd.read_csv(path)
        metrics = result["economic"][str(cost)]
        assert int(metrics["trade_count"]) == len(df)
        if df.empty:
            recomputed_nav = float(contract["initial_nav"])
            recomputed_return = 0.0
        else:
            assert set(df.exit_reason).issubset(EXPECTED_EXIT_REASONS)
            ordered = df.sort_values(["activation_bin", "event_key"]).reset_index(drop=True)
            previous_exit = -10**30
            previous_open = False
            nav = float(contract["initial_nav"])
            for row in ordered.itertuples(index=False):
                if previous_open:
                    raise AssertionError("trade follows a boundary-open position")
                assert int(row.activation_bin) >= previous_exit + 1
                assert int(row.entry_bin) >= int(row.activation_bin)
                assert int(row.exit_bin) >= int(row.entry_bin)
                nav *= 1.0 + float(row.account_return)
                assert close(nav, float(row.nav_after), 1e-9)
                previous_exit = int(row.exit_bin)
                previous_open = int(row.strategy_closed) == 0
            recomputed_nav = nav
            recomputed_return = nav / float(contract["initial_nav"]) - 1.0
        assert close(recomputed_nav, float(metrics["final_nav"]), 1e-9)
        assert close(recomputed_return, float(metrics["total_return"]), 1e-9)
        trade_summaries[str(cost)] = {
            "trade_count": len(df),
            "recomputed_final_nav": recomputed_nav,
            "recomputed_total_return": recomputed_return,
            "sha256": sha256(path) if path.exists() else None,
        }
        checks.append(f"{cost}bp account path independently compounded and globally non-overlapping")

    event_files = sorted((root.parent / "events").glob("*.csv.gz"))
    if not event_files:
        raise AssertionError("event files missing")
    event_dates = set()
    symbols = set()
    total_events = 0
    for path in event_files:
        frame = pd.read_csv(path, usecols=[
            "date", "symbol", "activation_bin", "signal_bin",
            "follow_filled", "follow_entry_bin", "follow_slot_release_bin", "follow_exit_bin",
            "fade_filled", "fade_entry_bin", "fade_slot_release_bin", "fade_exit_bin",
        ])
        total_events += len(frame)
        event_dates.update(frame.date.astype(str).unique())
        symbols.update(frame.symbol.astype(str).unique())
        assert (frame.activation_bin > frame.signal_bin).all()
        for prefix in ("follow", "fade"):
            assert (frame[f"{prefix}_entry_bin"] >= frame.activation_bin).all()
            assert (frame[f"{prefix}_slot_release_bin"] >= frame[f"{prefix}_entry_bin"]).all()
            assert (frame[f"{prefix}_exit_bin"] >= frame[f"{prefix}_entry_bin"]).all()
    assert event_dates == {"2022-07-01", "2023-03-01", "2023-07-01"}
    assert symbols == {"BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT"}
    checks.append("all source-derived events are pre-2024 and include the four frozen symbols")
    checks.append("every activation follows its completed signal state")
    checks.append("every filled or expired action uses a quote no earlier than activation and releases the global slot no earlier than entry")

    prereg = research_root / "preregistration.json"
    source = research_root / "run.py"
    report = {
        "status": "PASS",
        "claim_id": result["claim_id"],
        "result_id": result["result_id"],
        "result_sha256": sha256(result_path),
        "preregistration_sha256": sha256(prereg),
        "runner_sha256": sha256(source),
        "event_files": len(event_files),
        "total_events": total_events,
        "event_dates": sorted(event_dates),
        "symbols": sorted(symbols),
        "trade_summaries": trade_summaries,
        "checks": checks,
    }
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True)
    parser.add_argument("--research-root", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = audit(Path(args.root), Path(args.research_root))
    Path(args.output).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
