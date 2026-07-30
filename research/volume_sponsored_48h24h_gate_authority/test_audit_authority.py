from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("audit_authority", HERE / "audit_authority.py")
assert SPEC and SPEC.loader
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)


def test_strict_later_minute_activation() -> None:
    market = object.__new__(m.Market)
    market.mt = np.array([1_000, 2_000, 3_000], dtype=np.int64)
    market.mo = np.array([10.0, 20.0, 30.0])
    assert market.first_minute_after(2_000) == (2, 30.0)


def test_parent_parity_fails_closed() -> None:
    observed = {"multiple": 1.01, "completed_trades": 10}
    expected = {"multiple": 1.02, "trades": 10}
    check = m.parity_check(observed, expected)
    assert check["trade_count_match"] is True
    assert check["close_multiple_match_1e-8"] is False


def test_frozen_rule_constants() -> None:
    assert m.ENTRY_LB == 48
    assert m.EXIT_LB == 24
    assert m.VOL_Z == 2.2706072565238586
    assert m.RISK == 0.005
    assert m.CAP == 3.0
    assert m.SYMBOL_SIDES == {("BTCUSDT", 1), ("ETHUSDT", 1), ("ETHUSDT", -1)}
