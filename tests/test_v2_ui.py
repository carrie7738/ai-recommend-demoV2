from __future__ import annotations

import unittest
from unittest.mock import patch

from services.ui import (
    render_v2_procurement_strategy,
    render_v2_product_decisions,
    render_v2_purchase_plan,
    render_v2_runtime_status,
)


class V2UIRenderTests(unittest.TestCase):
    @patch("services.ui.st.markdown")
    def test_runtime_status_exposes_provider_model_intent_and_fallback(self, markdown) -> None:
        render_v2_runtime_status(
            "gemini",
            "gemini-test-model",
            {
                "pipeline_version": "V1_FALLBACK",
                "v2_status": "FAILED",
                "fallback_triggered": True,
                "fallback_reason": "schema <violation>",
            },
            {
                "objective": "PREVENT_STOCKOUT",
                "budget": 300,
                "traffic_expectation": "HIGH",
                "occasion": "NONE",
                "category_preference": ["Fruit"],
            },
            "live",
        )

        html = markdown.call_args.args[0]
        self.assertIn("Model &amp; Pipeline Status", html)
        self.assertIn("Provider: gemini", html)
        self.assertIn("Model: gemini-test-model", html)
        self.assertIn("V1_FALLBACK", html)
        self.assertIn("Structured Intent", html)
        self.assertIn("NZD 300", html)
        self.assertIn("schema &lt;violation&gt;", html)

    @patch("services.ui.st.markdown")
    def test_strategy_section_renders_provider_neutral_contract(self, markdown) -> None:
        render_v2_procurement_strategy({
            "primary_objective": "PREVENT_STOCKOUT",
            "primary_signals": ["STOCKOUT_RISK=HIGH"],
            "secondary_signals": ["TRAFFIC_EXPECTATION=HIGH"],
            "strategy_summary": "Protect <critical> availability.",
        }, retry_count=1)

        html = markdown.call_args.args[0]
        self.assertIn("Procurement Strategy", html)
        self.assertIn("1 constrained retry", html)
        self.assertIn("Protect &lt;critical&gt; availability.", html)

    @patch("services.ui.st.markdown")
    def test_product_decisions_distinguish_discovery(self, markdown) -> None:
        render_v2_product_decisions(
            [{
                "candidate_id": "P2",
                "product_name": "New Product",
                "recommended": True,
                "recommendation_type": "DISCOVERY",
                "priority": "HIGH",
                "replenishment_intensity": "LOW",
                "why_selected": ["Explicitly requested by the user."],
            }],
            [],
        )

        html = markdown.call_args.args[0]
        self.assertIn("AI Product Decisions", html)
        self.assertIn("NEW OPPORTUNITY", html)
        self.assertIn("Explicitly requested by the user.", html)

    @patch("services.ui.st.markdown")
    def test_final_plan_renders_validated_local_result(self, markdown) -> None:
        plan = [{
            "candidate_id": "P1",
            "product_name": "Core Product",
            "final_qty": 6,
            "unit": "pack",
            "unit_cost": 2.0,
            "estimated_cost": 12.0,
            "priority": "HIGH",
        }]
        render_v2_purchase_plan(
            plan,
            {"total_cost": 12.0, "remaining_budget": 8.0},
            {"status": "PASS", "valid": True},
        )

        html = markdown.call_args.args[0]
        self.assertIn("Final Purchase Plan", html)
        self.assertIn("Validated", html)
        self.assertIn("Core Product", html)
        self.assertIn("NZD 12.00", html)

    @patch("services.ui.st.error")
    @patch("services.ui.st.markdown")
    def test_invalid_plan_is_not_rendered_as_final_purchase_plan(self, markdown, error) -> None:
        render_v2_purchase_plan(
            [{"candidate_id": "P1", "final_qty": 25, "sales_unit": 6}],
            {"total_cost": 25.0, "remaining_budget": None},
            {
                "status": "FAIL",
                "valid": False,
                "violations": [{"code": "AVAILABLE_STOCK_EXCEEDED"}],
            },
        )

        markdown.assert_not_called()
        self.assertIn("No final purchase plan", error.call_args.args[0])
        self.assertIn("AVAILABLE_STOCK_EXCEEDED", error.call_args.args[0])


if __name__ == "__main__":
    unittest.main()
