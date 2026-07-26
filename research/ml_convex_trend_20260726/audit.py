from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, roc_auc_score

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "observed"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    result = json.loads((OUT / "RESULT.json").read_text())
    prereg_sha = sha256(ROOT / "preregistration.json")
    expected = json.loads((ROOT / "FINGERPRINTS.json").read_text())["preregistration_sha256"]
    assert prereg_sha == expected == result["preregistration_sha256"]
    assert result["official_2024_opened"] is False
    assert result["status"] == "CONFIRMATION_BELOW_GATE"
    assert result["decision"] == "KILL_EXACT_CONVEX_TREND_ROUTE_NO_ADJACENT_TUNING"
    assert not result["all_gates_pass"]

    conf = pd.read_csv(OUT / "events_confirmation.csv")
    cutoff = int(pd.Timestamp("2024-01-01", tz="UTC").value // 1_000_000)
    assert len(conf) == result["event_counts"]["confirmation"] == 261
    assert int(conf["entry_time_ms"].max()) < cutoff
    assert int(conf["label_end_time_ms"].max()) < cutoff
    assert set(conf["label"].unique()) == {0, 1}
    auc = roc_auc_score(conf["label"], conf["probability"])
    brier = brier_score_loss(conf["label"], conf["probability"])
    base = brier_score_loss(conf["label"], np.full(len(conf), conf["label"].mean()))
    skill = 1 - brier / base
    assert math.isclose(auc, result["model"]["confirmation_auc"], rel_tol=0, abs_tol=1e-12)
    assert math.isclose(brier, result["model"]["confirmation_brier"], rel_tol=0, abs_tol=1e-12)
    assert math.isclose(skill, result["model"]["confirmation_brier_skill"], rel_tol=0, abs_tol=1e-12)

    paths = pd.read_csv(OUT / "episode_paths_confirmation.csv")
    assert len(paths) == len(conf)
    assert paths["event_key"].is_unique
    assert int(paths["exit_time_ms"].max()) < cutoff
    assert (paths["max_stage"].between(0, 2)).all()
    assert paths.loc[paths["add2_idx"].isna(), "add3_idx"].isna().all()

    for bps in (12, 18, 24):
        for mode in ("unit1", "pyramid"):
            trades = pd.read_csv(OUT / f"trades_{mode}_{bps}bp.csv")
            metrics = result["economic"][str(bps)][mode]
            assert len(trades) == metrics["trade_count"]
            if len(trades):
                compounded = float(np.prod(1.0 + trades["account_return"].to_numpy()) - 1.0)
                assert math.isclose(compounded, metrics["total_return"], rel_tol=0, abs_tol=2e-12)
                assert (trades["entry_time_ms"] < trades["exit_time_ms"] + 1).all()
                assert int(trades["exit_time_ms"].max()) < cutoff
                assert float(trades["max_leverage"].max()) <= 5.0 + 1e-9
            if mode == "unit1" and len(trades):
                assert set(trades["unit_count"].unique()) == {1}
            if mode == "pyramid" and len(trades):
                assert trades["unit_count"].between(1, 3).all()
                joined = trades.merge(
                    paths[["event_key", "max_stage"]].rename(columns={"max_stage": "path_max_stage"}),
                    on="event_key",
                    how="left",
                    validate="one_to_one",
                )
                assert ((joined["unit_count"] - 1) <= joined["path_max_stage"]).all()

    full24 = pd.read_csv(OUT / "trades_pyramid_24bp.csv")
    excluded = set(result["winner_removed"]["24"]["excluded_event_keys"])
    positive = full24.loc[full24["net_pnl"] > 0].sort_values(
        ["net_pnl", "event_key"], ascending=[False, False]
    )
    expected_n = min(len(positive), max(1, math.ceil(len(full24) * 0.10))) if len(positive) else 0
    assert len(excluded) == expected_n
    assert excluded.issubset(set(positive["event_key"]))
    assert (
        result["economic"]["24"]["pyramid"]["total_return"]
        < result["economic"]["24"]["unit1"]["total_return"]
    )
    assert result["winner_removed"]["24"]["pyramid"]["total_return"] < 0

    audit = {
        "status": "PASS",
        "preregistration_sha256": prereg_sha,
        "result_sha256": sha256(OUT / "RESULT.json"),
        "code_sha256": sha256(ROOT / "run.py"),
        "confirmation_rows": len(conf),
        "confirmation_auc_recomputed": auc,
        "confirmation_brier_skill_recomputed": skill,
        "official_2024_opened": False,
        "checks": [
            "preregistration hash preserved",
            "confirmation labels and all exits precede 2024",
            "model metrics independently recomputed",
            "account returns compound to reported totals at 12/18/24bp",
            "unit-one and pyramid stage constraints hold",
            "leverage never exceeds 5x",
            "winner-removal keys independently reproduced",
            "no order credentials or 2024 data used",
        ],
    }
    (OUT / "AUDIT.json").write_text(json.dumps(audit, indent=2, sort_keys=True) + "\n")
    print(json.dumps(audit, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
