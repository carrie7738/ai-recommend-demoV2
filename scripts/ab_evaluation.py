from __future__ import annotations

import argparse
import csv
from dataclasses import replace
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import pandas as pd


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from services.ai_client import AIClient  # noqa: E402
from services.ai_decision import AIDecisionLayer  # noqa: E402
from services.intent_parser import IntentParser  # noqa: E402
from services.v2_decision_pipeline import V2DecisionPipeline  # noqa: E402
from services.v2_preparation import V2PreparationPipeline  # noqa: E402
from scripts.model_smoke_test import _settings_for  # noqa: E402
from scripts.v2_scenario_regression import (  # noqa: E402
    _scenario_contract_violations,
    load_scenario_bindings,
)


class MetricsRecordingClient:
    """Record provider metrics for each model call without exposing credentials."""

    def __init__(self, client: AIClient) -> None:
        self.client = client
        self.call_metrics: list[dict[str, Any]] = []

    @property
    def is_available(self) -> bool:
        return self.client.is_available

    @property
    def provider_name(self) -> str:
        return self.client.provider_name

    @property
    def supports_json_schema(self) -> bool:
        return self.client.supports_json_schema

    def chat_completion_json(
        self,
        messages: list[dict[str, str]],
        json_schema: dict[str, Any] | None = None,
        schema_name: str = "structured_response",
    ) -> dict[str, Any]:
        call_index = len(self.call_metrics) + 1
        try:
            return self.client.chat_completion_json(
                messages,
                json_schema=json_schema,
                schema_name=schema_name,
            )
        finally:
            self.call_metrics.append({
                "call_index": call_index,
                "schema_name": schema_name,
                **self.client.last_call_metrics,
            })


def compare_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault((record["scenario"], record["run"]), []).append(record)

    comparisons: list[dict[str, Any]] = []
    for (scenario, run), group in sorted(grouped.items()):
        successful = [item for item in group if item.get("status") == "PASS"]
        if len(successful) < 2:
            continue
        for left_index, left in enumerate(successful):
            for right in successful[left_index + 1:]:
                left_skus = set(left.get("final_skus", []))
                right_skus = set(right.get("final_skus", []))
                union = left_skus | right_skus
                comparisons.append({
                    "scenario": scenario,
                    "run": run,
                    "left_provider": left["provider"],
                    "right_provider": right["provider"],
                    "sku_overlap_ratio": (
                        round(len(left_skus & right_skus) / len(union), 4)
                        if union else 1.0
                    ),
                    "both_contract_pass": not left.get("contract_violations")
                    and not right.get("contract_violations"),
                    "cost_difference": round(
                        float(left.get("total_cost") or 0)
                        - float(right.get("total_cost") or 0),
                        2,
                    ),
                })
    return comparisons


def _record_for_result(
    provider: str,
    configured_model: str,
    scenario: dict[str, Any],
    run_number: int,
    result: dict[str, Any],
    metrics: list[dict[str, Any]],
    workbook: dict[str, pd.DataFrame] | None = None,
) -> dict[str, Any]:
    violations = _scenario_contract_violations(scenario["slug"], result, workbook)
    structured = result["safe_decision_context"]["structured_intent"]
    final_plan = result.get("final_purchase_plan", [])
    return {
        "scenario": scenario["slug"],
        "scenario_id": scenario.get("scenario_id"),
        "customer_id": scenario.get("customer_id"),
        "as_of_date": scenario.get("as_of_date"),
        "decision_path": scenario.get("decision_path"),
        "run": run_number,
        "provider": provider,
        "configured_model": configured_model,
        "actual_models": sorted({
            str(item["model"]) for item in metrics if item.get("model")
        }),
        "status": "PASS" if not violations else "FAIL",
        "contract_violations": violations,
        "intent": structured,
        "intent_source": result["intent"].get("AIAnalysisStatus"),
        "eligible_count": len(result["candidate_pool"]["eligible_candidates"]),
        "recommended_count": sum(
            1
            for item in result["ai_decision"]["candidate_decisions"]
            if item.get("recommended")
        ),
        "final_skus": [item["candidate_id"] for item in final_plan],
        "final_quantities": {
            item["candidate_id"]: item["final_qty"] for item in final_plan
        },
        "total_cost": result["optimizer_result"].get("total_cost"),
        "remaining_budget": result["optimizer_result"].get("remaining_budget"),
        "validator_status": result["validation_result"].get("status"),
        "repair_count": result.get("repair_count"),
        "retry_count": result.get("retry_count"),
        "v2_status": result.get("v2_status"),
        "fallback_triggered": result.get("fallback_triggered"),
        "latency_ms": round(sum(float(item.get("latency_ms") or 0) for item in metrics), 1),
        "input_tokens": sum(int(item.get("input_tokens") or 0) for item in metrics),
        "output_tokens": sum(int(item.get("output_tokens") or 0) for item in metrics),
        "reasoning_tokens": sum(int(item.get("reasoning_tokens") or 0) for item in metrics),
        "model_calls": metrics,
    }


