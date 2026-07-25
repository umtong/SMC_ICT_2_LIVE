from __future__ import annotations

import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "research" / "dynamic_factor_residual_final_20260725"
RESULT = ROOT / "research" / "reports" / "RES-20260725-DYNAMIC-FACTOR-001.json"
VALIDATION = ROOT / "research" / "validation" / "VAL-20260725-DYNAMIC-FACTOR-ACTUAL-FUNDING-001.json"
DATASET = ROOT / "data" / "catalog" / "DS-BINANCE-USDM-4ASSET-FUNDING-MARK-2023-R1.json"


class DynamicFactorReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.summary = json.loads((BASE / "actual_funding_audit_summary.json").read_text())
        self.ranking = json.loads((BASE / "FIRST_PLACE_PROPOSAL.json").read_text())
        self.result = json.loads(RESULT.read_text())
        self.validation = json.loads(VALIDATION.read_text())
        self.dataset = json.loads(DATASET.read_text())

    def test_exact_actual_funding_metrics(self) -> None:
        base = self.summary["scenarios"]["base"]
        self.assertEqual(base["trades"], 194)
        self.assertAlmostEqual(base["total_return"], 0.23258469071784216, places=15)
        self.assertAlmostEqual(base["gmean_daily"], 0.0005730774040979547, places=15)
        self.assertAlmostEqual(base["profit_factor"], 1.504104514971923, places=14)
        self.assertLess(base["top10pct_removed_return"], 0.0)
        self.assertLess(base["median_net_bps"], 0.0)

    def test_cost_stress_uses_same_candidate_and_stays_positive(self) -> None:
        self.assertGreater(self.summary["scenarios"]["cost18"]["total_return"], 0.0)
        self.assertGreater(self.summary["scenarios"]["cost24"]["total_return"], 0.0)
        self.assertEqual(self.summary["candidate_id"], "021fbab613517a31ad98")

    def test_stage_and_order_seals(self) -> None:
        self.assertFalse(self.summary["later_holdout_opened"])
        self.assertFalse(self.summary["orders_submitted"])
        self.assertEqual(self.summary["stage"], "EXPLORATORY_DEVELOPMENT_2023")

    def test_result_validation_dataset_identity(self) -> None:
        dependency = "7dcce21901d8ee6e6a55316da98edc5c44ffce79a148dea25f6a9b470ad49046"
        self.assertEqual(self.result["dependency_fingerprint"], dependency)
        self.assertEqual(self.validation["dependency_fingerprint"], dependency)
        self.assertIn(self.dataset["dataset_id"], self.result["dataset_ids"])
        self.assertEqual(self.validation["status"], "PASS")
        self.assertEqual(self.result["hard_validity_status"], "PASS")
        self.assertEqual(self.result["economic_status"], "BASIC_COST_POSITIVE")

    def test_provisional_rank_is_separate_from_practical_use(self) -> None:
        challenger = self.ranking["challenger"]
        incumbent = self.ranking["current_first_place"]
        self.assertEqual(self.ranking["decision"], "PROPOSE_PROVISIONAL_FIRST_PLACE")
        self.assertGreater(challenger["geometric_daily_growth"], incumbent["geometric_daily_growth"])
        self.assertGreater(challenger["return_24bps"], incumbent["return_24bps"])
        self.assertLess(challenger["maximum_drawdown"], incumbent["maximum_drawdown"])
        self.assertLess(challenger["top5_positive_share"], incumbent["top5_positive_share"])
        self.assertFalse(challenger["frozen_2024_family_portfolios_passed"])
        self.assertLess(challenger["top10pct_removed_return"], 0.0)


if __name__ == "__main__":
    unittest.main()
