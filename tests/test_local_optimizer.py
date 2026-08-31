from __future__ import annotations

import unittest

import pandas as pd

from services.local_optimizer import LocalOptimizer, OptimizerPolicy


def workbook(
    *,
    available: dict[str, int] | None = None,
    current: dict[str, int] | None = None,
    costs: dict[str, float] | None = None,
    sales_units: dict[str, int] | None = None,
) -> dict[str, pd.DataFrame]:
    product_ids = ["P1", "P2", "P3"]
    available = available or {"P1": 100, "P2": 100, "P3": 100}
    current = current or {"P1": 0, "P2": 0, "P3": 0}
    costs = costs or {"P1": 2.0, "P2": 3.0, "P3": 4.0}
    sales_units = sales_units or {"P1": 6, "P2": 4, "P3": 2}
    return {
        "Customer": pd.DataFrame([
            {"CustomerId": "C1", "Industry": "Retail"},
            {"CustomerId": "C2", "Industry": "Retail"},
        ]),
        "Product": pd.DataFrame([
            {
                "ProductId": product_id,
                "ProductName": f"Product {product_id}",
                "AvgCost": costs[product_id],
                "SalesUnit": sales_units[product_id],
                "Unit": "pack",
                "IsSellable": True,
            }
            for product_id in product_ids
        ]),
        "SupplyAvailability": pd.DataFrame([
            {"ProductId": product_id, "AvailableStock": available[product_id]}
            for product_id in product_ids
        ]),
        "Inventory": pd.DataFrame([
            {
                "CustomerId": "C1",
                "ProductId": product_id,
                "CurrentStock": current[product_id],
                "LastUpdated": "2026-06-01",
            }
            for product_id in product_ids
        ]),
        "OrderHistory": pd.DataFrame([
            {
                "OrderId": "O1",
                "CustomerId": "C1",
                "ProductId": "P1",
                "OrderDate": "2026-05-25",
                "Quantity": 90,
                "EventId": "",
            },
            {
                "OrderId": "O2",
                "CustomerId": "C1",
                "ProductId": "P3",
                "OrderDate": "2025-12-15",
                "Quantity": 20,
                "EventId": "EV_XMAS_2025",
            },
            {
                "OrderId": "O3",
                "CustomerId": "C2",
                "ProductId": "P3",
                "OrderDate": "2025-12-15",
                "Quantity": 30,
                "EventId": "EV_XMAS_2025",
            },
        ]),
        "EventConfig": pd.DataFrame([
            {
                "EventId": "EV_XMAS_2026",
                "EventName": "Christmas 2026",
                "EventWindowStart": "2026-12-10",
                "EventWindowEnd": "2026-12-24",
                "ComparableEventId": "EV_XMAS_2025",
            }
        ]),
    }


def candidates(*product_ids: str) -> list[dict]:
    sales_units = {"P1": 6, "P2": 4, "P3": 2}
    return [
        {
            "candidate_id": product_id,
            "product_name": f"Product {product_id}",
            "recommendation_type": "REPLENISHMENT",
            "candidate_source": "HISTORICAL_PURCHASE",
            "sales_unit": sales_units[product_id],
            "available_stock": 100,
            "features": {"baseline_source": "RECENT_STORE"},
        }
        for product_id in product_ids
    ]


def decision(*rows: tuple[str, str, str, str]) -> dict:
    return {
        "candidate_decisions": [
            {
                "candidate_id": product_id,
                "recommended": True,
                "recommendation_type": recommendation_type,
                "priority": priority,
                "replenishment_intensity": intensity,
                "decision_signals": ["TEST_SIGNAL"],
            }
            for product_id, recommendation_type, priority, intensity in rows
        ]
    }