def run_evaluation(
    providers: list[str],
    runs: int,
    case_slugs: set[str] | None = None,
    model_overrides: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    workbook = pd.read_excel(
        REPOSITORY_ROOT / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx",
        sheet_name=None,
        engine="openpyxl",
    )
    scenarios = json.loads(
        (REPOSITORY_ROOT / "videos" / "procurement-scenarios" / "media" / "scenarios.json")
        .read_text(encoding="utf-8")
    )
    scenarios = load_scenario_bindings(workbook, scenarios)
    if case_slugs:
        scenarios = [item for item in scenarios if item["slug"] in case_slugs]

    records: list[dict[str, Any]] = []
    for provider in providers:
        settings = _settings_for(provider)
        override = (model_overrides or {}).get(provider)
        if override:
            settings = replace(settings, model=override)
        for run_number in range(1, runs + 1):
            for scenario in scenarios:
                recorder = MetricsRecordingClient(AIClient(settings=settings))
                pipeline = V2DecisionPipeline(
                    preparation=V2PreparationPipeline(
                        intent_parser=IntentParser(ai_client=recorder)
                    ),
                    decision_layer=AIDecisionLayer(ai_client=recorder),
                )
                try:
                    result = pipeline.run(
                        workbook,
                        scenario["customer_id"],
                        scenario["request"],
                        scenario["as_of_date"],
                    )
                    records.append(_record_for_result(
                        provider,
                        settings.model,
                        scenario,
                        run_number,
                        result,
                        recorder.call_metrics,
                        workbook,
                    ))
                except Exception as exc:
                    records.append({
                        "scenario": scenario["slug"],
                        "scenario_id": scenario["scenario_id"],
                        "customer_id": scenario["customer_id"],
                        "as_of_date": scenario["as_of_date"],
                        "decision_path": scenario["decision_path"],
                        "run": run_number,
                        "provider": provider,
                        "configured_model": settings.model,
                        "status": "FAIL",
                        "contract_violations": ["PIPELINE_EXCEPTION"],
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "model_calls": recorder.call_metrics,
                    })
    return records


def write_artifacts(records: list[dict[str, Any]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "ab_runs.json").write_text(
        json.dumps(records, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    comparisons = compare_records(records)
    (output_dir / "ab_comparison.json").write_text(
        json.dumps(comparisons, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    scalar_fields = [
        "scenario", "scenario_id", "customer_id", "as_of_date", "decision_path",
        "run", "provider", "configured_model", "status",
        "eligible_count", "recommended_count", "total_cost", "remaining_budget",
        "validator_status", "repair_count", "retry_count", "v2_status",
        "fallback_triggered", "latency_ms", "input_tokens", "output_tokens",
        "reasoning_tokens", "contract_violations", "error_type", "error",
    ]
    with (output_dir / "ab_runs.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=scalar_fields, extrasaction="ignore")
        writer.writeheader()
        for record in records:
            row = dict(record)
            row["contract_violations"] = "|".join(record.get("contract_violations", []))
            writer.writerow(row)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run repeatable provider-neutral V2 A/B evaluation.")
    parser.add_argument(
        "--providers",
        nargs="+",
        choices=["deepseek", "gemini"],
        default=["deepseek", "gemini"],
    )
    parser.add_argument("--runs", type=int, default=1)
    parser.add_argument("--case", action="append", dest="case_slugs")
    parser.add_argument("--deepseek-model")
    parser.add_argument("--gemini-model")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    if args.runs <= 0:
        parser.error("--runs must be positive")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir = args.output_dir or REPOSITORY_ROOT / "outputs" / "ab-evaluation" / timestamp
    records = run_evaluation(
        providers=list(dict.fromkeys(args.providers)),
        runs=args.runs,
        case_slugs=set(args.case_slugs or []) or None,
        model_overrides={
            key: value
            for key, value in {
                "deepseek": args.deepseek_model,
                "gemini": args.gemini_model,
            }.items()
            if value
        },
    )
    write_artifacts(records, output_dir)
    summary = {
        "output_dir": str(output_dir),
        "record_count": len(records),
        "pass_count": sum(item.get("status") == "PASS" for item in records),
        "fail_count": sum(item.get("status") != "PASS" for item in records),
        "comparison_count": len(compare_records(records)),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["fail_count"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
