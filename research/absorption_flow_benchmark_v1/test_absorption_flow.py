from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import numpy as np
import pandas as pd

MODULE_PATH = Path(__file__).resolve().parent / "absorption_flow_benchmark.py"
spec = importlib.util.spec_from_file_location("absorption_flow_benchmark", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def minute_fixture() -> pd.DataFrame:
    index = pd.date_range("2024-01-01", periods=20, freq="1min", tz="UTC")
    close = np.linspace(100, 102, len(index))
    frame = pd.DataFrame(index=index)
    frame["open"] = np.r_[close[0], close[:-1]]
    frame["close"] = close
    frame["high"] = frame[["open", "close"]].max(axis=1) + 0.1
    frame["low"] = frame[["open", "close"]].min(axis=1) - 0.1
    frame["volume"] = 1.0
    frame["quote_volume"] = 100.0
    frame["num_trades"] = 10
    frame["signed_quote"] = 0.0
    return frame


def test_strict_resample_discards_incomplete_group() -> None:
    frame = minute_fixture().drop(pd.Timestamp("2024-01-01 00:02", tz="UTC"))
    out = module.strict_resample_5m(frame)
    assert pd.Timestamp("2024-01-01 00:00", tz="UTC") not in out.index
    assert pd.Timestamp("2024-01-01 00:05", tz="UTC") in out.index


def test_target_is_net_reward_after_cost() -> None:
    cost = module.COST_PROFILES[0]
    entry = 100.0 * (1 + cost.slippage_rate)
    unit_loss = 2.0
    trigger = module.trigger_for_net_reward(entry, unit_loss, 1, 2.0, cost)
    exit_exec = trigger * (1 - cost.slippage_rate)
    net = exit_exec - entry - cost.fee_rate * (entry + exit_exec)
    assert abs(net - 4.0) < 1e-9


def test_candidate_ids_unique() -> None:
    ids = [candidate.candidate_id for candidate in module.candidate_grid()]
    assert len(ids) == len(set(ids))


def test_no_future_in_prior_z() -> None:
    base = pd.Series(np.arange(100, dtype=float))
    a = module.prior_z(base, 20, 5)
    changed = base.copy(); changed.iloc[80:] += 10_000
    b = module.prior_z(changed, 20, 5)
    pd.testing.assert_series_equal(a.iloc[:80], b.iloc[:80])
