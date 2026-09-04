import json
from pathlib import Path
import unittest

from services.intent_parser import IntentParser


class OfflineAIClient:
    is_available = False


class LiveAIClient:
    is_available = True

    def chat_completion_json(self, messages):
        return {
            "budget": 500,
            "traffic_level": "HIGH",
            "promotion_flag": False,
            "shelf_life_preference": "LONG",
            "preferred_category": "Fruit",
            "excluded_category": None,
            "time_range": "next_week",
            "expected_intent": "Prevent stockouts for fruit next week.",
            "business_intent": {
                "primary_intent": "stockout_prevention",
                "secondary_intents": [],
                "decision_type": "planning",
                "urgency": "medium",
                "intent_summary": "Prevent stockouts for fruit next week.",
            },
            "decision_signals": {
                "expected_demand_change": "increase",
                "demand_driver": "traffic",
                "stockout_sensitivity": "high",
                "waste_sensitivity": "medium",
                "price_sensitivity": "medium",
                "growth_appetite": "medium",
                "budget_strictness": "strict",
                "substitution_allowed": False,
            },
            "uncertainty": {
                "overall_confidence": 0.8,
                "field_sources": {
                    "budget": "explicit",
                    "traffic_level": "explicit",
                    "promotion_flag": "explicit",
                    "shelf_life_preference": "explicit",
                    "category": "explicit",
                    "time_horizon": "explicit",
                },
                "low_confidence_fields": [],
            },
            "missing_information": [],
            "recommendation_readiness": {
                "can_generate_recommendation": True,
                "should_ask_follow_up": False,
                "confidence_level": "high",
                "confidence_score": 0.8,
                "confidence_drivers": [],
                "confidence_risks": [],
                "follow_up_question": "",
            },
            "structured_intent": {
                "store_id": "",
                "budget": 500,
                "objective": "PREVENT_STOCKOUT",
                "traffic_expectation": "HIGH",
                "occasion": "NONE",
                "category_preference": ["Fruit"],
                "hard_constraints": [],
                "soft_preferences": [],
                "explicit_products": [],
            },
            "store_context": {},
            "store_considerations": [],
        }


class SchemaLessInvalidAIClient:
    is_available = True
    supports_json_schema = False

    def chat_completion_json(self, messages):
        return {
            "budget": 500,
            "traffic_level": "HIGH",
        }


