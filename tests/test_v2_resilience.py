from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import unittest

import pandas as pd
from openai import APITimeoutError, RateLimitError

from services.ai_client import AIClientError
from services.candidate_pool import CandidatePoolBuilder
from services.intent_parser import INTENT_JSON_SCHEMA, IntentParser
from services.local_optimizer import LocalOptimizer, LocalOptimizerError
from services.model_providers import DeepSeekAdapter, ModelProviderError
from config.settings import AISettings


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"


class StaticClientFactory:
    """A deterministic OpenAI-compatible client double; it never opens a network connection."""

    def __init__(self, content: str = '{"ok": true}', error: Exception | None = None) -> None:
        self.content = content
        self.error = error
        self.factory_calls = 0
        self.request_calls = 0

    def __call__(self, **kwargs):
        self.factory_calls += 1

        def create(**request_kwargs):
            self.request_calls += 1
            if self.error is not None:
                raise self.error
            return SimpleNamespace(
                model=request_kwargs["model"],
                usage=None,
                choices=[SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=self.content),
                )],
            )

        return SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create)),
        )


def rate_limit_error() -> RateLimitError:
    response = SimpleNamespace(request=None, status_code=429, headers={})
    return RateLimitError("429 rate limited", response=response, body={"error": "rate"})


class SchemaCapableIntentClient:
    is_available = True
    supports_json_schema = True
    provider_name = "deepseek"

    def __init__(self, response) -> None:
        self.response = response
        self.calls = 0
        self.received_schema = None
        self.received_schema_name = None

    def chat_completion_json(self, messages, json_schema=None, schema_name="structured_response"):
        self.calls += 1
        self.received_schema = json_schema
        self.received_schema_name = schema_name
        return self.response


class FailingIntentClient:
    is_available = True
    supports_json_schema = False
    provider_name = "deepseek"

    def __init__(self, error: Exception) -> None:
        self.error = error
        self.calls = 0

    def chat_completion_json(self, messages):
        self.calls += 1
        raise self.error


