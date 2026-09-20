from __future__ import annotations

import json
import unittest

import pandas as pd

from services.ai_decision import AIDecisionError, AIDecisionLayer
from services.hard_validator import HardValidator
from services.v2_decision_pipeline import V2DecisionPipeline
from tests.test_local_optimizer import candidates as optimizer_candidates
from tests.test_local_optimizer import workbook as optimizer_workbook


def validator_workbook() -> dict[str, pd.DataFrame]:
    return {
        "Product": pd.DataFrame([
            {"ProductId": "P1", "IsSellable": True, "AvgCost": 2.0, "SalesUnit": 6},
            {"ProductId": "P2", "IsSellable": True, "AvgCost": 3.0, "SalesUnit": 6},
        ]),
        "SupplyAvailability": pd.DataFrame([
            {"ProductId": "P1", "AvailableStock": 20},
            {"ProductId": "P2", "AvailableStock": 4},
        ]),
    }


def ai_decision() -> dict:
    return {
        "procurement_strategy": {
            "primary_objective": "PREVENT_STOCKOUT",
            "primary_signals": ["STOCKOUT_RISK=HIGH"],
            "secondary_signals": [],
            "strategy_summary": "Protect priority replenishment.",
        },
        "candidate_decisions": [
            {
                "candidate_id": "P1",
                "recommended": True,
                "recommendation_type": "REPLENISHMENT",
                "priority": "HIGH",
                "replenishment_intensity": "HIGH",
                "decision_signals": ["STOCKOUT_RISK=HIGH"],
            },
            {
                "candidate_id": "P2",
                "recommended": True,
                "recommendation_type": "DISCOVERY",
                "priority": "HIGH",
                "replenishment_intensity": "LOW",
                "decision_signals": ["USER_REQUESTED"],
            },
        ],
    }