class LocalOptimizerTests(unittest.TestCase):
    def test_replenishment_applies_intensity_then_sales_unit(self) -> None:
        result = LocalOptimizer().optimize(
            workbook(),
            "C1",
            {"budget": None, "occasion": "NONE"},
            candidates("P1"),
            decision(("P1", "REPLENISHMENT", "HIGH", "HIGH")),
            "2026-06-02",
        )

        item = result["purchase_plan"][0]
        self.assertEqual(item["final_qty"], 18)
        self.assertIn("SALES_UNIT_ROUNDED", item["constraint_adjustments"])

    def test_available_stock_caps_at_complete_sales_unit(self) -> None:
        data = workbook(available={"P1": 10, "P2": 100, "P3": 100})
        raw_candidates = candidates("P1")
        raw_candidates[0]["available_stock"] = 10
        result = LocalOptimizer().optimize(
            data,
            "C1",
            {"budget": None, "occasion": "NONE"},
            raw_candidates,
            decision(("P1", "REPLENISHMENT", "HIGH", "HIGH")),
            "2026-06-02",
        )

        self.assertEqual(result["purchase_plan"][0]["final_qty"], 6)
        self.assertIn("AVAILABLE_STOCK_CAPPED", result["purchase_plan"][0]["constraint_adjustments"])

    def test_tail_stock_below_sales_unit_can_be_bought_once(self) -> None:
        data = workbook(available={"P1": 4, "P2": 100, "P3": 100})
        raw_candidates = candidates("P1")
        raw_candidates[0]["available_stock"] = 4
        result = LocalOptimizer().optimize(
            data,
            "C1",
            {"budget": None, "occasion": "NONE"},
            raw_candidates,
            decision(("P1", "REPLENISHMENT", "HIGH", "MEDIUM")),
            "2026-06-02",
        )

        self.assertEqual(result["purchase_plan"][0]["final_qty"], 4)
        self.assertIn("TAIL_STOCK_EXCEPTION", result["purchase_plan"][0]["constraint_adjustments"])

    def test_budget_reduces_quantity_by_sales_unit(self) -> None:
        result = LocalOptimizer().optimize(
            workbook(),
            "C1",
            {"budget": 15.0, "occasion": "NONE"},
            candidates("P1"),
            decision(("P1", "REPLENISHMENT", "HIGH", "HIGH")),
            "2026-06-02",
        )

        self.assertEqual(result["purchase_plan"][0]["final_qty"], 6)
        self.assertEqual(result["total_cost"], 12.0)
        self.assertIn("BUDGET_CAPPED", result["purchase_plan"][0]["constraint_adjustments"])

    def test_budget_allocation_follows_ai_priority(self) -> None:
        data = workbook(costs={"P1": 2.0, "P2": 3.0, "P3": 4.0})
        raw_candidates = candidates("P1", "P2")
        raw_candidates[1]["recommendation_type"] = "DISCOVERY"
        raw_candidates[1]["candidate_source"] = "PEER_SIGNAL"
        result = LocalOptimizer().optimize(
            data,
            "C1",
            {"budget": 12.0, "occasion": "NONE"},
            raw_candidates,
            decision(
                ("P2", "DISCOVERY", "LOW", "MEDIUM"),
                ("P1", "REPLENISHMENT", "HIGH", "MEDIUM"),
            ),
            "2026-06-02",
        )

        self.assertEqual([item["candidate_id"] for item in result["purchase_plan"]], ["P1"])
        self.assertEqual(result["unallocated_candidates"], [{"candidate_id": "P2", "reason": "BUDGET_CONFLICT"}])

    def test_system_discovery_uses_one_configured_trial_sales_unit(self) -> None:
        raw_candidates = candidates("P2")
        raw_candidates[0]["recommendation_type"] = "DISCOVERY"
        raw_candidates[0]["candidate_source"] = "PEER_SIGNAL"
        result = LocalOptimizer().optimize(
            workbook(),
            "C1",
            {"budget": None, "occasion": "NONE"},
            raw_candidates,
            decision(("P2", "DISCOVERY", "MEDIUM", "MEDIUM")),
            "2026-06-02",
        )

        self.assertEqual(result["purchase_plan"][0]["baseline_source"], "DISCOVERY_TRIAL")
        self.assertEqual(result["purchase_plan"][0]["final_qty"], 4)

    def test_holiday_prefers_comparable_store_event_baseline(self) -> None:
        data = workbook(current={"P1": 0, "P2": 0, "P3": 5})
        raw_candidates = candidates("P3")
        raw_candidates[0]["features"]["baseline_source"] = "STORE_EVENT"
        result = LocalOptimizer().optimize(
            data,
            "C1",
            {"budget": None, "occasion": "CHRISTMAS"},
            raw_candidates,
            decision(("P3", "REPLENISHMENT", "HIGH", "MEDIUM")),
            "2026-12-10",
        )

        self.assertEqual(result["purchase_plan"][0]["baseline_source"], "STORE_EVENT")
        self.assertEqual(result["purchase_plan"][0]["final_qty"], 16)

    def test_optimizer_policy_is_injectable_for_evaluation(self) -> None:
        optimizer = LocalOptimizer(
            OptimizerPolicy(
                coverage_period_days=7,
                demand_history_days=90,
                intensity_factors={"HIGH": 2.0, "MEDIUM": 1.0, "LOW": 0.5},
                discovery_trial_sales_units=2,
            )
        )
        raw_candidates = candidates("P2")
        raw_candidates[0]["recommendation_type"] = "DISCOVERY"
        result = optimizer.optimize(
            workbook(),
            "C1",
            {"budget": None, "occasion": "NONE"},
            raw_candidates,
            decision(("P2", "DISCOVERY", "MEDIUM", "MEDIUM")),
            "2026-06-02",
        )

        self.assertEqual(result["purchase_plan"][0]["final_qty"], 8)
        self.assertEqual(result["evaluation_parameters"]["coverage_period_days"], 7)


if __name__ == "__main__":
    unittest.main()
