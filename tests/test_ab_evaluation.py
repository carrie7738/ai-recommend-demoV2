from pathlib import Path
import tempfile
import unittest

from scripts.ab_evaluation import compare_records, write_artifacts


class ABEvaluationTests(unittest.TestCase):
    def test_comparison_reports_sku_overlap_and_cost_difference(self) -> None:
        records = [
            {
                "scenario": "case-1",
                "run": 1,
                "provider": "deepseek",
                "status": "PASS",
                "contract_violations": [],
                "final_skus": ["P001", "P002"],
                "total_cost": 100,
            },
            {
                "scenario": "case-1",
                "run": 1,
                "provider": "gemini",
                "status": "PASS",
                "contract_violations": [],
                "final_skus": ["P002", "P003"],
                "total_cost": 80,
            },
        ]

        result = compare_records(records)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["sku_overlap_ratio"], 0.3333)
        self.assertEqual(result[0]["cost_difference"], 20.0)
        self.assertTrue(result[0]["both_contract_pass"])

    def test_artifacts_do_not_require_nested_fields_in_csv(self) -> None:
        records = [{
            "scenario": "case-1",
            "run": 1,
            "provider": "deepseek",
            "configured_model": "test-model",
            "status": "FAIL",
            "contract_violations": ["PIPELINE_EXCEPTION"],
            "error_type": "RuntimeError",
            "error": "test",
        }]
        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            write_artifacts(records, output_dir)

            self.assertTrue((output_dir / "ab_runs.json").exists())
            self.assertTrue((output_dir / "ab_runs.csv").exists())
            self.assertTrue((output_dir / "ab_comparison.json").exists())
            self.assertIn("PIPELINE_EXCEPTION", (output_dir / "ab_runs.csv").read_text(encoding="utf-8-sig"))


if __name__ == "__main__":
    unittest.main()
