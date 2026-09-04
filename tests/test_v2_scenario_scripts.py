from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import pandas as pd

from scripts import ab_evaluation, v2_scenario_regression


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKBOOK_PATH = REPOSITORY_ROOT / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"
VIDEO_SCENARIOS_PATH = (
    REPOSITORY_ROOT
    / "videos"
    / "procurement-scenarios"
    / "media"
    / "scenarios.json"
)


class V2ScenarioScriptMappingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = pd.read_excel(
            WORKBOOK_PATH,
            sheet_name=None,
            engine="openpyxl",
        )
        cls.video_scenarios = json.loads(
            VIDEO_SCENARIOS_PATH.read_text(encoding="utf-8")
        )

    def test_all_video_slugs_have_audited_workbook_rows(self) -> None:
        bindings = v2_scenario_regression.load_scenario_bindings(
            self.workbook,
            self.video_scenarios,
        )
        expected = {
            "01_high_traffic": (
                "V2-001",
                "C051",
                "2026-06-02",
                "NORMAL_REPLENISHMENT",
            ),
            "02_holiday_promo": (
                "V2-018",
                "C051",
                "2026-12-10",
                "STORE_EVENT_BASELINE",
            ),
            "03_low_budget": (
                "V2-004",
                "C051",
                "2026-06-02",
                "HIGH_STOCKOUT_RISK",
            ),
            "04_long_shelf": (
                "V2-006",
                "C051",
                "2026-06-02",
                "LONG_SHELF_LIFE_SOFT",
            ),
            "05_fruit_focus": (
                "V2-008",
                "C051",
                "2026-06-02",
                "CATEGORY_PREFERENCE_SOFT",
            ),
            "06_no_budget": (
                "V2-001",
                "C051",
                "2026-06-02",
                "NORMAL_REPLENISHMENT",
            ),
        }

        self.assertEqual(len(bindings), len(expected))
        for binding in bindings:
            with self.subTest(slug=binding["slug"]):
                self.assertEqual(
                    (
                        binding["scenario_id"],
                        binding["customer_id"],
                        binding["as_of_date"],
                        binding["decision_path"],
                    ),
                    expected[binding["slug"]],
                )
                self.assertGreater(binding["expected_candidate_count"], 0)

    def test_regression_and_ab_scripts_do_not_hardcode_customer_id(self) -> None:
        for module in (v2_scenario_regression, ab_evaluation):
            with self.subTest(module=module.__name__):
                source = inspect.getsource(module)
                self.assertNotIn("'C001'", source)
                self.assertNotIn('"C001"', source)

    def test_ab_runner_passes_audited_identity_without_calling_model(self) -> None:
        class FakeAIClient:
            is_available = False
            provider_name = "offline-test"
            supports_json_schema = False
            last_call_metrics: dict = {}

            def __init__(self, settings) -> None:
                self.settings = settings

        class FakePipeline:
            calls: list[tuple] = []

            def __init__(self, *args, **kwargs) -> None:
                pass

            def run(self, *args, **kwargs) -> dict:
                self.calls.append((args, kwargs))
                return {
                    "safe_decision_context": {
                        "structured_intent": {
                            "budget": 1000.0,
                            "traffic_expectation": "HIGH",
                            "occasion": "NONE",
                            "category_preference": [],
                            "hard_constraints": [],
                            "soft_preferences": [],
                        },
                        "candidates": [{
                            "candidate_id": "P201",
                            "features": {
                                "shelf_life_level": "LONG",
                                "category_relevance": "MEDIUM",
                            },
                        }],
                    },
                    "intent": {"AIAnalysisStatus": "live"},
                    "candidate_pool": {"eligible_candidates": []},
                    "ai_decision": {"candidate_decisions": [{
                        "candidate_id": "P201",
                        "recommended": True,
                        "priority": "HIGH",
                        "replenishment_intensity": "HIGH",
                    }]},
                    "final_purchase_plan": [{
                        "candidate_id": "P201",
                        "final_qty": 1,
                    }],
                    "optimizer_result": {
                        "total_cost": 1.0,
                        "remaining_budget": 999.0,
                    },
                    "validation_result": {"status": "PASS", "valid": True},
                    "v2_status": "SUCCESS",
                    "fallback_triggered": False,
                }

        with patch.object(ab_evaluation, "AIClient", FakeAIClient), \
                patch.object(ab_evaluation, "V2DecisionPipeline", FakePipeline), \
                patch.object(
                    ab_evaluation,
                    "_settings_for",
                    return_value=SimpleNamespace(model="offline-test"),
                ):
            records = ab_evaluation.run_evaluation(
                providers=["deepseek"],
                runs=1,
                case_slugs={"01_high_traffic"},
            )

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["scenario_id"], "V2-001")
        self.assertEqual(records[0]["customer_id"], "C051")
        self.assertEqual(records[0]["as_of_date"], "2026-06-02")
        self.assertEqual(FakePipeline.calls[0][0][1], "C051")
        self.assertEqual(FakePipeline.calls[0][0][3], "2026-06-02")


if __name__ == "__main__":
    unittest.main()