class V2ResilienceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = pd.read_excel(WORKBOOK_PATH, sheet_name=None, engine="openpyxl")
        cls.builder = CandidatePoolBuilder()

    def test_missing_deepseek_key_fails_before_client_creation(self) -> None:
        factory = StaticClientFactory()
        provider = DeepSeekAdapter(
            AISettings(provider="deepseek", api_key=""),
            client_factory=factory,
        )

        self.assertFalse(provider.is_available)
        with self.assertRaisesRegex(ModelProviderError, "deepseek is not available"):
            provider.chat_completion_json([{"role": "user", "content": "Return JSON."}])
        self.assertEqual(factory.factory_calls, 0)
        self.assertEqual(factory.request_calls, 0)

    def test_timeout_is_translated_without_an_adapter_retry(self) -> None:
        factory = StaticClientFactory(error=APITimeoutError(request=None))
        provider = DeepSeekAdapter(
            AISettings(provider="deepseek", api_key="test"),
            client_factory=factory,
        )

        with self.assertRaisesRegex(ModelProviderError, "AI request timed out"):
            provider.chat_completion_json([{"role": "user", "content": "Return JSON."}])
        self.assertEqual(factory.factory_calls, 1)
        self.assertEqual(factory.request_calls, 1)

    def test_rate_limit_is_translated_without_an_adapter_retry(self) -> None:
        factory = StaticClientFactory(error=rate_limit_error())
        provider = DeepSeekAdapter(
            AISettings(provider="deepseek", api_key="test"),
            client_factory=factory,
        )

        with self.assertRaisesRegex(ModelProviderError, r"AI API error: 429"):
            provider.chat_completion_json([{"role": "user", "content": "Return JSON."}])
        self.assertEqual(factory.factory_calls, 1)
        self.assertEqual(factory.request_calls, 1)

    def test_empty_provider_content_is_rejected_before_json_parsing(self) -> None:
        factory = StaticClientFactory(content="   ")
        provider = DeepSeekAdapter(
            AISettings(provider="deepseek", api_key="test"),
            client_factory=factory,
        )

        with self.assertRaisesRegex(ModelProviderError, "AI returned empty content"):
            provider.chat_completion_json([{"role": "user", "content": "Return JSON."}])
        self.assertIsNone(provider.last_call_metrics["json_parse_success"])

    def test_malformed_provider_json_sets_parse_failure_metric(self) -> None:
        factory = StaticClientFactory(content="{not valid json")
        provider = DeepSeekAdapter(
            AISettings(provider="deepseek", api_key="test"),
            client_factory=factory,
        )

        with self.assertRaisesRegex(ModelProviderError, "Invalid JSON response from AI"):
            provider.chat_completion_json([{"role": "user", "content": "Return JSON."}])
        self.assertTrue(provider.last_call_metrics["api_success"])
        self.assertFalse(provider.last_call_metrics["json_parse_success"])

    def test_schema_capable_intent_response_is_still_locally_validated(self) -> None:
        client = SchemaCapableIntentClient({})
        intent = IntentParser(ai_client=client).parse_intent("Budget NZD 500")

        self.assertEqual(intent["AIAnalysisStatus"], "fallback")
        self.assertEqual(intent["Budget"], 500.0)
        self.assertEqual(client.calls, 1)
        self.assertEqual(client.received_schema, INTENT_JSON_SCHEMA)
        self.assertEqual(client.received_schema_name, "procurement_intent")

    def test_intent_transport_failure_falls_back_and_keeps_trusted_identity(self) -> None:
        client = FailingIntentClient(AIClientError("Invalid JSON response from AI"))
        trusted_context = {
            "CustomerId": "C051",
            "StoreName": "Cafe Store 051",
            "Industry": "Cafe",
            "Region": "Christchurch",
            "StoreLevel": "Bronze",
            "CustomerStage": "New",
        }

        intent = IntentParser(ai_client=client).parse_intent(
            "Budget NZD 500 and high traffic",
            store_context=trusted_context,
        )

        self.assertEqual(intent["AIAnalysisStatus"], "fallback")
        self.assertEqual(intent["Budget"], 500.0)
        self.assertEqual(intent["StoreContext"], trusted_context)
        self.assertEqual(intent["StructuredIntent"]["store_id"], "C051")
        self.assertEqual(client.calls, 1)

    def test_malformed_available_stock_fails_closed_as_no_stock(self) -> None:
        workbook = {name: frame.copy() for name, frame in self.workbook.items()}
        mask = workbook["SupplyAvailability"]["ProductId"].astype(str) == "P201"
        workbook["SupplyAvailability"]["AvailableStock"] = (
            workbook["SupplyAvailability"]["AvailableStock"].astype(object)
        )
        workbook["SupplyAvailability"].loc[mask, "AvailableStock"] = "not-a-number"

        result = self.builder.build(
            workbook,
            "C051",
            {"hard_constraints": [], "explicit_products": [], "occasion": "NONE"},
            "2026-06-02",
        )

        candidate = result.find("P201")
        self.assertIsNotNone(candidate)
        self.assertFalse(candidate["eligible"])
        self.assertEqual(candidate["rejection_code"], "NO_AVAILABLE_STOCK")
        self.assertEqual(candidate["available_stock"], 0.0)

    def test_invalid_product_avg_cost_fails_closed_in_local_optimizer(self) -> None:
        workbook = {name: frame.copy() for name, frame in self.workbook.items()}
        workbook["Product"]["AvgCost"] = workbook["Product"]["AvgCost"].astype(object)
        workbook["Product"].loc[
            workbook["Product"]["ProductId"].astype(str) == "P201", "AvgCost"
        ] = "not-a-number"
        pool = self.builder.build(
            workbook,
            "C051",
            {"hard_constraints": [], "explicit_products": [], "occasion": "NONE"},
            "2026-06-02",
        )
        candidate = pool.find("P201")
        self.assertIsNotNone(candidate)

        with self.assertRaisesRegex(LocalOptimizerError, "AvgCost must be a non-negative number"):
            LocalOptimizer().optimize(
                workbook,
                "C051",
                {"budget": None, "occasion": "NONE"},
                [candidate],
                {
                    "candidate_decisions": [{
                        "candidate_id": "P201",
                        "recommended": True,
                        "recommendation_type": candidate["recommendation_type"],
                        "priority": "HIGH",
                        "replenishment_intensity": "MEDIUM",
                        "decision_signals": [],
                    }],
                },
                "2026-06-02",
            )

if __name__ == "__main__":
    unittest.main()
