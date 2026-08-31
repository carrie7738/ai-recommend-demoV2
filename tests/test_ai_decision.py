from __future__ import annotations

import json
from pathlib import Path
import unittest

import pandas as pd

from services.ai_decision import AIDecisionError, AIDecisionLayer
from services.intent_parser import IntentParser
from services.v2_decision_pipeline import V2DecisionPipeline
from services.v2_preparation import V2PreparationPipeline


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"


class OfflineAIClient:
    is_available = False


class ContractDecisionClient:
    is_available = True
    provider_name = "test"

    def __init__(self) -> None:
        self.messages = []

    def chat_completion_json(self, messages):
        self.messages = messages
        model_input = json.loads(messages[-1]["content"])
        candidates = model_input["candidates"]
        return {
            "procurement_strategy": {
                "primary_objective": str(
                    model_input["structured_intent"].get("objective") or "GENERAL_PLANNING"
                ),
                "primary_signals": model_input["allowed_strategy_signals"][:1],
                "secondary_signals": model_input["allowed_strategy_signals"][1:2],
                "strategy_summary": "Prioritize the strongest verified procurement signals.",
            },
            "candidate_decisions": [
                {
                    "candidate_id": candidate["candidate_id"],
                    "recommended": True,
                    "recommendation_type": candidate["recommendation_type"],
                    "priority": "HIGH" if "USER_REQUESTED" in candidate["signals"] else "MEDIUM",
                    "replenishment_intensity": "MEDIUM",
                    "decision_signals": candidate["signals"][:2],
                }
                for candidate in candidates
            ],
        }


def safe_context() -> dict:
    return {
        "structured_intent": {
            "objective": "PREVENT_STOCKOUT",
            "traffic_expectation": "HIGH",
            "occasion": "NONE",
            "budget": 500.0,
        },
        "candidates": [
            {
                "candidate_id": "P101",
                "recommendation_type": "REPLENISHMENT",
                "candidate_source": "STORE_HISTORY",
                "features": {
                    "purchase_frequency": "HIGH",
                    "stockout_risk": "HIGH",
                },
                "signals": ["PURCHASE_FREQUENCY=HIGH", "STOCKOUT_RISK=HIGH"],
            },
            {
                "candidate_id": "P209",
                "recommendation_type": "DISCOVERY",
                "candidate_source": "USER_REQUESTED",
                "features": {"peer_popularity": "LOW"},
                "signals": ["USER_REQUESTED", "PEER_PURCHASE_RATIO=0%"],
            },
        ],
    }


