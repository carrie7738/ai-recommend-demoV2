import unittest

import pandas as pd

from app import (
    build_v2_display_context,
    failed_v2_fallback_status,
    resolve_v2_as_of_date,
    should_render_recommendations,
)


class AppStateTests(unittest.TestCase):
    def test_v1_fallback_status_preserves_original_v2_failure(self) -> None:
        status = failed_v2_fallback_status("AI decision schema violation")

        self.assertEqual(status["pipeline_version"], "V1_FALLBACK")
        self.assertEqual(status["v2_status"], "FAILED")
        self.assertTrue(status["fallback_triggered"])
        self.assertEqual(status["fallback_reason"], "AI decision schema violation")

    def test_v2_display_context_does_not_require_v1_recommendations(self) -> None:
        context = build_v2_display_context(
            {"SessionId": "S1", "CustomerId": "OLD", "Budget": 500.0},
            {
                "Budget": 300.0,
                "StoreContext": {"CustomerId": "C051"},
                "StructuredIntent": {"budget": 300.0},
            },
        )

        self.assertEqual(context["CustomerId"], "C051")
        self.assertEqual(context["Budget"], 300.0)
        self.assertEqual(context["StructuredIntent"]["budget"], 300.0)

    def test_recommendations_are_hidden_before_a_request_is_submitted(self) -> None:
        self.assertFalse(should_render_recommendations(False, None))
        self.assertFalse(should_render_recommendations(False, "S001"))

    def test_recommendations_require_a_matched_session(self) -> None:
        self.assertFalse(should_render_recommendations(True, None))
        self.assertTrue(should_render_recommendations(True, "S001"))

    def test_v2_as_of_uses_exact_evaluation_scenario(self) -> None:
        workbook = {
            "V2TestScenarios": pd.DataFrame([{
                "CustomerId": "C1",
                "UserInput": "Prepare for Christmas.",
                "AsOfDate": "2026-12-10",
            }]),
            "SupplyAvailability": pd.DataFrame([{
                "LastUpdated": "2026-06-02",
            }]),
        }

        result = resolve_v2_as_of_date(workbook, "prepare for christmas.", "C1")

        self.assertEqual(result, pd.Timestamp("2026-12-10"))

    def test_christmas_variants_use_configured_event_window(self) -> None:
        workbook = {
            "V2TestScenarios": pd.DataFrame(),
            "EventConfig": pd.DataFrame([{
                "EventId": "EV_XMAS_2025",
                "EventName": "Christmas 2025",
                "EventType": "HOLIDAY",
                "EventWindowStart": "2025-12-10",
                "EventWindowEnd": "2025-12-24",
                "ComparableEventId": None,
            }, {
                "EventId": "EV_XMAS_2026",
                "EventName": "Christmas 2026",
                "EventType": "HOLIDAY",
                "EventWindowStart": "2026-12-10",
                "EventWindowEnd": "2026-12-24",
                "ComparableEventId": "EV_XMAS_2025",
            }]),
            "SupplyAvailability": pd.DataFrame([{"LastUpdated": "2026-06-02"}]),
        }
        for request in [
            "Christmas promotion",
            "prepare for Christmas",
            "Christmas campaign",
            "holiday promotion for Christmas",
        ]:
            with self.subTest(request=request):
                result = resolve_v2_as_of_date(
                    workbook,
                    request,
                    "C1",
                    {"StructuredIntent": {"occasion": "CHRISTMAS"}},
                )
                self.assertEqual(result, pd.Timestamp("2026-12-10"))

if __name__ == "__main__":
    unittest.main()
