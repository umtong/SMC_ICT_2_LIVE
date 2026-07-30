from __future__ import annotations

import unittest

import numpy as np

import audit


class RobustRiskAuditTest(unittest.TestCase):
    def test_registered_grid_is_unique_and_unchanged(self) -> None:
        self.assertEqual(len(audit.GRID), 12)
        self.assertEqual(len(set(audit.GRID)), 12)
        self.assertEqual(audit.GRID[0], (0.005, 3.0))
        self.assertEqual(audit.GRID[-1], (0.60, 12.0))
        self.assertIn((0.10, 12.0), audit.GRID)

    def test_bootstrap_is_deterministic(self) -> None:
        x = np.linspace(-0.01, 0.02, 730, dtype=float)
        first = audit.bootstrap_summary(x)
        second = audit.bootstrap_summary(x)
        self.assertEqual(first, second)
        self.assertLess(first["q05_mean_log_growth"], first["median_mean_log_growth"])
        self.assertLess(first["median_mean_log_growth"], first["q95_mean_log_growth"])

    def test_signal_contract_is_fixed(self) -> None:
        self.assertEqual(audit.THRESHOLD, 2.2706072565238586)
        self.assertEqual(
            audit.SUBSET,
            {("BTCUSDT", 1), ("ETHUSDT", 1), ("ETHUSDT", -1)},
        )


if __name__ == "__main__":
    unittest.main()
