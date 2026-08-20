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

    def test_trusted_store_context_overrides_model_store_identity(self) -> None:
        class ConflictingStoreClient(LiveAIClient):
            def chat_completion_json(self, messages):
                payload = super().chat_completion_json(messages)
                payload["store_context"] = {"customer_id": "C999", "store_name": "Wrong Store"}
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


if __name__ == "__main__":
    unittest.main()
