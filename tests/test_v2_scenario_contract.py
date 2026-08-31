from pathlib import Path
import unittest

import pandas as pd

from services.candidate_pool import CandidatePoolBuilder
from services.decision_features import DecisionFeatureBuilder


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"


class V2ScenarioContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = pd.read_excel(WORKBOOK_PATH, sheet_name=None, engine="openpyxl")
        cls.scenarios = cls.workbook["V2TestScenarios"].set_index("ScenarioId")
        cls.expected = cls.workbook["V2ExpectedCandidates"]
        cls.candidate_builder = CandidatePoolBuilder()
        cls.feature_builder = DecisionFeatureBuilder()

    @staticmethod
    def _intent_for(scenario_id: str) -> dict:
        intent = {
            "hard_constraints": [],
            "soft_preferences": [],
            "category_preference": [],
            "explicit_products": [],
            "occasion": "NONE",
        }
        if scenario_id == "V2-006":
            intent["soft_preferences"] = [{"type": "SHELF_LIFE", "value": "LONG"}]
        elif scenario_id == "V2-007":
            intent["hard_constraints"] = [{
                "type": "SHELF_LIFE",
                "operator": "REQUIRE_LEVEL",
                "value": "LONG",
            }]
        elif scenario_id == "V2-008":
            intent["soft_preferences"] = [{"type": "CATEGORY", "value": "Fruit"}]
            intent["category_preference"] = ["Fruit"]
        elif scenario_id == "V2-009":
            intent["hard_constraints"] = [{
                "type": "CATEGORY",
                "operator": "INCLUDE_ONLY",
                "values": ["Fruit"],
            }]
        elif scenario_id in {"V2-011", "V2-012"}:
            intent["explicit_products"] = [{"sku": "P209", "quantity_intent": "NORMAL"}]
        elif scenario_id == "V2-013":
            intent["explicit_products"] = [{"sku": "P213", "quantity_intent": "NORMAL"}]
        elif scenario_id in {"V2-018", "V2-019", "V2-020"}:
            intent["explicit_products"] = [{"sku": "P212", "quantity_intent": "NORMAL"}]
            intent["occasion"] = "CHRISTMAS"
        return intent

    def test_excel_candidate_and_feature_expectations_for_tasks_2_and_3(self) -> None:
        grouped = self.expected.groupby("ScenarioId", sort=False)
        for scenario_id, expected_rows in grouped:
            scenario = self.scenarios.loc[scenario_id]
            intent = self._intent_for(scenario_id)
            pool = self.candidate_builder.build(
                self.workbook,
                str(scenario["CustomerId"]),
                intent,
                scenario["AsOfDate"],
            )
            features = {
                item["candidate_id"]: item
                for item in self.feature_builder.build(
                    self.workbook,
                    str(scenario["CustomerId"]),
                    intent,
                    pool.eligible_candidates,
                    scenario["AsOfDate"],
                )
            }

            for _, expected in expected_rows.iterrows():
                product_id = str(expected["ProductId"])
                with self.subTest(scenario_id=scenario_id, product_id=product_id):
                    candidate = pool.find(product_id)
                    expected_eligible = bool(expected["ExpectedEligibility"])
                    self.assertIsNotNone(candidate)
                    self.assertEqual(bool(candidate["eligible"]), expected_eligible)

                    expected_type = expected.get("ExpectedRecommendationType")
                    if pd.notna(expected_type):
                        self.assertEqual(candidate.get("recommendation_type"), str(expected_type))

                    expected_signals = expected.get("ExpectedFeatureSignals")
                    if pd.notna(expected_signals):
                        self.assertIn(product_id, features)
                        actual_signals = set(features[product_id]["signals"])
                        for signal in str(expected_signals).split("|"):
                            self.assertIn(signal, actual_signals)


if __name__ == "__main__":
    unittest.main()
