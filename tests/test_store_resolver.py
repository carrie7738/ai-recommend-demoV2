import unittest

import pandas as pd

from services.store_resolver import StoreResolver


class StoreResolverTests(unittest.TestCase):
    def setUp(self) -> None:
        self.workbook = {
            "Customer": pd.DataFrame([
                {
                    "CustomerId": "C001",
                    "StoreName": "Cafe Store 001",
                    "Industry": "Cafe",
                    "Region": "Christchurch",
                    "StoreLevel": "Bronze",
                    "CustomerStage": "New",
                },
                {"CustomerId": "C002", "StoreName": "Cafe Store 002"},
                {"CustomerId": "C003", "StoreName": "Restaurant Store 003"},
            ]),
            "ConversationContext": pd.DataFrame([
                {"SessionId": "S001", "CustomerId": "C001"},
                {"SessionId": "S002", "CustomerId": "C002"},
            ]),
        }
        self.resolver = StoreResolver()

    def test_resolves_full_store_name_inside_natural_language(self) -> None:
        result = self.resolver.resolve(
            self.workbook,
            "For Cafe Store 001, prepare a replenishment plan for next week.",
        )
        self.assertTrue(result.is_found)
        self.assertEqual(result.customer_id, "C001")

    def test_resolves_store_id_case_insensitively(self) -> None:
        result = self.resolver.resolve(self.workbook, "For c001, budget is NZD 500.")
        self.assertTrue(result.is_found)
        self.assertEqual(result.customer_id, "C001")

    def test_requires_store_when_request_has_no_store_reference(self) -> None:
        result = self.resolver.resolve(self.workbook, "Budget NZD 500 for next week.")
        self.assertEqual(result.status, "missing")
        self.assertIn("Please include a store name or ID", result.message)

    def test_reports_unknown_store_reference(self) -> None:
        result = self.resolver.resolve(self.workbook, "For C999, budget is NZD 500.")
        self.assertEqual(result.status, "unknown")
        self.assertIn("could not find", result.message)

    def test_ignores_store_without_demo_context(self) -> None:
        result = self.resolver.resolve(self.workbook, "For Restaurant Store 003, budget is NZD 500.")
        self.assertEqual(result.status, "unknown")

    def test_builds_trusted_store_context_from_customer_master(self) -> None:
        context = self.resolver.build_store_context(self.workbook, "C001")
        self.assertEqual(context["StoreName"], "Cafe Store 001")
        self.assertEqual(context["StoreLevel"], "Bronze")
        self.assertEqual(context["CustomerStage"], "New")


if __name__ == "__main__":
    unittest.main()