class HardValidatorTests(unittest.TestCase):
    candidates = [{"candidate_id": "P1"}, {"candidate_id": "P2"}]

    def test_valid_plan_passes_sales_unit_stock_and_budget(self) -> None:
        result = HardValidator().validate(
            validator_workbook(),
            {"budget": 30.0},
            self.candidates,
            ai_decision(),
            {
                "purchase_plan": [
                    {"candidate_id": "P1", "final_qty": 6, "sales_unit": 6},
                    {"candidate_id": "P2", "final_qty": 4, "sales_unit": 6},
                ],
                "unallocated_candidates": [],
                "total_cost": 24.0,
            },
        )

        self.assertTrue(result["valid"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["violations"], [])

    def test_validator_detects_local_constraint_violations(self) -> None:
        result = HardValidator().validate(
            validator_workbook(),
            {"budget": 10.0},
            self.candidates,
            ai_decision(),
            {
                "purchase_plan": [
                    {"candidate_id": "P1", "final_qty": 25, "sales_unit": 6},
                ],
                "unallocated_candidates": [],
                "total_cost": 12.0,
            },
        )

        codes = {item["code"] for item in result["violations"]}
        self.assertEqual(
            codes,
            {
                "AVAILABLE_STOCK_EXCEEDED",
                "SALES_UNIT_VIOLATION",
                "COST_METADATA_MISMATCH",
                "BUDGET_EXCEEDED",
            },
        )
        self.assertFalse(result["requires_model_retry"])
        self.assertEqual(result["status"], "FAIL")

    def test_deterministic_repair_fixes_stock_sales_unit_and_budget_then_passes(self) -> None:
        validator = HardValidator()
        original = {
            "purchase_plan": [
                {
                    "candidate_id": "P1", "final_qty": 25, "sales_unit": 6,
                    "priority": "HIGH", "unit_cost": 2.0, "estimated_cost": 50.0,
                    "constraint_adjustments": [],
                }
            ],
            "unallocated_candidates": [],
            "total_cost": 50.0,
            "remaining_budget": 0.0,
        }
        failed = validator.validate(
            validator_workbook(), {"budget": 20.0}, self.candidates, ai_decision(), original
        )

        repaired = validator.repair(
            validator_workbook(), {"budget": 20.0}, original, failed["violations"]
        )
        revalidated = validator.validate(
            validator_workbook(), {"budget": 20.0}, self.candidates, ai_decision(), repaired
        )

        self.assertTrue(repaired["repair_applied"])
        self.assertEqual(repaired["purchase_plan"][0]["final_qty"], 6)
        self.assertEqual(repaired["total_cost"], 12.0)
        self.assertEqual(revalidated["status"], "PASS")

    def test_repair_uses_same_as_of_supply_snapshot_as_validate(self) -> None:
        validator = HardValidator()
        data = validator_workbook()
        data["SupplyAvailability"] = pd.DataFrame([
            {"ProductId": "P1", "AvailableStock": 100, "LastUpdated": "2026-06-03"},
            {"ProductId": "P1", "AvailableStock": 2, "LastUpdated": "2026-06-02"},
            {"ProductId": "P1", "AvailableStock": 20, "LastUpdated": "2026-05-30"},
            {"ProductId": "P2", "AvailableStock": 4, "LastUpdated": "2026-06-02"},
        ])
        original = {
            "purchase_plan": [{
                "candidate_id": "P1",
                "final_qty": 18,
                "sales_unit": 6,
                "unit_cost": 2.0,
                "estimated_cost": 36.0,
            }],
            "unallocated_candidates": [],
            "total_cost": 36.0,
        }
        failed = validator.validate(
            data,
            {"budget": None},
            self.candidates,
            ai_decision(),
            original,
            as_of_date="2026-06-02",
        )

        repaired = validator.repair(
            data,
            {"budget": None},
            original,
            failed["violations"],
            as_of_date="2026-06-02",
        )
        revalidated = validator.validate(
            data,
            {"budget": None},
            self.candidates,
            ai_decision(),
            repaired,
            as_of_date="2026-06-02",
        )

        self.assertEqual(repaired["purchase_plan"][0]["final_qty"], 2)
        self.assertEqual(revalidated["status"], "PASS")

    def test_repair_reconciles_forged_cost_metadata_using_product_avg_cost(self) -> None:
        validator = HardValidator()
        for forged_unit_cost in (0.01, 100.0):
            with self.subTest(forged_unit_cost=forged_unit_cost):
                original = {
                    "purchase_plan": [{
                        "candidate_id": "P1",
                        "final_qty": 12,
                        "sales_unit": 6,
                        "unit_cost": forged_unit_cost,
                        "estimated_cost": round(12 * forged_unit_cost, 2),
                    }],
                    "unallocated_candidates": [],
                    "total_cost": round(12 * forged_unit_cost, 2),
                    "remaining_budget": 0.0,
                }
                failed = validator.validate(
                    validator_workbook(),
                    {"budget": 20.0},
                    self.candidates,
                    ai_decision(),
                    original,
                )

                repaired = validator.repair(
                    validator_workbook(),
                    {"budget": 20.0},
                    original,
                    failed["violations"],
                )
                revalidated = validator.validate(
                    validator_workbook(),
                    {"budget": 20.0},
                    self.candidates,
                    ai_decision(),
                    repaired,
                )
                item = repaired["purchase_plan"][0]
                self.assertEqual(item["final_qty"], 6)
                self.assertEqual(item["unit_cost"], 2.0)
                self.assertEqual(item["estimated_cost"], 12.0)
                self.assertEqual(repaired["total_cost"], 12.0)
                self.assertEqual(repaired["remaining_budget"], 8.0)
                self.assertEqual(revalidated["status"], "PASS")

    def test_repair_marks_metadata_only_correction_as_applied(self) -> None:
        validator = HardValidator()
        original = {
            "purchase_plan": [{
                "candidate_id": "P1",
                "final_qty": 6,
                "sales_unit": 6,
                "unit_cost": 100.0,
                "estimated_cost": 600.0,
            }],
            "unallocated_candidates": [],
            "total_cost": 600.0,
            "remaining_budget": None,
        }

        repaired = validator.repair(
            validator_workbook(),
            {"budget": None},
            original,
            [{"code": "SALES_UNIT_VIOLATION", "repairable_locally": True}],
        )

        self.assertTrue(repaired["repair_applied"])
        self.assertEqual(repaired["purchase_plan"][0]["final_qty"], 6)
        self.assertEqual(repaired["purchase_plan"][0]["unit_cost"], 2.0)
        self.assertEqual(repaired["purchase_plan"][0]["estimated_cost"], 12.0)
        self.assertEqual(repaired["total_cost"], 12.0)

    def test_nonrepairable_violation_remains_failed(self) -> None:
        validator = HardValidator()
        original = {
            "purchase_plan": [{"candidate_id": "P999", "final_qty": 6, "sales_unit": 6}],
            "unallocated_candidates": [], "total_cost": 0.0,
        }
        failed = validator.validate(
            validator_workbook(), {"budget": None}, self.candidates, ai_decision(), original
        )
        repaired = validator.repair(
            validator_workbook(), {"budget": None}, original, failed["violations"]
        )
        revalidated = validator.validate(
            validator_workbook(), {"budget": None}, self.candidates, ai_decision(), repaired
        )

        self.assertFalse(repaired["repair_applied"])
        self.assertEqual(revalidated["status"], "FAIL")

    def test_high_priority_budget_conflict_creates_sanitized_retry_feedback(self) -> None:
        result = HardValidator().validate(
            validator_workbook(),
            {"budget": 10.0},
            self.candidates,
            ai_decision(),
            {
                "purchase_plan": [{"candidate_id": "P1", "final_qty": 6, "sales_unit": 6}],
                "unallocated_candidates": [
                    {"candidate_id": "P2", "reason": "BUDGET_CONFLICT"}
                ],
                "total_cost": 10.0,
            },
        )

        self.assertTrue(result["requires_model_retry"])
        self.assertEqual(result["retry_feedback"]["type"], "BUDGET_CONFLICT")
        self.assertEqual(result["retry_feedback"]["affected_candidates"], ["P2"])
        serialized = json.dumps(result["retry_feedback"]).casefold()
        for forbidden in ["price", "cost", "difference", "remaining", "severity", "constraint_level"]:
            self.assertNotIn(forbidden, serialized)

    def test_partial_budget_cap_is_a_local_optimizer_outcome(self) -> None:
        result = HardValidator().validate(
            validator_workbook(),
            {"budget": 12.0},
            self.candidates,
            ai_decision(),
            {
                "purchase_plan": [{
                    "candidate_id": "P1",
                    "final_qty": 6,
                    "sales_unit": 6,
                    "constraint_adjustments": ["BUDGET_CAPPED"],
                }],
                "unallocated_candidates": [],
                "total_cost": 12.0,
            },
        )

        self.assertFalse(result["requires_model_retry"])
        self.assertTrue(result["valid"])

    def test_budget_is_recomputed_from_product_master_not_optimizer_total(self) -> None:
        result = HardValidator().validate(
            validator_workbook(),
            {"budget": 10.0},
            self.candidates,
            ai_decision(),
            {
                "purchase_plan": [
                    {"candidate_id": "P1", "final_qty": 6, "sales_unit": 6},
                ],
                "unallocated_candidates": [],
                "total_cost": 1.0,
            },
        )

        self.assertEqual(result["validated_total_cost"], 12.0)
        self.assertIn("BUDGET_EXCEEDED", {item["code"] for item in result["violations"]})


class RetryDecisionTests(unittest.TestCase):
    safe_context = {
        "structured_intent": {
            "objective": "PREVENT_STOCKOUT",
            "traffic_expectation": "NORMAL",
            "occasion": "NONE",
            "budget": 10.0,
        },
        "candidates": [
            {
                "candidate_id": "P1",
                "recommendation_type": "REPLENISHMENT",
                "signals": ["STOCKOUT_RISK=HIGH"],
            },
            {
                "candidate_id": "P2",
                "recommendation_type": "DISCOVERY",
                "signals": ["USER_REQUESTED"],
            },
        ],
    }

    def test_retry_sends_only_approved_constraint_feedback(self) -> None:
        previous = ai_decision()

        class RetryClient:
            is_available = True

            def __init__(self):
                self.model_input = None

            def chat_completion_json(self, messages):
                self.model_input = json.loads(messages[-1]["content"])
                retried = json.loads(json.dumps(previous))
                retried["candidate_decisions"][0]["priority"] = "MEDIUM"
                retried["candidate_decisions"][1]["recommended"] = False
                retried["candidate_decisions"][1]["priority"] = "LOW"
                return retried

        client = RetryClient()
        result = AIDecisionLayer(ai_client=client).retry_decision(
            self.safe_context,
            previous,
            {
                "type": "BUDGET_CONFLICT",
                "affected_candidates": ["P1", "P2"],
                "reason": "The current candidate combination cannot be supported within the available budget.",
                "required_action": "Re-evaluate candidate priorities.",
            },
        )

        self.assertFalse(result["candidate_decisions"][1]["recommended"])
        self.assertEqual(
            set(client.model_input["constraint_feedback"]),
            {"type", "affected_candidates", "reason", "required_action"},
        )

    def test_retry_rejects_constraint_severity(self) -> None:
        feedback = {
            "type": "BUDGET_CONFLICT",
            "affected_candidates": ["P1", "P2"],
            "reason": "Conflict.",
            "required_action": "Re-evaluate.",
            "constraint_level": "SEVERE",
        }

        with self.assertRaisesRegex(AIDecisionError, "approved contract"):
            AIDecisionLayer(ai_client=type("Client", (), {"is_available": True})()).retry_decision(
                self.safe_context,
                ai_decision(),
                feedback,
            )


class RetryPipelineTests(unittest.TestCase):
    def test_validation_failure_is_hard_gate_for_final_purchase_plan(self) -> None:
        raw_candidates = optimizer_candidates("P1")
        safe_candidates = [{
            "candidate_id": "P1",
            "recommendation_type": "REPLENISHMENT",
            "candidate_source": "STORE_HISTORY",
            "features": {"baseline_source": "RECENT_STORE"},
            "signals": ["STOCKOUT_RISK=HIGH"],
        }]

        class Preparation:
            @staticmethod
            def prepare(*args, **kwargs):
                return {
                    "intent": {},
                    "candidate_pool": {"eligible_candidates": raw_candidates, "rejected_candidates": []},
                    "safe_decision_context": {
                        "structured_intent": {
                            "objective": "PREVENT_STOCKOUT", "occasion": "NONE",
                            "traffic_expectation": "NORMAL", "budget": None,
                        },
                        "candidates": safe_candidates,
                    },
                }

        class DecisionLayer:
            @staticmethod
            def decide(context):
                decision = ai_decision()
                decision["candidate_decisions"] = decision["candidate_decisions"][:1]
                return decision

        class InvalidOptimizer:
            @staticmethod
            def optimize(**kwargs):
                return {
                    "purchase_plan": [{
                        "candidate_id": "P999", "final_qty": 6, "sales_unit": 6,
                        "unit_cost": 1.0, "estimated_cost": 25.0,
                    }],
                    "unallocated_candidates": [], "total_cost": 25.0,
                    "remaining_budget": None,
                }

        result = V2DecisionPipeline(
            preparation=Preparation(),
            decision_layer=DecisionLayer(),
            optimizer=InvalidOptimizer(),
        ).run(optimizer_workbook(), "C1", "Protect priority stock.", "2026-06-02")

        self.assertEqual(result["validation_result"]["status"], "FAIL")
        self.assertEqual(result["final_purchase_plan"], [])
        self.assertEqual(result["decision_trace"]["final_result"]["status"], "VALIDATION_FAILED")

    def test_pipeline_retries_once_then_reoptimizes_and_revalidates(self) -> None:
        raw_candidates = optimizer_candidates("P1", "P2")
        raw_candidates[1]["recommendation_type"] = "DISCOVERY"
        raw_candidates[1]["candidate_source"] = "PEER_SIGNAL"
        safe_candidates = [
            {
                "candidate_id": item["candidate_id"],
                "recommendation_type": item["recommendation_type"],
                "candidate_source": item["candidate_source"],
                "features": {"baseline_source": "RECENT_STORE"},
                "signals": ["STOCKOUT_RISK=HIGH"] if item["candidate_id"] == "P1" else ["USER_REQUESTED"],
            }
            for item in raw_candidates
        ]

        class Preparation:
            @staticmethod
            def prepare(*args, **kwargs):
                return {
                    "intent": {},
                    "candidate_pool": {
                        "eligible_candidates": raw_candidates,
                        "rejected_candidates": [],
                    },
                    "safe_decision_context": {
                        "structured_intent": {
                            "objective": "PREVENT_STOCKOUT",
                            "occasion": "NONE",
                            "traffic_expectation": "NORMAL",
                            "budget": 12.0,
                        },
                        "candidates": safe_candidates,
                    },
                }

        first = ai_decision()

        class DecisionLayer:
            retry_calls = 0

            @staticmethod
            def decide(context):
                return first

            def retry_decision(self, context, previous, feedback):
                self.retry_calls += 1
                retried = json.loads(json.dumps(previous))
                retried["candidate_decisions"][0]["priority"] = "MEDIUM"
                retried["candidate_decisions"][1]["recommended"] = False
                retried["candidate_decisions"][1]["priority"] = "LOW"
                return retried

        layer = DecisionLayer()
        result = V2DecisionPipeline(
            preparation=Preparation(),
            decision_layer=layer,
        ).run(
            optimizer_workbook(),
            "C1",
            "Protect priority stock.",
            "2026-06-02",
        )

        self.assertEqual(layer.retry_calls, 1)
        self.assertEqual(result["retry_count"], 1)
        self.assertTrue(result["validation_result"]["valid"])
        self.assertEqual(
            [item["candidate_id"] for item in result["final_purchase_plan"]],
            ["P1"],
        )

    def test_pipeline_passes_effective_as_of_to_both_retry_repair_points(self) -> None:
        raw_candidates = optimizer_candidates("P1", "P2")
        safe_candidates = [{
            "candidate_id": item["candidate_id"],
            "recommendation_type": item["recommendation_type"],
            "candidate_source": item["candidate_source"],
            "features": {"baseline_source": "RECENT_STORE"},
            "signals": ["STOCKOUT_RISK=HIGH"],
        } for item in raw_candidates]
        effective_date = pd.Timestamp("2026-12-10")

        class Preparation:
            @staticmethod
            def prepare(*args, **kwargs):
                return {
                    "intent": {},
                    "effective_as_of_date": effective_date,
                    "candidate_pool": {
                        "eligible_candidates": raw_candidates,
                        "rejected_candidates": [],
                    },
                    "safe_decision_context": {
                        "structured_intent": {
                            "objective": "PREVENT_STOCKOUT",
                            "occasion": "NONE",
                            "traffic_expectation": "NORMAL",
                            "budget": 12.0,
                        },
                        "candidates": safe_candidates,
                    },
                }

        class DecisionLayer:
            retry_calls = 0

            @staticmethod
            def decide(context):
                return ai_decision()

            def retry_decision(self, context, previous, feedback):
                self.retry_calls += 1
                return json.loads(json.dumps(previous))

        class TwoInvalidResultsOptimizer:
            calls = 0

            @classmethod
            def optimize(cls, **kwargs):
                cls.calls += 1
                quantity = 25 if cls.calls == 1 else 7
                return {
                    "purchase_plan": [{
                        "candidate_id": "P1",
                        "final_qty": quantity,
                        "sales_unit": 6,
                        "unit_cost": 2.0,
                        "estimated_cost": quantity * 2.0,
                    }],
                    "unallocated_candidates": (
                        [{"candidate_id": "P2", "reason": "BUDGET_CONFLICT"}]
                        if cls.calls == 1 else []
                    ),
                    "total_cost": quantity * 2.0,
                    "remaining_budget": 0.0,
                }

        class RecordingValidator(HardValidator):
            def __init__(self):
                super().__init__()
                self.validate_dates = []
                self.repair_dates = []

            def validate(self, *args, **kwargs):
                self.validate_dates.append(kwargs.get("as_of_date"))
                return super().validate(*args, **kwargs)

            def repair(self, *args, **kwargs):
                self.repair_dates.append(kwargs.get("as_of_date"))
                return super().repair(*args, **kwargs)

        layer = DecisionLayer()
        validator = RecordingValidator()
        result = V2DecisionPipeline(
            preparation=Preparation(),
            decision_layer=layer,
            optimizer=TwoInvalidResultsOptimizer(),
            validator=validator,
        ).run(
            optimizer_workbook(),
            "C1",
            "Protect priority stock.",
            "2026-06-02",
        )

        self.assertEqual(layer.retry_calls, 1)
        self.assertEqual(validator.repair_dates, [effective_date, effective_date])
        self.assertTrue(result["validation_result"]["valid"])


if __name__ == "__main__":
    unittest.main()
