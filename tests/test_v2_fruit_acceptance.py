"""Category preference must not override the workbook's inventory gap."""
from copy import deepcopy
from pathlib import Path
import unittest

import pandas as pd

from scripts.v2_scenario_regression import _scenario_contract_violations
from services.intent_parser import IntentParser
from services.local_optimizer import LocalOptimizer
from services.v2_preparation import V2PreparationPipeline


class OfflineClient:
    is_available = False


class FruitAcceptanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workbook = pd.read_excel(
            Path(__file__).resolve().parents[1] / "data/AI_Demo_Data_Pack_V2_Large.xlsx",
            sheet_name=None,
        )
        prepared = V2PreparationPipeline(
            intent_parser=IntentParser(ai_client=OfflineClient())
        ).prepare(cls.workbook, "C051", "Focus on Fruit products. Budget NZD 800.", "2026-06-02")
        # Only the acceptance checker is under test; this is not live API evidence.
        prepared["intent"]["AIAnalysisStatus"] = "live"
        safe = prepared["safe_decision_context"]
        decisions = {"candidate_decisions": [
            {"candidate_id": c["candidate_id"], "recommended": True,
             "recommendation_type": c["recommendation_type"], "priority": "MEDIUM",
             "replenishment_intensity": "MEDIUM", "decision_signals": c["signals"]}
            for c in safe["candidates"]
        ]}
        features = {c["candidate_id"]: c["features"] for c in safe["candidates"]}
        candidates = [{**c, "features": features[c["candidate_id"]]}
                      for c in prepared["candidate_pool"]["eligible_candidates"]]
        optimized = LocalOptimizer().optimize(
            cls.workbook, "C051", safe["structured_intent"], candidates, decisions, "2026-06-02",
        )
        cls.base_result = {
            **prepared, "ai_decision": decisions, "optimizer_result": optimized,
            "final_purchase_plan": optimized["purchase_plan"],
            "validation_result": {"valid": True, "status": "PASS"},
            "v2_status": "SUCCESS", "fallback_triggered": False,
        }

    def setUp(self):
        self.result = deepcopy(self.base_result)

    def check(self, workbook=None):
        return _scenario_contract_violations(
            "05_fruit_focus", self.result, self.workbook if workbook is None else workbook,
        )

    def test_recommended_fruit_with_zero_gap_has_no_purchase_and_passes(self):
        self.assertEqual(self.check(), [])
        self.assertFalse({"P206", "P207"} & {
            c["candidate_id"] for c in self.result["final_purchase_plan"]
        })

    def test_zero_gap_does_not_excuse_ignoring_model_preference(self):
        for c in self.result["ai_decision"]["candidate_decisions"]:
            if c["candidate_id"] in {"P206", "P207"}:
                c["recommended"] = False
        self.assertIn("PREFERRED_CATEGORY_NOT_RECOMMENDED", self.check())

    def test_preferred_model_recommendation_rate_cannot_be_lower(self):
        for c in self.result["ai_decision"]["candidate_decisions"]:
            if c["candidate_id"] == "P206":
                c["recommended"] = False
        self.assertTrue(any(v.startswith("PREFERRED_CATEGORY_RECOMMENDATION_RATE_LOWER") for v in self.check()))

    def test_zero_gap_purchase_is_rejected_even_with_pass_validator_label(self):
        self.result["final_purchase_plan"].append({"candidate_id": "P206", "final_qty": 2})
        self.assertIn("ZERO_GAP_PREFERRED_CATEGORY_PURCHASED=P206", self.check())

    def test_zero_gap_requires_explicit_optimizer_reason(self):
        self.result["optimizer_result"]["unallocated_candidates"] = []
        self.assertIn("ZERO_GAP_PREFERRED_CATEGORY_REASON_MISSING=P206", self.check())

    def test_positive_gap_cannot_use_zero_gap_exemption(self):
        workbook = dict(self.workbook)
        inventory = self.workbook["Inventory"].copy()
        mask = (inventory["CustomerId"] == "C051") & (inventory["ProductId"] == "P206")
        inventory.loc[mask, "CurrentStock"] = 0
        workbook["Inventory"] = inventory
        self.assertIn("POSITIVE_GAP_PREFERRED_CATEGORY_NOT_SELECTED=P206", self.check(workbook))

    def test_missing_workbook_cannot_claim_zero_gap(self):
        self.assertIn("PREFERRED_CATEGORY_INVENTORY_EVIDENCE_MISSING",
                      _scenario_contract_violations("05_fruit_focus", self.result))

    def test_only_zero_gap_recommendations_allow_valid_empty_plan(self):
        for c in self.result["ai_decision"]["candidate_decisions"]:
            c["recommended"] = c["candidate_id"] in {"P206", "P207"}
        self.result["final_purchase_plan"] = []
        self.result["optimizer_result"].update(total_cost=0, remaining_budget=800)
        self.assertEqual(self.check(), [])


if __name__ == "__main__":
    unittest.main()
