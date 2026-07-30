from types import SimpleNamespace
import importlib.util
import numpy as np
import pandas as pd

spec = importlib.util.spec_from_file_location("m", "run_origin.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

b = pd.DataFrame({
    "high": [1., 2., 5., 3., 2., 1.],
    "low": [5., 4., 1., 3., 4., 5.],
    "open": [1.] * 6,
    "close": [1.] * 6,
    "is_complete": [True] * 6,
    "available_at_ms": np.arange(1, 7) * 100,
    "start_time_ms": np.arange(6) * 100,
})
p = m.confirmed_pivots(b, 2)
assert any(x[0] == "HIGH" and x[2] == 500 for x in p)

bb = pd.DataFrame({"high": [11., 12., 13., 14.], "low": [9., 10., 11., 12.], "close": [10., 11., 12., 13.]})
a = m.tr_atr_prior(bb, 2)
assert np.isnan(a.iloc[2]) and np.isfinite(a.iloc[3])

b15 = pd.DataFrame({"available_at_ms": [900000, 1800000], "is_complete": [True, True], "close": [90., 110.]})
assert m.first_state_invalidation(b15, 0, 2000000, 1, 95.) == 960000

base = m.tms("2022-01-01")
b1 = pd.DataFrame({
    "start_time_ms": [base, base + 60000],
    "observed": [True, True],
    "open": [102., 103.],
    "high": [106., 104.],
    "low": [99., 100.],
    "close": [104., 103.],
})
b15e = pd.DataFrame({
    "available_at_ms": pd.Series(dtype="int64"),
    "is_complete": pd.Series(dtype="bool"),
    "close": pd.Series(dtype="float64"),
})
fund = pd.DataFrame({"timestamp_ms": pd.Series(dtype="int64"), "funding_rate": pd.Series(dtype="float64")})
c = SimpleNamespace(fill_ms=base, fill_mode="INTRAMINUTE_LIMIT", side=1, stop=95., target=105., origin_extreme=96., entry=100.)
r = m.first_exit(c, b1, b15e, fund, 2022)
assert r["exit_reason"] == "YEAR_END_MARK", r

b1s = b1.copy()
b1s.loc[0, "low"] = 94.
r = m.first_exit(c, b1s, b15e, fund, 2022)
assert r["exit_reason"] == "STOP" and r["exit_price"] == 95., r

print("5 semantic tests passed")
