from pathlib import Path
import unittest

import pandas as pd

from services.candidate_pool import CandidatePoolBuilder
from services.decision_features import DecisionFeatureBuilder
from services.v2_policy import V2FeaturePolicy, V2PolicyError


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"


class V2DecisionFeatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = pd.read_excel(WORKBOOK_PATH, sheet_name=None, engine="openpyxl")
        cls.candidate_builder = CandidatePoolBuilder()
        cls.feature_builder = DecisionFeatureBuilder()

    @staticmethod
    def intent(*, soft_preferences=None, explicit_products=None, occasion="NONE"):
        return {
            "hard_constraints": [],
            "soft_preferences": soft_preferences or [],
            "category_preference": [],
            "explicit_products": explicit_products or [],
            "occasion": occasion,
        }

    def features_for(self, customer_id="C051", intent=None, as_of_date="2026-06-02"):
        structured_intent = intent or self.intent()
        pool = self.candidate_builder.build(
            self.workbook,
            customer_id,
            structured_intent,
            as_of_date,
        )
        rows = self.feature_builder.build(
            self.workbook,
            customer_id,
            structured_intent,
            pool.eligible_candidates,
            as_of_date,
        )
        return {row["candidate_id"]: row for row in rows}

    def test_policy_is_loaded_from_workbook(self) -> None:
        policy = V2FeaturePolicy.from_workbook(self.workbook)
        self.assertEqual(policy.purchase_frequency_window_days, 90)
        self.assertEqual(policy.purchase_frequency_high_threshold, 8)
        self.assertEqual(policy.discovery_peer_ratio_threshold, 0.3)

    def test_missing_policy_fails_closed(self) -> None:
        workbook = dict(self.workbook)
        workbook.pop("V2FeaturePolicy")
        with self.assertRaises(V2PolicyError):
            V2FeaturePolicy.from_workbook(workbook)

    def test_purchase_frequency_features_cover_high_and_low(self) -> None:
        rows = self.features_for()
        self.assertEqual(rows["P202"]["features"]["purchase_frequency"], "HIGH")
        self.assertEqual(rows["P203"]["features"]["purchase_frequency"], "LOW")
        self.assertIn("STORE_PURCHASE_HISTORY", rows["P203"]["signals"])

    def test_stockout_risk_uses_coverage_not_raw_stock_label(self) -> None:
        rows = self.features_for()
        self.assertEqual(rows["P204"]["features"]["stockout_risk"], "HIGH")
        self.assertEqual(rows["P205"]["features"]["stockout_risk"], "LOW")

    def test_shelf_life_and_category_preference_are_safe_labels(self) -> None:
        rows = self.features_for(intent=self.intent(soft_preferences=[
            {"type": "CATEGORY", "value": "Fruit"},
            {"type": "SHELF_LIFE", "value": "LONG"},
        ]))
        self.assertEqual(rows["P206"]["features"]["shelf_life_level"], "SHORT")
        self.assertEqual(rows["P207"]["features"]["shelf_life_level"], "LONG")
        self.assertEqual(rows["P214"]["features"]["category_relevance"], "LOW")

    def test_peer_and_user_requested_signals_are_distinct(self) -> None:
        system_rows = self.features_for()
        requested_rows = self.features_for(intent=self.intent(explicit_products=[{"sku": "P209"}]))

        self.assertEqual(system_rows["P208"]["features"]["peer_purchase_ratio"], "40%")
        self.assertEqual(system_rows["P208"]["candidate_source"], "PEER_SIGNAL")
        self.assertIn("PEER_POPULARITY=HIGH", system_rows["P208"]["signals"])
        self.assertEqual(requested_rows["P209"]["features"]["peer_purchase_ratio"], "20%")
        self.assertIn("USER_REQUESTED", requested_rows["P209"]["signals"])

    def test_explicit_quantity_intent_reaches_safe_model_signals(self) -> None:
        rows = self.features_for(intent=self.intent(explicit_products=[{
            "sku": "P209",
            "quantity_intent": "HIGH",
        }]))

        self.assertEqual(rows["P209"]["features"]["quantity_intent"], "HIGH")
        self.assertIn("USER_QUANTITY_INTENT=HIGH", rows["P209"]["signals"])

    def test_event_baseline_fallback_order(self) -> None:
        cases = [
            ("C051", "STORE_EVENT"),
            ("C054", "PEER_EVENT"),
            ("C053", "RECENT_STORE"),
        ]
        for customer_id, expected in cases:
            with self.subTest(customer_id=customer_id):
                rows = self.features_for(
                    customer_id=customer_id,
                    intent=self.intent(explicit_products=[{"sku": "P212"}], occasion="CHRISTMAS"),
                    as_of_date="2026-12-10",
                )
                self.assertEqual(rows["P212"]["features"]["baseline_source"], expected)

    def test_model_feature_payload_contains_no_private_numeric_fields(self) -> None:
        row = self.features_for()["P204"]
        serialized_keys = {str(key).casefold() for key in row["features"]}
        forbidden = {"current_stock", "available_stock", "unit_price", "avg_cost", "quantity"}
        self.assertTrue(serialized_keys.isdisjoint(forbidden))


if __name__ == "__main__":
    unittest.main()
