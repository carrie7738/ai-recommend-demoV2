import unittest

from services.intent_parser import IntentParser


class OfflineAIClient:
    is_available = False


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


if __name__ == "__main__":
    unittest.main()
