from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def audit_latency(root: Path, latency_ms: int) -> dict:
    result = json.loads((root / "RESULT.json").read_text())
    assert result["claim_id"] == "CLM-20260726-2036-ML-XVENUE-MAKER-001"
    assert result["official_2024_2026_opened"] is False
    assert result["orders_submitted"] is False
    expected_delta = 1 + latency_ms // 100
    checks = ["authority and sealed-period flags"]
    for stage, date in result["dates"].items():
        assert date < "2024-01-01"
        events = pd.read_csv(root / f"events_{stage}.csv")
        if len(events):
            assert (events["placement_bin"] - events["signal_bin"] == expected_delta).all()
            assert (events["pending_end_bin"] >= events["placement_bin"]).all()
            filled = events[events["filled"].eq(1)]
            if len(filled):
                assert (filled["fill_bin"] >= filled["placement_bin"]).all()
                assert not filled["exit_reason"].str.contains("time|timeout", case=False, regex=True).any()
    checks.append("completed-state placement latency and structural-only exits")

    if (root / "scored_confirmation.csv").exists():
        scored = pd.read_csv(root / "scored_confirmation.csv")
        for cost in (12, 18, 24):
            trade_path = root / f"trades_{cost}bp.csv"
            if not trade_path.exists():
                continue
            trades = pd.read_csv(trade_path)
            metrics = result["economic"][str(cost)]
            assert len(trades) == metrics["trade_count"]
            if len(trades):
                assert float(trades["leverage"].max()) <= 3.0 + 1e-12
                compounded = float(np.prod(1.0 + trades["account_return"].to_numpy()) - 1.0)
                assert math.isclose(compounded, metrics["total_return"], rel_tol=0, abs_tol=2e-12)
                ordered = trades.sort_values("fill_bin")
                assert (ordered["fill_bin"].iloc[1:].to_numpy() > ordered["exit_bin"].iloc[:-1].to_numpy()).all() if len(ordered) > 1 else True
            removed = pd.read_csv(root / f"trades_{cost}bp_winner_removed.csv")
            excluded = set(metrics["top10_positive_event_keys_removed"])
            assert not set(removed.get("event_key", pd.Series(dtype=str))).intersection(excluded)
        checks.append("account compounding, one-slot chronology, leverage, and winner rerouting")

    return {
        "latency_ms": latency_ms,
        "status": "PASS",
        "result_sha256": sha256(root / "RESULT.json"),
        "checks": checks,
    }


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--latency100", required=True)
    p.add_argument("--latency300", required=True)
    p.add_argument("--combined", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    combined = json.loads(Path(args.combined).read_text())
    assert combined["official_2024_2026_opened"] is False
    assert combined["orders_submitted"] is False
    payload = {
        "claim_id": combined["claim_id"],
        "result_id": combined["result_id"],
        "status": "PASS",
        "latencies": [
            audit_latency(Path(args.latency100), 100),
            audit_latency(Path(args.latency300), 300),
        ],
        "combined_result_sha256": sha256(Path(args.combined)),
        "official_2024_2026_opened": False,
        "orders_submitted": False,
    }
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
