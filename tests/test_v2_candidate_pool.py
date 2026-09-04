from pathlib import Path
import unittest

import pandas as pd

from services.candidate_pool import CandidatePoolBuilder


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"


class V2CandidatePoolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = pd.read_excel(WORKBOOK_PATH, sheet_name=None, engine="openpyxl")
        cls.builder = CandidatePoolBuilder()

    @staticmethod
    def intent(
        *,
        hard_constraints=None,
        soft_preferences=None,
        explicit_products=None,
        occasion="NONE",
    ):
        return {
            "hard_constraints": hard_constraints or [],
            "soft_preferences": soft_preferences or [],
            "explicit_products": explicit_products or [],
            "occasion": occasion,
        }

    def build(self, customer_id="C051", intent=None, as_of_date="2026-06-02"):
        return self.builder.build(
            self.workbook,
            customer_id,
            intent or self.intent(),
            as_of_date,
        )

    def test_normal_replenishment_uses_purchase_history(self) -> None:
        candidate = self.build().find("P201")
        self.assertTrue(candidate["eligible"])
        self.assertEqual(candidate["recommendation_type"], "REPLENISHMENT")
        self.assertEqual(candidate["candidate_source"], "HISTORICAL_PURCHASE")

    def test_soft_preferences_do_not_filter_candidates(self) -> None:
        result = self.build(intent=self.intent(
            soft_preferences=[
                {"type": "SHELF_LIFE", "value": "LONG"},
                {"type": "CATEGORY", "value": "Fruit"},
            ]
        ))
        self.assertTrue(result.find("P206")["eligible"])
        self.assertTrue(result.find("P214")["eligible"])

    def test_hard_shelf_life_constraint_filters_short_life_product(self) -> None:
        result = self.build(intent=self.intent(hard_constraints=[{
            "type": "SHELF_LIFE",
            "operator": "REQUIRE_LEVEL",
            "value": "LONG",
        }]))
        self.assertEqual(result.find("P206")["rejection_code"], "HARD_CONSTRAINT_FILTER")
        self.assertTrue(result.find("P207")["eligible"])

    def test_hard_category_constraint_filters_other_categories(self) -> None:
        result = self.build(intent=self.intent(hard_constraints=[{
            "type": "CATEGORY",
            "operator": "INCLUDE_ONLY",
            "values": ["Fruit"],
        }]))
        self.assertEqual(result.find("P214")["rejection_code"], "HARD_CONSTRAINT_FILTER")

    def test_system_discovery_requires_configured_peer_ratio(self) -> None:
        result = self.build()
        accepted = result.find("P208")
        rejected = result.find("P209")

        self.assertTrue(accepted["eligible"])
        self.assertEqual(accepted["recommendation_type"], "DISCOVERY")
        self.assertEqual(accepted["candidate_source"], "PEER_SIGNAL")
        self.assertEqual(accepted["peer_purchase_ratio"], 0.4)
        self.assertIsNone(rejected)

    def test_user_requested_discovery_bypasses_peer_threshold(self) -> None:
        result = self.build(intent=self.intent(explicit_products=[{
            "sku": "P209",
            "quantity_intent": "NORMAL",
        }]))
        candidate = result.find("P209")

        self.assertTrue(candidate["eligible"])
        self.assertEqual(candidate["recommendation_type"], "DISCOVERY")
        self.assertEqual(candidate["candidate_source"], "USER_REQUESTED")
        self.assertEqual(candidate["peer_purchase_ratio"], 0.2)

    def test_user_requested_unsellable_product_is_rejected(self) -> None:
        result = self.build(intent=self.intent(explicit_products=[{"sku": "P213"}]))
        candidate = result.find("P213")

        self.assertFalse(candidate["eligible"])
        self.assertEqual(candidate["rejection_code"], "INELIGIBLE_CANDIDATE")

    def test_sales_unit_tail_stock_remains_eligible(self) -> None:
        candidate = self.build().find("P211")

        self.assertTrue(candidate["eligible"])
        self.assertEqual(candidate["sales_unit"], 6)
        self.assertEqual(candidate["available_stock"], 4)

    def test_holiday_does_not_reclassify_unpurchased_explicit_product(self) -> None:
        result = self.build(
            customer_id="C054",
            intent=self.intent(
                explicit_products=[{"sku": "P212"}],
                occasion="CHRISTMAS",
            ),
            as_of_date="2026-12-10",
        )
        candidate = result.find("P212")

        self.assertTrue(candidate["eligible"])
        self.assertEqual(candidate["recommendation_type"], "DISCOVERY")
        self.assertEqual(candidate["candidate_source"], "USER_REQUESTED")

    def test_missing_sales_unit_fails_closed(self) -> None:
        workbook = {name: frame.copy() for name, frame in self.workbook.items()}
        workbook["Product"].loc[
            workbook["Product"]["ProductId"].astype(str) == "P201", "SalesUnit"
        ] = None

        with self.assertRaisesRegex(ValueError, "SalesUnit is required"):
            self.builder.build(workbook, "C051", self.intent(), "2026-06-02")

    def test_fractional_sales_unit_fails_closed(self) -> None:
        workbook = {name: frame.copy() for name, frame in self.workbook.items()}
        workbook["Product"]["SalesUnit"] = workbook["Product"]["SalesUnit"].astype(float)
        workbook["Product"].loc[
            workbook["Product"]["ProductId"].astype(str) == "P201", "SalesUnit"
        ] = 1.5

        with self.assertRaisesRegex(ValueError, "positive integer"):
            self.builder.build(workbook, "C051", self.intent(), "2026-06-02")

    def test_future_supply_snapshot_is_not_used(self) -> None:
        workbook = {name: frame.copy() for name, frame in self.workbook.items()}
        current = workbook["SupplyAvailability"].loc[
            workbook["SupplyAvailability"]["ProductId"].astype(str) == "P201"
        ].iloc[-1].copy()
        expected_stock = float(current["AvailableStock"])
        current["AvailableStock"] = 0
        current["LastUpdated"] = "2027-01-01"
        workbook["SupplyAvailability"] = pd.concat(
            [workbook["SupplyAvailability"], pd.DataFrame([current])],
            ignore_index=True,
        )

        candidate = self.builder.build(
            workbook, "C051", self.intent(), "2026-06-02"
        ).find("P201")

        self.assertTrue(candidate["eligible"])
        self.assertEqual(candidate["available_stock"], expected_stock)


if __name__ == "__main__":
    unittest.main()
