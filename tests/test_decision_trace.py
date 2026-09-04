from __future__ import annotations

import json
import unittest

from services.decision_trace import DecisionTraceBuilder, WhySelectedBuilder


class WhySelectedBuilderTests(unittest.TestCase):
    def test_reasons_are_derived_from_verified_signals(self) -> None:
        reasons = WhySelectedBuilder().build({
            "decision_signals": [
                "STOCKOUT_RISK=HIGH",
                "PURCHASE_FREQUENCY=HIGH",
                "PRODUCT_DEMAND_TREND=UP",
            ]
        })

        self.assertEqual(
            reasons,
            [
                "High stockout risk makes replenishment urgent.",
                "Frequently purchased by this store.",
                "Demand trend is increasing.",
            ],
        )

    def test_unknown_signal_does_not_create_an_explanation(self) -> None:
        reasons = WhySelectedBuilder().build({"decision_signals": ["UNVERIFIED_CLAIM"]})
        self.assertEqual(reasons, [])

    def test_long_shelf_reason_mentions_user_only_when_preference_exists(self) -> None:
        decision = {"decision_signals": ["SHELF_LIFE_LEVEL=LONG"]}

        without_preference = WhySelectedBuilder().build(decision, {"soft_preferences": []})
        with_preference = WhySelectedBuilder().build(
            decision,
            {"soft_preferences": [{"type": "SHELF_LIFE", "value": "LONG"}]},
        )

        self.assertEqual(without_preference, [])
        self.assertEqual(
            with_preference,
            ["Matches the user's long shelf-life preference."],
        )


class DecisionTraceBuilderTests(unittest.TestCase):
    def test_trace_records_each_stage_and_redacts_private_candidate_fields(self) -> None:
        prepared = {
            "candidate_pool": {
                "eligible_candidates": [{
                    "candidate_id": "P1",
                    "recommendation_type": "REPLENISHMENT",
                    "candidate_source": "HISTORICAL_PURCHASE",
                    "product_name": "Product One",
                    "available_stock": 100,
                    "sales_unit": 6,
                }],
                "rejected_candidates": [{
                    "candidate_id": "P2",
                    "rejection_code": "NO_AVAILABLE_STOCK",
                    "available_stock": 0,
                }],
            },
            "safe_decision_context": {
                "structured_intent": {"objective": "PREVENT_STOCKOUT", "budget": 100},
                "candidates": [{
                    "candidate_id": "P1",
                    "recommendation_type": "REPLENISHMENT",
                    "signals": ["STOCKOUT_RISK=HIGH"],
                }],
            },
        }
        decision = {
            "procurement_strategy": {
                "primary_objective": "PREVENT_STOCKOUT",
                "primary_signals": ["STOCKOUT_RISK=HIGH"],
                "secondary_signals": [],
                "strategy_summary": "Protect availability.",
            },
            "candidate_decisions": [{
                "candidate_id": "P1",
                "recommended": True,
                "recommendation_type": "REPLENISHMENT",
                "priority": "HIGH",
                "replenishment_intensity": "HIGH",
                "decision_signals": ["STOCKOUT_RISK=HIGH"],
            }],
        }
        optimizer = {
            "purchase_plan": [{
                "candidate_id": "P1",
                "final_qty": 6,
                "unit_cost": 2.0,
                "estimated_cost": 12.0,
            }],
            "unallocated_candidates": [],
            "total_cost": 12.0,
        }
        validation = {
            "status": "PASS",
            "valid": True,
            "violations": [],
            "requires_model_retry": False,
            "retry_feedback": None,
        }

        trace = DecisionTraceBuilder().build(
            "Prevent stockout for P1",
            prepared,
            [decision],
            optimizer,
            validation,
        )

        self.assertEqual(trace["final_result"]["status"], "VALID")
        self.assertEqual(
            trace["final_result"]["purchase_plan"][0]["why_selected"],
            ["High stockout risk makes replenishment urgent."],
        )
        candidate_payload = json.dumps(trace["candidate_pool"]).casefold()
        self.assertNotIn('"available_stock":', candidate_payload)
        self.assertNotIn('"sales_unit":', candidate_payload)
        self.assertEqual(len(trace["model_decision_attempts"]), 1)
        self.assertEqual(trace["candidate_decisions"][0]["product_name"], "Product One")
        self.assertEqual(
            trace["candidate_decisions"][0]["why_selected"],
            ["High stockout risk makes replenishment urgent."],
        )


if __name__ == "__main__":
    unittest.main()
