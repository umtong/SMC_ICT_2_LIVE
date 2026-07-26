from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

MODULE_PATH = Path(__file__).with_name("run_wallet_skill_gate.py")
spec = importlib.util.spec_from_file_location("wallet_skill_gate", MODULE_PATH)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def synthetic_observations(invert_future: bool = False):
    dates = [
        "2025-07-27", "2025-07-28", "2025-07-29", "2025-07-30",
        "2025-07-31", "2025-08-01", "2025-08-02", "2025-08-03", "2025-08-04",
    ]
    output = {date: [] for date in dates}
    for coin in module.COINS:
        for index in range(40):
            wallet = f"0x{coin.lower()}{index:038d}"
            prior_mark = -20.0 + index * (40.0 / 39.0)
            for _repeat in range(20):
                output["2025-07-27"].append(
                    module.Observation("2025-07-27", "warmup", coin, wallet, prior_mark, prior_mark)
                )
            for date in dates[1:4]:
                output[date].append(
                    module.Observation(date, module.ROLE_BY_DATE[date], coin, wallet, prior_mark, prior_mark)
                )
            future = -prior_mark if invert_future else prior_mark
            for date in dates[4:]:
                output[date].append(
                    module.Observation(date, module.ROLE_BY_DATE[date], coin, wallet, future, future)
                )
    return dates, output


def test_first_after():
    series = (np.array([1000, 2000, 8000], dtype=np.int64), np.array([10.0, 11.0, 12.0]))
    assert module.first_after(series, 1500, 600) == 11.0
    assert module.first_after(series, 2500, 1000) is None


def test_causal_gate_passes_persistent_skill():
    dates, observations = synthetic_observations(False)
    result, snapshots = module.evaluate_candidate(
        (60, 20, 50, 0.02), dates, observations, module.DEV_ROLES, True
    )
    assert result["gate_passed"], result["gate_failures"]
    assert result["parts"]["development_a"]["top_minus_bottom_spread_bp"] >= 4
    assert result["parts"]["development_b"]["mean_score_return_correlation"] > 0
    assert snapshots


def test_causal_gate_rejects_reversed_skill():
    dates, observations = synthetic_observations(True)
    result, _ = module.evaluate_candidate((60, 20, 50, 0.02), dates, observations, module.DEV_ROLES)
    assert not result["gate_passed"]
    assert any(
        "mean_signed_positive" in failure or "correlation_positive" in failure
        for failure in result["gate_failures"]
    )


def test_top_positive_removal_and_rank():
    assert module.remove_top_positive([100.0, 2.0, 1.0, -1.0]) < 2.0
    dates, observations = synthetic_observations(False)
    passed, _ = module.evaluate_candidate((60, 20, 50, 0.02), dates, observations, module.DEV_ROLES)
    failed, _ = module.evaluate_candidate((60, 50, 50, 0.02), dates, observations, module.DEV_ROLES)
    ranked = module.rank_candidates([failed, passed])
    assert ranked[0]["gate_passed"] is True


def main():
    test_first_after()
    test_causal_gate_passes_persistent_skill()
    test_causal_gate_rejects_reversed_skill()
    test_top_positive_removal_and_rank()
    print("wallet skill synthetic tests passed")


if __name__ == "__main__":
    main()
