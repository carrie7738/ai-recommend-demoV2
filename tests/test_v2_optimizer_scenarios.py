from __future__ import annotations

from pathlib import Path
import unittest

import pandas as pd

from services.hard_validator import HardValidator
from services.intent_parser import IntentParser
from services.local_optimizer import LocalOptimizer
from services.v2_preparation import V2PreparationPipeline


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"


class OfflineAIClient:
    is_available = False


class V2OptimizerScenarioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = pd.read_excel(WORKBOOK_PATH, sheet_name=None, engine="openpyxl")
        cls.scenarios = cls.workbook["V2TestScenarios"].set_index("ScenarioId")
        cls.preparation = V2PreparationPipeline(
            intent_parser=IntentParser(ai_client=OfflineAIClient())
        )
        cls.optimizer = LocalOptimizer()
        cls.validator = HardValidator()

    def _run_candidate(self, scenario_id: str, candidate_id: str) -> tuple[dict, dict]:
        scenario = self.scenarios.loc[scenario_id]
        prepared = self.preparation.prepare(
            self.workbook,
            str(scenario["CustomerId"]),
            str(scenario["UserInput"]),
            scenario["AsOfDate"],
        )
        safe = {
            item["candidate_id"]: item
            for item in prepared["safe_decision_context"]["candidates"]
        }
        raw = next(
            item
            for item in prepared["candidate_pool"]["eligible_candidates"]
            if item["candidate_id"] == candidate_id
        )
        optimizer_candidate = {**raw, "features": safe[candidate_id]["features"]}
        ai_decision = {
            "candidate_decisions": [{
                "candidate_id": candidate_id,
                "recommended": True,
                "recommendation_type": raw["recommendation_type"],
                "priority": "MEDIUM",
                "replenishment_intensity": "MEDIUM",
                "decision_signals": safe[candidate_id]["signals"],
            }]
        }
        result = self.optimizer.optimize(
            self.workbook,
            str(scenario["CustomerId"]),
            prepared["safe_decision_context"]["structured_intent"],
            [optimizer_candidate],
            ai_decision,
            scenario["AsOfDate"],
        )
        validation = self.validator.validate(
            self.workbook,
            prepared["safe_decision_context"]["structured_intent"],
            [raw],
            ai_decision,
            result,
        )
        self.assertTrue(validation["valid"])
        return result["purchase_plan"][0], result

    def test_sales_unit_tail_stock_and_available_stock_scenarios(self) -> None:
        sales_unit, _ = self._run_candidate("V2-015", "P210")
        tail_stock, _ = self._run_candidate("V2-016", "P211")
        stock_cap, _ = self._run_candidate("V2-017", "P215")

        self.assertEqual(sales_unit["final_qty"] % sales_unit["sales_unit"], 0)
        self.assertIn("SALES_UNIT_ROUNDED", sales_unit["constraint_adjustments"])
        self.assertEqual(tail_stock["final_qty"], 4)
        self.assertIn("TAIL_STOCK_EXCEPTION", tail_stock["constraint_adjustments"])
        self.assertEqual(stock_cap["final_qty"], 10)
        self.assertIn("AVAILABLE_STOCK_CAPPED", stock_cap["constraint_adjustments"])

    def test_event_baseline_fallback_order_reaches_optimizer(self) -> None:
        store_event, _ = self._run_candidate("V2-018", "P212")
        peer_event, _ = self._run_candidate("V2-019", "P212")
        recent_store, _ = self._run_candidate("V2-020", "P212")

        self.assertEqual(store_event["baseline_source"], "STORE_EVENT")
        self.assertEqual(peer_event["baseline_source"], "PEER_EVENT")
        self.assertEqual(recent_store["baseline_source"], "RECENT_STORE")


if __name__ == "__main__":
    unittest.main()