class IntentParserFallbackTests(unittest.TestCase):
    def setUp(self) -> None:
        self.parser = IntentParser(ai_client=OfflineAIClient())

    def test_import_re_at_module_top(self) -> None:
        import services.intent_parser as mod
        self.assertTrue(hasattr(mod, "re"))

    def test_fallback_extracts_excluded_category_from_avoid(self) -> None:
        intent = self.parser.parse_intent("avoid fresh products please")
        self.assertEqual(intent["ExcludedCategory"], "Fresh")

    def test_fallback_extracts_excluded_category_from_no(self) -> None:
        intent = self.parser.parse_intent("no dairy in this order")
        self.assertEqual(intent["ExcludedCategory"], "Dairy")

    def test_fallback_does_not_misclassify_next_week_no_problem(self) -> None:
        intent = self.parser.parse_intent("I want fresh fruit, no problem next week")
        self.assertIsNone(intent["ExcludedCategory"])

    def test_fallback_does_not_misclassify_no_problem_with_category_word(self) -> None:
        intent = self.parser.parse_intent("need some frozen items, no problem at all")
        self.assertIsNone(intent["ExcludedCategory"])

    def test_fallback_preserves_existing_budget_traffic_shelf(self) -> None:
        intent = self.parser.parse_intent(
            "Budget NZD 100, high traffic next week, avoid short shelf-life products"
        )
        self.assertEqual(intent["Budget"], 100.0)
        self.assertEqual(intent["TrafficLevel"], "HIGH")
        self.assertEqual(intent["ShelfLifePreference"], "LONG")
        self.assertIsNone(intent["ExcludedCategory"])

    def test_fallback_identifies_its_rule_based_analysis_source(self) -> None:
        intent = self.parser.parse_intent("Budget NZD 100")
        self.assertEqual(intent["AIAnalysisStatus"], "fallback")
        self.assertEqual(intent["AIAnalysisSource"], "Rules fallback")

    def test_live_client_identifies_deepseek_analysis_source(self) -> None:
        intent = IntentParser(ai_client=LiveAIClient()).parse_intent("Budget NZD 500")
        self.assertEqual(intent["AIAnalysisStatus"], "live")
        self.assertEqual(intent["AIAnalysisSource"], "DeepSeek")

    def test_schema_less_provider_response_is_locally_schema_validated(self) -> None:
        intent = IntentParser(ai_client=SchemaLessInvalidAIClient()).parse_intent(
            "Budget NZD 500 and high traffic"
        )

        self.assertEqual(intent["AIAnalysisStatus"], "fallback")
        self.assertEqual(intent["AIAnalysisSource"], "Rules fallback")

    def test_live_prompt_marks_actual_user_request_separately_from_example(self) -> None:
        class RecordingLiveClient(LiveAIClient):
            def __init__(self):
                self.messages = []

            def chat_completion_json(self, messages):
                self.messages = messages
                return super().chat_completion_json(messages)

        client = RecordingLiveClient()
        IntentParser(ai_client=client).parse_intent("Budget NZD 500 and high traffic")

        self.assertIn("user_request:", client.messages[-1]["content"])
        self.assertIn("Budget NZD 500 and high traffic", client.messages[-1]["content"])
        self.assertIn("not the illustrative JSON example", client.messages[-1]["content"])

    def test_trusted_store_context_is_applied_to_schema_valid_model_output(self) -> None:
        class ConflictingStoreClient(LiveAIClient):
            def chat_completion_json(self, messages):
                payload = super().chat_completion_json(messages)
                payload["store_considerations"] = ["Use the trusted store profile."]
                return payload

        trusted_context = {
            "CustomerId": "C001",
            "StoreName": "Cafe Store 001",
            "Industry": "Cafe",
            "Region": "Christchurch",
            "StoreLevel": "Bronze",
            "CustomerStage": "New",
        }
        intent = IntentParser(ai_client=ConflictingStoreClient()).parse_intent(
            "For Cafe Store 001, budget is NZD 500.",
            store_context=trusted_context,
        )

        self.assertEqual(intent["StoreContext"], trusted_context)
        self.assertEqual(intent["StoreConsiderations"], ["Use the trusted store profile."])
        self.assertEqual(intent["StructuredIntent"]["store_id"], "C001")

    def test_fallback_builds_v2_soft_preferences_without_filtering(self) -> None:
        intent = self.parser.parse_intent(
            "For C051, prefer long shelf-life products and focus on Fruit."
        )

        structured = intent["StructuredIntent"]
        self.assertEqual(structured["hard_constraints"], [])
        self.assertIn({"type": "SHELF_LIFE", "value": "LONG"}, structured["soft_preferences"])
        self.assertIn({"type": "CATEGORY", "value": "Fruit"}, structured["soft_preferences"])

    def test_fallback_builds_explicit_hard_constraints(self) -> None:
        intent = self.parser.parse_intent(
            "Only Fruit and do not accept short shelf-life products."
        )

        constraints = intent["StructuredIntent"]["hard_constraints"]
        self.assertIn(
            {"type": "CATEGORY", "operator": "INCLUDE_ONLY", "values": ["Fruit"]},
            constraints,
        )
        self.assertIn(
            {"type": "SHELF_LIFE", "operator": "REQUIRE_LEVEL", "value": "LONG"},
            constraints,
        )

    def test_fallback_extracts_explicit_sku(self) -> None:
        intent = self.parser.parse_intent("Please purchase P209 with normal quantity.")

        self.assertEqual(
            intent["StructuredIntent"]["explicit_products"],
            [{"sku": "P209", "product_name": "", "quantity_intent": "NORMAL"}],
        )

    def test_live_payload_normalizes_v2_contract(self) -> None:
        class StructuredClient(LiveAIClient):
            def chat_completion_json(self, messages):
                payload = super().chat_completion_json(messages)
                payload["structured_intent"] = {
                    **payload["structured_intent"],
                    "objective": "PREVENT_STOCKOUT",
                    "occasion": "CHRISTMAS",
                    "hard_constraints": [],
                    "soft_preferences": [{"type": "CATEGORY", "value": "Fruit"}],
                    "explicit_products": [
                        {"sku": "P209", "product_name": "", "quantity_intent": "HIGH"}
                    ],
                }
                return payload

        intent = IntentParser(ai_client=StructuredClient()).parse_intent("Prepare P209 for Christmas")
        structured = intent["StructuredIntent"]

        self.assertEqual(structured["objective"], "PREVENT_STOCKOUT")
        self.assertEqual(structured["occasion"], "CHRISTMAS")
        self.assertEqual(structured["explicit_products"][0]["sku"], "P209")
        self.assertEqual(structured["explicit_products"][0]["quantity_intent"], "HIGH")

    def test_invalid_free_text_enum_falls_back_to_local_intent_parsing(self) -> None:
        class FreeTextStructuredClient(LiveAIClient):
            def chat_completion_json(self, messages):
                payload = super().chat_completion_json(messages)
                payload["structured_intent"] = {
                    "objective": "Prevent stockouts",
                    "occasion": "Christmas promotion",
                }
                return payload

        intent = IntentParser(ai_client=FreeTextStructuredClient()).parse_intent(
            "Prevent stockouts for the Christmas promotion."
        )

        self.assertEqual(intent["AIAnalysisStatus"], "fallback")
        self.assertEqual(intent["StructuredIntent"]["objective"], "PREVENT_STOCKOUT")
        self.assertEqual(intent["StructuredIntent"]["occasion"], "CHRISTMAS")

    def test_six_demo_requests_produce_stable_v2_intent(self) -> None:
        scenario_path = (
            Path(__file__).resolve().parents[1]
            / "videos"
            / "procurement-scenarios"
            / "media"
            / "scenarios.json"
        )
        scenarios = json.loads(scenario_path.read_text(encoding="utf-8"))

        self.assertEqual(len(scenarios), 6)
        parsed = {
            scenario["slug"]: self.parser.parse_intent(scenario["request"])["StructuredIntent"]
            for scenario in scenarios
        }
        self.assertEqual(parsed["01_high_traffic"]["budget"], 1000.0)
        self.assertEqual(parsed["01_high_traffic"]["traffic_expectation"], "HIGH")
        self.assertEqual(parsed["02_holiday_promo"]["occasion"], "CHRISTMAS")
        self.assertEqual(parsed["02_holiday_promo"]["objective"], "SEASONAL_PREPARATION")
        self.assertEqual(parsed["03_low_budget"]["objective"], "PREVENT_STOCKOUT")
        self.assertIn(
            {"type": "SHELF_LIFE", "value": "LONG"},
            parsed["04_long_shelf"]["soft_preferences"],
        )
        self.assertIn("Fruit", parsed["05_fruit_focus"]["category_preference"])
        self.assertIsNone(parsed["06_no_budget"]["budget"])


if __name__ == "__main__":
    unittest.main()
