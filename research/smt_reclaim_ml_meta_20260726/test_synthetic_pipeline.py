from __future__ import annotations

import gzip
import json
import math
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

import train_entry as wrapper

engine = wrapper.engine


def rows_for_stage(stage: str, dates: list[str], seed: int) -> list[dict[str, object]]:
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    sequence = 0
    for date_index, date in enumerate(dates):
        for index in range(24):
            latent = -2.5 + 5.0 * index / 23.0 + rng.normal(0, 0.05)
            positive = latent > 0
            gross = 70.0 if positive else -25.0
            base_time = 1_650_000_000 + date_index * 100_000 + index * 10
            row: dict[str, object] = {
                "claim_id": engine.CLAIM_ID,
                "stage": stage,
                "date": date,
                "event_id": f"{stage}-{date}-{index}",
                "symbol": "XRPUSDT" if index % 2 else "SOLUSDT",
                "horizon_seconds": (1, 2, 5)[index % 3],
                "confirmation_time": float(base_time),
                "btc_displacement_z": 4.0 + latent,
                "btc_activity_ratio": 2.5 + 0.1 * latent,
                "btc_aggressor_alignment": 0.7 + 0.02 * latent,
                "follower_aggressor_alignment_at_event": 0.7 + 0.01 * latent,
                "frozen_beta": 1.1 + 0.05 * latent,
                "initial_residual_gap_bps": 20.0 + max(0.0, latent),
                "overreaction_ratio": 1.4 + 0.05 * latent,
                "target_to_btc_trade_count_ratio_30m": 1.2 + 0.1 * latent,
                "target_to_btc_realized_volatility_ratio_15m": 1.8 + 0.1 * latent,
                "mss_residual_contraction_ratio": 0.7 - 0.05 * latent,
                "milliseconds_event_to_mss": 1200.0 - 100.0 * latent,
                "opposite_flow_strength_1s": 0.25 + 0.08 * latent,
                "opposite_flow_trade_count_1s": 8.0 + max(0.0, latent),
                "target_realized_volatility_10s": 0.002 + 0.0002 * latent,
                "target_trade_count_1s": 12.0 + max(0.0, latent),
                "other_follower_residual_bps": 4.0 + 3.0 * latent,
                "utc_time_sine": math.sin(index / 24.0 * 2 * math.pi),
                "utc_time_cosine": math.cos(index / 24.0 * 2 * math.pi),
            }
            for latency in engine.LATENCIES:
                row[f"l{latency}_trade"] = True
                row[f"l{latency}_entry_time"] = float(base_time + latency / 1000.0)
                row[f"l{latency}_exit_time"] = float(base_time + 1.0 + latency / 1000.0)
                row[f"l{latency}_gross_bps"] = gross - (latency - 100) * 0.002
                row[f"l{latency}_net24_bps"] = row[f"l{latency}_gross_bps"] - 24.0
                row[f"l{latency}_unavailable"] = False
                row[f"l{latency}_boundary_loss"] = False
                row[f"l{latency}_status"] = "TRADE"
            rows.append(row)
            sequence += 1
    return rows


def write_matrix(root: Path, name: str, rows: list[dict[str, object]]) -> None:
    root.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(root / f"matrix_{name}.csv.gz", index=False, compression="gzip")


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        base = root / "base"
        development = root / "development"
        selection = root / "selection"
        calibration_output = root / "calibration_output"
        development_output = root / "development_output"
        selection_output = root / "selection_output"
        final_output = root / "final_output"

        fit_dates = sorted(engine.FIT_DATES)
        calibration_dates = sorted(engine.CALIBRATION_DATES)
        development_dates = sorted(engine.DEVELOPMENT_DATES)
        selection_dates = sorted(engine.SELECTION_DATES)
        write_matrix(base, "fit", rows_for_stage("FIT", fit_dates, 1))
        write_matrix(base, "calibration", rows_for_stage("CALIBRATION", calibration_dates, 2))
        with gzip.open(base / "matrix_empty_date.csv.gz", "wt", encoding="utf-8") as stream:
            stream.write("")
        write_matrix(
            development,
            "development",
            rows_for_stage("DEVELOPMENT", development_dates, 3),
        )
        write_matrix(
            selection,
            "selection",
            rows_for_stage("SELECTION_EVIDENCE", selection_dates, 4),
        )

        calibration = engine.calibrate(base, calibration_output)
        assert calibration["pair_survivor_count"] > 0
        assert calibration["freeze"]["calibration_survivor"] is True
        development_result = wrapper.corrected_evaluate_frozen(
            development,
            calibration_output / "MODEL_BUNDLE.joblib",
            calibration_output / "FREEZE.json",
            "DEVELOPMENT",
            development_output,
        )
        assert development_result["stage_gate_passed"] is True
        selection_result = wrapper.corrected_evaluate_frozen(
            selection,
            calibration_output / "MODEL_BUNDLE.joblib",
            calibration_output / "FREEZE.json",
            "SELECTION_EVIDENCE",
            selection_output,
        )
        assert selection_result["stage_gate_passed"] is True
        final = engine.finalize(
            calibration_output / "CALIBRATION_RESULT.json",
            development_output / "DEVELOPMENT_RESULT.json",
            selection_output / "SELECTION_EVIDENCE_RESULT.json",
            final_output,
        )
        assert final["status"] == "PRE2024_SELECTION_SURVIVOR"
        assert final["pre2024_survivor"] is True
        assert final["official_2024_opened"] is False
        print(json.dumps({
            "status": "SYNTHETIC_PIPELINE_PASS",
            "selected_model": calibration["freeze"]["model_name"],
            "selected_quantile": calibration["freeze"]["score_quantile"],
            "development_status": development_result["status"],
            "selection_status": selection_result["status"],
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
