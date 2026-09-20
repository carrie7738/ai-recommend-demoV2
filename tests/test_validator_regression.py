from __future__ import annotations

import math
import unittest

import pandas as pd

from services.hard_validator import HardValidationError, HardValidator


def workbook(*, sales_unit: object = 6, avg_cost: object = 2.0) -> dict[str, pd.DataFrame]:
    product = {"ProductId": "P1", "IsSellable": True, "SalesUnit": sales_unit, "AvgCost": avg_cost}
    if avg_cost is _MISSING:
        product.pop("AvgCost")
    return {
        "Product": pd.DataFrame([product]),
        "SupplyAvailability": pd.DataFrame([
            {"ProductId": "P1", "AvailableStock": 20},
        ]),
    }


_MISSING = object()


def plan(*, quantity: object = 6, sales_unit: object = 6) -> dict:
    return {
        "purchase_plan": [{
            "candidate_id": "P1",
            "final_qty": quantity,
            "sales_unit": sales_unit,
        }],
        "unallocated_candidates": [],
        "total_cost": 12.0,
    }


class ValidatorRegressionTests(unittest.TestCase):
    candidates = [{"candidate_id": "P1"}]
    ai_decision = {"candidate_decisions": []}

    def test_validate_uses_product_sales_unit_instead_of_optimizer_pack(self) -> None:
        result = HardValidator().validate(
            workbook(),
            {"budget": None},
            self.candidates,
            self.ai_decision,
            plan(quantity=1, sales_unit=1),
        )

        self.assertFalse(result["valid"])
        self.assertIn(
            "SALES_UNIT_METADATA_MISMATCH",
            {item["code"] for item in result["violations"]},
        )
        self.assertIn(
            "SALES_UNIT_VIOLATION",
            {item["code"] for item in result["violations"]},
        )

    def test_repair_rewrites_trusted_pack_before_rechecking_quantity_and_cost(self) -> None:
        validator = HardValidator()
        original = plan(quantity=6, sales_unit=1)
        failed = validator.validate(
            workbook(),
            {"budget": None},
            self.candidates,
            self.ai_decision,
            original,
        )

        repaired = validator.repair(
            workbook(),
            {"budget": None},
            original,
            failed["violations"],
        )
        revalidated = validator.validate(
            workbook(),
            {"budget": None},
            self.candidates,
            self.ai_decision,
            repaired,
        )

        self.assertEqual(repaired["purchase_plan"][0]["sales_unit"], 6)
        self.assertEqual(repaired["purchase_plan"][0]["final_qty"], 6)
        self.assertEqual(repaired["purchase_plan"][0]["unit_cost"], 2.0)
        self.assertEqual(repaired["purchase_plan"][0]["estimated_cost"], 12.0)
        self.assertEqual(repaired["total_cost"], 12.0)
        self.assertEqual(revalidated["status"], "PASS")

    def test_validate_rejects_non_integer_quantity(self) -> None:
        result = HardValidator().validate(
            workbook(),
            {"budget": None},
            self.candidates,
            self.ai_decision,
            plan(quantity=6.5),
        )

        self.assertFalse(result["valid"])
        self.assertIn(
            "NON_INTEGER_QTY",
            {item["code"] for item in result["violations"]},
        )

    def test_invalid_product_sales_unit_is_a_hard_validation_error(self) -> None:
        for value in (None, 0, -1, 1.5, math.inf):
            with self.subTest(value=value):
                data = workbook(sales_unit=value)
                with self.assertRaises(HardValidationError):
                    HardValidator().validate(
                        data,
                        {"budget": None},
                        self.candidates,
                        self.ai_decision,
                        plan(),
                    )
                with self.assertRaises(HardValidationError):
                    HardValidator().repair(
                        data,
                        {"budget": None},
                        plan(),
                        [{"code": "SALES_UNIT_METADATA_MISMATCH", "repairable_locally": True}],
                    )

    def test_invalid_product_avg_cost_is_a_hard_validation_error(self) -> None:
        for value in (_MISSING, -1.0, math.inf):
            with self.subTest(value=value):
                data = workbook(avg_cost=value)
                with self.assertRaises(HardValidationError):
                    HardValidator().validate(
                        data,
                        {"budget": None},
                        self.candidates,
                        self.ai_decision,
                        plan(),
                    )
                with self.assertRaises(HardValidationError):
                    HardValidator().repair(
                        data,
                        {"budget": None},
                        plan(),
                        [{"code": "SALES_UNIT_METADATA_MISMATCH", "repairable_locally": True}],
                    )

    def test_cost_metadata_mismatch_is_repaired_without_a_budget_violation(self) -> None:
        validator = HardValidator()
        original = {
            "purchase_plan": [{
                "candidate_id": "P1",
                "final_qty": 6,
                "sales_unit": 6,
                "unit_cost": 0.01,
                "estimated_cost": 0.06,
            }],
            "unallocated_candidates": [],
            "total_cost": 0.06,
            "remaining_budget": 99.94,
        }

        failed = validator.validate(
            workbook(),
            {"budget": None},
            self.candidates,
            self.ai_decision,
            original,
        )
        self.assertIn(
            "COST_METADATA_MISMATCH",
            {item["code"] for item in failed["violations"]},
        )

        repaired = validator.repair(
            workbook(),
            {"budget": None},
            original,
            failed["violations"],
        )
        revalidated = validator.validate(
            workbook(),
            {"budget": None},
            self.candidates,
            self.ai_decision,
            repaired,
        )

        self.assertEqual(repaired["purchase_plan"][0]["unit_cost"], 2.0)
        self.assertEqual(repaired["purchase_plan"][0]["estimated_cost"], 12.0)
        self.assertEqual(repaired["total_cost"], 12.0)
        self.assertIsNone(repaired["remaining_budget"])
        self.assertEqual(revalidated["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
