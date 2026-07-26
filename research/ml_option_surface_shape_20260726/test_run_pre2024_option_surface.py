from __future__ import annotations

import datetime as dt
import importlib.util
import sys
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).with_name("run_pre2024_option_surface.py")
spec = importlib.util.spec_from_file_location("option_surface_run", MODULE_PATH)
assert spec and spec.loader
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


class OptionSurfaceTests(unittest.TestCase):
    def contract(self, symbol: str, asset: str, event_us: int, expiry_us: int, option_type: str, strike: float, delta: float, iv: float, oi: float = 10.0):
        return m.ContractState(
            symbol=symbol,
            asset=asset,
            event_us=event_us,
            option_type=option_type,
            strike=strike,
            expiration_us=expiry_us,
            open_interest=oi,
            bid_iv=iv - 0.5,
            ask_iv=iv + 0.5,
            mark_iv=iv,
            underlying_price=50_000.0,
            delta=delta,
        )

    def test_surface_construction(self):
        snapshot = int(dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1_000_000)
        state = {}
        for label, days, base in (("F", 10, 55.0), ("M", 30, 52.0), ("B", 90, 50.0)):
            expiry = snapshot + days * 86_400_000_000
            contracts = [
                self.contract(f"BTC-{label}-C25", "BTC", snapshot - 1, expiry, "call", 55_000, 0.25, base - 2, 12),
                self.contract(f"BTC-{label}-P25", "BTC", snapshot - 1, expiry, "put", 45_000, -0.25, base + 3, 18),
                self.contract(f"BTC-{label}-CATM", "BTC", snapshot - 1, expiry, "call", 50_000, 0.50, base, 20),
                self.contract(f"BTC-{label}-PATM", "BTC", snapshot - 1, expiry, "put", 50_000, -0.50, base + 1, 22),
            ]
            state.update({item.symbol: item for item in contracts})
        surface = m.build_surface("BTC", state, snapshot)
        self.assertIsNotNone(surface)
        assert surface is not None
        self.assertAlmostEqual(surface["front_rr25"], -5.0)
        self.assertAlmostEqual(surface["middle_minus_front_atm"], -3.0)
        self.assertEqual(surface["back_atm_missing"], 0.0)
        self.assertEqual(surface["mark_fraction"], 0.0)

    def test_price_context_uses_prior_completed_hour_and_first_passage(self):
        start = int(dt.datetime(2023, 1, 1, tzinfo=dt.timezone.utc).timestamp() * 1000)
        bars = []
        for index in range(180):
            price = 100.0
            high = 101.0 if index < 60 else 100.2
            low = 99.0 if index < 60 else 99.8
            if index == 62:
                high = 101.2
            bars.append(m.MinuteBar(start + index * 60_000, price, high, low, price))
        surface = {"decision_us": (start + 59 * 60_000) * 1000}
        context = m.price_context(surface, bars)
        self.assertIsNotNone(context)
        assert context is not None
        self.assertEqual(context["entry_time_ms"], start + 60 * 60_000)
        self.assertEqual(context["outcome"], "UPPER")
        self.assertEqual(context["label"], 1)

    def test_action_is_cost_adjusted(self):
        row = {"upper_distance": 0.010, "lower_distance": 0.005}
        side, ev_long, ev_short = m.choose_action(row, 0.80, 0.0018)
        self.assertEqual(side, "LONG")
        self.assertGreater(ev_long, 0)
        self.assertLess(ev_short, ev_long)


if __name__ == "__main__":
    unittest.main()
