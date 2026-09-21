import unittest
from pathlib import Path

import pandas as pd

from services.excel_loader import ExcelLoader
from services.hard_validator import HardValidator
from services.intent_parser import IntentParser
from services.local_optimizer import LocalOptimizer
from services.v2_preparation import V2PreparationPipeline


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"
V2_PRODUCT_IDS = [f"P{value}" for value in range(201, 216)]


class DemoDataAlignmentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = ExcelLoader(WORKBOOK_PATH).load_workbook()

    def test_c001_has_one_inventory_row_for_each_v2_product(self) -> None:
        inventory = self.workbook["Inventory"].copy()
        inventory["CustomerId"] = inventory["CustomerId"].astype(str)
        inventory["ProductId"] = inventory["ProductId"].astype(str)
        rows = inventory.loc[
            inventory["CustomerId"].eq("C001")
            & inventory["ProductId"].isin(V2_PRODUCT_IDS)
        ]

        self.assertEqual(rows["ProductId"].tolist(), V2_PRODUCT_IDS)
        self.assertFalse(rows.duplicated(["CustomerId", "ProductId"]).any())
        self.assertTrue(pd.to_numeric(rows["CurrentStock"], errors="coerce").notna().all())
        self.assertTrue(pd.to_datetime(rows["LastUpdated"], errors="coerce").notna().all())

    def test_c001_high_traffic_demo_can_produce_valid_purchase_lines(self) -> None:
        request = (
            "For Cafe Store 001, high traffic is expected next week. "
            "Budget is NZD 1000."
        )
        store_context = {
            "CustomerId": "C001",
            "StoreName": "Cafe Store 001",
            "Industry": "Cafe",
            "Region": "Christchurch",
            "StoreLevel": "Bronze",
            "CustomerStage": "New",
        }
        parsed_intent = IntentParser(
            ai_client=type("OfflineAI", (), {"is_available": False})()
        ).parse_intent(request, store_context=store_context)
        parser = type(
            "FixedParser",
            (),
            {"parse_intent": lambda self, *args, **kwargs: parsed_intent},
        )()
        prepared = V2PreparationPipeline(intent_parser=parser).prepare(
            self.workbook,
            "C001",
            request,
            "2026-06-02",
            parsed_intent=parsed_intent,
        )
        safe_context = prepared["safe_decision_context"]
        features = {
            item["candidate_id"]: item["features"]
            for item in safe_context["candidates"]
        }
        candidates = [
            {**item, "features": features[item["candidate_id"]]}
            for item in prepared["candidate_pool"]["eligible_candidates"]
        ]
        decisions = {
            "candidate_decisions": [
                {
                    "candidate_id": item["candidate_id"],
                    "recommended": True,
                    "recommendation_type": item["recommendation_type"],
                    "priority": (
                        "HIGH"
                        if item["features"].get("stockout_risk") == "HIGH"
                        else "MEDIUM"
                    ),
                    "replenishment_intensity": "MEDIUM",
                    "decision_signals": item["signals"],
                    "why_selected": ["Verified demo signal."],
                }
                for item in safe_context["candidates"]
            ],
            "procurement_strategy": {},
        }
        optimizer_result = LocalOptimizer().optimize(
            self.workbook,
            "C001",
            safe_context["structured_intent"],
            candidates,
            decisions,
            "2026-06-02",
        )
        validation_result = HardValidator().validate(
            self.workbook,
            safe_context["structured_intent"],
            candidates,
            decisions,
            optimizer_result,
            as_of_date="2026-06-02",
        )

        self.assertGreater(len(optimizer_result["purchase_plan"]), 0)
        self.assertGreater(optimizer_result["total_cost"], 0)
        self.assertEqual(validation_result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