class AIDecisionLayerTests(unittest.TestCase):
    def test_valid_decision_contract_is_accepted(self) -> None:
        client = ContractDecisionClient()
        result = AIDecisionLayer(ai_client=client).decide(safe_context())

        self.assertEqual({item["candidate_id"] for item in result["candidate_decisions"]}, {"P101", "P209"})
        requested = next(item for item in result["candidate_decisions"] if item["candidate_id"] == "P209")
        self.assertEqual(requested["recommendation_type"], "DISCOVERY")
        self.assertEqual(requested["priority"], "HIGH")

    def test_model_receives_schema_and_safe_context_only(self) -> None:
        client = ContractDecisionClient()
        AIDecisionLayer(ai_client=client).decide(safe_context())
        payload = json.loads(client.messages[-1]["content"])
        serialized = json.dumps(payload).casefold()

        self.assertIn("output_schema", payload)
        self.assertNotIn("candidate_pool", payload)
        for forbidden in ["unit_price", "avg_cost", "current_stock", "available_stock", "recommended_qty"]:
            self.assertNotIn(forbidden, serialized)

    def test_raw_inventory_field_is_rejected_before_model_call(self) -> None:
        client = ContractDecisionClient()
        context = safe_context()
        context["candidates"][0]["current_stock"] = 12

        with self.assertRaisesRegex(AIDecisionError, "Forbidden raw field"):
            AIDecisionLayer(ai_client=client).decide(context)
        self.assertEqual(client.messages, [])

    def test_unknown_candidate_is_rejected(self) -> None:
        class UnknownCandidateClient(ContractDecisionClient):
            def chat_completion_json(self, messages):
                payload = super().chat_completion_json(messages)
                payload["candidate_decisions"][0]["candidate_id"] = "P999"
                return payload

        with self.assertRaisesRegex(AIDecisionError, "candidate mismatch"):
            AIDecisionLayer(ai_client=UnknownCandidateClient()).decide(safe_context())

    def test_changed_recommendation_type_is_rejected(self) -> None:
        class ChangedTypeClient(ContractDecisionClient):
            def chat_completion_json(self, messages):
                payload = super().chat_completion_json(messages)
                payload["candidate_decisions"][0]["recommendation_type"] = "DISCOVERY"
                return payload

        with self.assertRaisesRegex(AIDecisionError, "changed recommendation_type"):
            AIDecisionLayer(ai_client=ChangedTypeClient()).decide(safe_context())

    def test_invented_candidate_signal_is_rejected(self) -> None:
        class InventedSignalClient(ContractDecisionClient):
            def chat_completion_json(self, messages):
                payload = super().chat_completion_json(messages)
                payload["candidate_decisions"][0]["decision_signals"] = ["MADE_UP=HIGH"]
                return payload

        with self.assertRaisesRegex(AIDecisionError, "invented decision signals"):
            AIDecisionLayer(ai_client=InventedSignalClient()).decide(safe_context())

    def test_schema_rejects_quantity_output(self) -> None:
        class QuantityClient(ContractDecisionClient):
            def chat_completion_json(self, messages):
                payload = super().chat_completion_json(messages)
                payload["candidate_decisions"][0]["quantity"] = 10
                return payload

        with self.assertRaisesRegex(AIDecisionError, "schema violation"):
            AIDecisionLayer(ai_client=QuantityClient()).decide(safe_context())

    def test_large_candidate_pool_preserves_every_candidate(self) -> None:
        context = safe_context()
        context["candidates"] = [
            {
                "candidate_id": f"P{index:03d}",
                "recommendation_type": "REPLENISHMENT",
                "candidate_source": "STORE_HISTORY",
                "features": {
                    "purchase_frequency": "HIGH",
                    "stockout_risk": "HIGH",
                },
                "signals": ["PURCHASE_FREQUENCY=HIGH", "STOCKOUT_RISK=HIGH"],
            }
            for index in range(1, 51)
        ]

        result = AIDecisionLayer(ai_client=ContractDecisionClient()).decide(context)

        self.assertEqual(len(result["candidate_decisions"]), 50)
        self.assertEqual(
            {item["candidate_id"] for item in result["candidate_decisions"]},
            {item["candidate_id"] for item in context["candidates"]},
        )


class V2DecisionPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = pd.read_excel(WORKBOOK_PATH, sheet_name=None, engine="openpyxl")

    def test_task_1_to_4_pipeline_uses_safe_handoff(self) -> None:
        decision_client = ContractDecisionClient()
        pipeline = V2DecisionPipeline(
            preparation=V2PreparationPipeline(
                intent_parser=IntentParser(ai_client=OfflineAIClient())
            ),
            decision_layer=AIDecisionLayer(ai_client=decision_client),
        )

        result = pipeline.run(
            self.workbook,
            "C051",
            "Please purchase V2 Requested Specialty Drink.",
            "2026-06-02",
        )

        safe_ids = {
            item["candidate_id"] for item in result["safe_decision_context"]["candidates"]
        }
        decision_ids = {
            item["candidate_id"] for item in result["ai_decision"]["candidate_decisions"]
        }
        self.assertEqual(decision_ids, safe_ids)
        self.assertIn("P209", decision_ids)
        self.assertEqual(result["pipeline_version"], "V2")
        self.assertEqual(result["v2_status"], "SUCCESS")
        self.assertFalse(result["fallback_triggered"])


if __name__ == "__main__":
    unittest.main()
