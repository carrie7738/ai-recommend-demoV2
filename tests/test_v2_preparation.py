import json
from pathlib import Path
import unittest

import pandas as pd

from services.intent_parser import IntentParser
from services.v2_preparation import V2PreparationPipeline


WORKBOOK_PATH = Path(__file__).resolve().parents[1] / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx"


class OfflineAIClient:
    is_available = False


class V2PreparationPipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workbook = pd.read_excel(WORKBOOK_PATH, sheet_name=None, engine="openpyxl")
        cls.pipeline = V2PreparationPipeline(
            intent_parser=IntentParser(ai_client=OfflineAIClient())
        )

    def test_pipeline_resolves_explicit_product_name_without_live_ai(self) -> None:
        result = self.pipeline.prepare(
            self.workbook,
            "C051",
            "Please purchase V2 Requested Specialty Drink.",
            "2026-06-02",
        )
        candidates = {
            item["candidate_id"]: item
            for item in result["safe_decision_context"]["candidates"]
        }

        self.assertEqual(result["intent"]["StructuredIntent"]["store_id"], "C051")
        self.assertEqual(candidates["P209"]["candidate_source"], "USER_REQUESTED")
        self.assertEqual(candidates["P209"]["recommendation_type"], "DISCOVERY")
        self.assertIn("USER_REQUESTED", candidates["P209"]["signals"])

    def test_pipeline_exposes_only_safe_candidate_context_to_task_4(self) -> None:
        result = self.pipeline.prepare(
            self.workbook,
            "C051",
            "High traffic next week. Focus on Fruit products.",
            "2026-06-02",
        )
        payload = json.dumps(result["safe_decision_context"]).casefold()

        for forbidden in ["unitprice", "unit_price", "avgcost", "avg_cost", "currentstock", "current_stock", "availablestock", "available_stock"]:
            self.assertNotIn(forbidden, payload)

    def test_pipeline_builds_peer_event_baseline(self) -> None:
        result = self.pipeline.prepare(
            self.workbook,
            "C054",
            "Prepare V2 Christmas Ham for Christmas 2026.",
            "2026-12-10",
        )
        candidates = {
            item["candidate_id"]: item
            for item in result["safe_decision_context"]["candidates"]
        }

        self.assertEqual(candidates["P212"]["features"]["baseline_source"], "PEER_EVENT")
        self.assertIn("OCCASION=CHRISTMAS", candidates["P212"]["signals"])


if __name__ == "__main__":
    unittest.main()
