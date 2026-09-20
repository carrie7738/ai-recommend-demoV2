import unittest

import pandas as pd

from services.local_optimizer import LocalOptimizer
from services.runtime_trace import capture_trace


AS_OF = "2026-06-02"


def _workbook(inventory_rows: list[dict]) -> dict[str, pd.DataFrame]:
    return {
        "Customer": pd.DataFrame([{"CustomerId": "C1", "Industry": "Retail"}]),
        "Product": pd.DataFrame([
            {
                "ProductId": product_id,
                "ProductName": f"Product {product_id}",
                "AvgCost": 2.0,
                "SalesUnit": 2,
                "Unit": "pack",
                "IsSellable": True,
            }
            for product_id in ("P1", "P2")
        ]),
        "SupplyAvailability": pd.DataFrame([
            {"ProductId": product_id, "AvailableStock": 100}
            for product_id in ("P1", "P2")
        ]),
        "Inventory": pd.DataFrame(inventory_rows),
        "OrderHistory": pd.DataFrame([
            {
                "OrderId": f"O{product_id}",
                "CustomerId": "C1",
                "ProductId": product_id,
                "OrderDate": "2026-05-25",
                "Quantity": 20,
                "EventId": "",
            }
            for product_id in ("P1", "P2")
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


def _candidates() -> list[dict]:
    return [
        {
            "candidate_id": product_id,
            "product_name": f"Product {product_id}",
            "recommendation_type": "REPLENISHMENT",
            "candidate_source": "HISTORICAL_PURCHASE",
            "sales_unit": 2,
            "available_stock": 100,
            "features": {"baseline_source": "RECENT_STORE"},
        }
        for product_id in ("P1", "P2")
    ]


def _decision() -> dict:
    return {
        "candidate_decisions": [
            {
                "candidate_id": product_id,
                "recommended": True,
                "recommendation_type": "REPLENISHMENT",
                "priority": "HIGH",
                "replenishment_intensity": "MEDIUM",
                "decision_signals": ["TEST_SIGNAL"],
            }
            for product_id in ("P1", "P2")
        ]
    }


def _run(inventory_rows: list[dict]) -> dict:
    return LocalOptimizer().optimize(
        _workbook(inventory_rows),
        "C1",
        {"budget": None, "occasion": "NONE"},
        _candidates(),
        _decision(),
        AS_OF,
    )


class InventoryRegressionTests(unittest.TestCase):
    def test_missing_or_invalid_inventory_is_unallocated_and_other_skus_continue(self) -> None:
        cases = {
            "missing": [],
            "future_only": [{
                "CustomerId": "C1",
                "ProductId": "P1",
                "CurrentStock": 0,
                "LastUpdated": "2026-06-03",
            }],
            "nan": [{
                "CustomerId": "C1",
                "ProductId": "P1",
                "CurrentStock": float("nan"),
                "LastUpdated": "2026-06-01",
            }],
            "infinite": [{
                "CustomerId": "C1",
                "ProductId": "P1",
                "CurrentStock": float("inf"),
                "LastUpdated": "2026-06-01",
            }],
            "negative": [{
                "CustomerId": "C1",
                "ProductId": "P1",
                "CurrentStock": -1,
                "LastUpdated": "2026-06-01",
            }],
        }
        for case_name, p1_rows in cases.items():
            with self.subTest(case_name=case_name):
                result = _run(p1_rows + [{
                    "CustomerId": "C1",
                    "ProductId": "P2",
                    "CurrentStock": 0,
                    "LastUpdated": "2026-06-01",
                }])

                self.assertEqual(
                    [item["candidate_id"] for item in result["purchase_plan"]],
                    ["P2"],
                )
                self.assertEqual(
                    result["unallocated_candidates"],
                    [{"candidate_id": "P1", "reason": "INVENTORY_UNAVAILABLE"}],
                )

    def test_inventory_trace_marks_missing_evidence_and_skipped_allocation(self) -> None:
        with capture_trace() as trace:
            result = _run([{
                "CustomerId": "C1",
                "ProductId": "P1",
                "CurrentStock": -1,
                "LastUpdated": "2026-06-01",
            }, {
                "CustomerId": "C1",
                "ProductId": "P2",
                "CurrentStock": 0,
                "LastUpdated": "2026-06-01",
            }])

        self.assertEqual([item["candidate_id"] for item in result["purchase_plan"]], ["P2"])
        events = [
            event for event in trace["events"]
            if event.get("operation") == "candidate_allocation"
            and event.get("input", {}).get("candidate_id") == "P1"
        ]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["status"], "skipped")
        self.assertEqual(events[0]["reason"], "INVENTORY_UNAVAILABLE")
        self.assertEqual(
            events[0]["input"]["source_evidence"]["Inventory"]["calculation"]["evidence_status"],
            "missing",
        )

    def test_known_zero_inventory_remains_a_valid_stock_value(self) -> None:
        result = _run([{
            "CustomerId": "C1",
            "ProductId": "P1",
            "CurrentStock": 0,
            "LastUpdated": "2026-06-01",
        }, {
            "CustomerId": "C1",
            "ProductId": "P2",
            "CurrentStock": 0,
            "LastUpdated": "2026-06-01",
        }])

        self.assertEqual(
            [item["candidate_id"] for item in result["purchase_plan"]],
            ["P1", "P2"],
        )


if __name__ == "__main__":
    unittest.main()
