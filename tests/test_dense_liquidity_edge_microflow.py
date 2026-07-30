from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'research/dense_liquidity_edge_microflow/extract_edge_microflow.py'
spec = importlib.util.spec_from_file_location('dense_edge_extract', SCRIPT)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
assert spec.loader is not None
spec.loader.exec_module(module)


class DenseLiquidityEdgeTests(unittest.TestCase):
    def test_sensor_and_delayed_entry(self):
        s = module.Sensor(
            event_id='e', symbol='BTCUSDT', day='2023-01-01', side='HIGH',
            level=100.0, prev_high=100.0, prev_low=90.0, atr15m20=2.0,
            seq=1, anchor_ms=1_000, anchor_price=100.0,
            sensor=[
                (1_000, 100.0, 1.0, 'BUY'),
                (5_500, 101.0, 2.0, 'BUY'),
                (10_500, 100.5, 1.0, 'SELL'),
            ],
            entry_ms=12_000, entry_price=100.7,
        )
        row = module.sensor_features(s, 'ok')
        self.assertEqual(row['entry_price'], 100.7)
        self.assertGreater(row['flow_imbalance'], 0)

    def test_first_trade_crossing_creates_event_without_current_bar_future(self):
        p = module.MonthProcessor('BTCUSDT', 2023, 1)
        p.atr = 2.0
        p.prev_high = 100.0
        p.prev_low = 90.0
        p.day_str = '2023-01-01'
        p.process_trade(1_000, 99.9, 1.0, 'BUY', True)
        self.assertEqual(len(p.active), 0)
        p.process_trade(2_000, 100.0, 1.0, 'BUY', True)
        self.assertEqual(len(p.active), 1)
        self.assertEqual(p.active[0].anchor_ms, 2_000)

    def test_completed_minute_rearms_only_after_inside_close(self):
        p = module.MonthProcessor('BTCUSDT', 2023, 1)
        p.atr = 2.0
        p.prev_high = 100.0
        p.prev_low = 90.0
        p.day_str = '2023-01-01'
        p.armed['HIGH'] = False
        p.process_trade(1_000, 99.5, 1.0, 'SELL', True)
        p.process_trade(61_000, 99.4, 1.0, 'SELL', True)
        self.assertTrue(p.armed['HIGH'])


if __name__ == '__main__':
    unittest.main()
