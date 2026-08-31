from __future__ import annotations

import json
import argparse
from dataclasses import replace
from pathlib import Path
import sys

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


SCENARIO_EXPECTATIONS = {
    "01_high_traffic": {"budget": 1000.0, "traffic_expectation": "HIGH"},
    "02_holiday_promo": {
        "budget": 1000.0,
        "traffic_expectation": "HIGH",
        "occasion": "CHRISTMAS",
    },
    "03_low_budget": {"budget": 300.0, "objective": "PREVENT_STOCKOUT"},
    "04_long_shelf": {
        "budget": 1000.0,
        "soft_preference": {"type": "SHELF_LIFE", "value": "LONG"},
    },
    "05_fruit_focus": {
        "budget": 800.0,
        "category": "Fruit",
        "soft_preference": {"type": "CATEGORY", "value": "Fruit"},
    },
    "06_no_budget": {"budget": None, "traffic_expectation": "HIGH"},
}


def _scenario_contract_violations(
    scenario_slug: str,
    result: dict,
) -> list[str]:
    """Evaluate known Demo semantics without turning them into runtime business rules."""
    violations: list[str] = []
    expected = SCENARIO_EXPECTATIONS[scenario_slug]
    structured = result["safe_decision_context"]["structured_intent"]
    intent_source = result["intent"].get("AIAnalysisStatus")

    if intent_source != "live":
        violations.append(f"INTENT_SOURCE={intent_source!r}, expected 'live'")
    for field in ("budget", "traffic_expectation", "occasion", "objective"):
        if field in expected and structured.get(field) != expected[field]:
            violations.append(
                f"INTENT_{field.upper()}={structured.get(field)!r}, expected {expected[field]!r}"
            )
    if expected.get("category") not in structured.get("category_preference", []):
        if "category" in expected:
            violations.append(
                f"CATEGORY_PREFERENCE missing {expected['category']!r}"
            )
    if expected.get("soft_preference") not in structured.get("soft_preferences", []):
        if "soft_preference" in expected:
            violations.append(
                f"SOFT_PREFERENCE missing {expected['soft_preference']!r}"
            )

    validation = result["validation_result"]
    if validation.get("status") != "PASS" or validation.get("valid") is not True:
        violations.append(f"VALIDATOR={validation.get('status')!r}")
    if result.get("v2_status") != "SUCCESS":
        violations.append(f"V2_STATUS={result.get('v2_status')!r}")
    if result.get("fallback_triggered"):
        violations.append("FALLBACK_TRIGGERED")

    final_plan = result.get("final_purchase_plan", [])
    if not final_plan:
        violations.append("FINAL_PLAN_EMPTY")
    budget = structured.get("budget")
    total_cost = result["optimizer_result"].get("total_cost")
    if budget is not None and (total_cost is None or total_cost > budget + 1e-9):
        violations.append(f"BUDGET_EXCEEDED total={total_cost!r}, budget={budget!r}")
    return violations


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compact", action="store_true")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print only the business and constraint outcome for each scenario.",
    )
    parser.add_argument("--case", dest="case_slug")
    parser.add_argument("--provider", choices=["deepseek", "gemini"], default="deepseek")
    parser.add_argument("--model")
    args = parser.parse_args()
    workbook = pd.read_excel(
        REPOSITORY_ROOT / "data" / "AI_Demo_Data_Pack_V2_Large.xlsx",
        sheet_name=None,
        engine="openpyxl",
    )
    scenarios = json.loads(
        (REPOSITORY_ROOT / "videos" / "procurement-scenarios" / "media" / "scenarios.json")
        .read_text(encoding="utf-8")
    )
    if args.case_slug:
        scenarios = [item for item in scenarios if item["slug"] == args.case_slug]
    reports = []
    any_failure = False
    for scenario in scenarios:
        model_settings = _settings_for(args.provider)
        if args.model:
            model_settings = replace(model_settings, model=args.model)
        client = AIClient(settings=model_settings)
        pipeline = V2DecisionPipeline(
            preparation=V2PreparationPipeline(intent_parser=IntentParser(ai_client=client)),
            decision_layer=AIDecisionLayer(ai_client=client),
        )
        try:
            result = pipeline.run(
                workbook,
                "C001",
                scenario["request"],
                "2026-06-02",
            )
            trace = result["decision_trace"]
            contract_violations = _scenario_contract_violations(scenario["slug"], result)
            reports.append({
                "case": scenario["slug"],
                "intent": result["safe_decision_context"]["structured_intent"],
                "intent_source": result["intent"].get("AIAnalysisStatus"),
                "event_context": result.get("event_context"),
                "candidate_pool": trace["candidate_pool"],
                "safe_features": result["safe_decision_context"]["candidates"],
                "ai_decision": result["ai_decision"],
                "optimizer_result": result["optimizer_result"],
                "validator_result": result["validation_result"],
                "repair_count": result["repair_count"],
                "retry_count": result["retry_count"],
                "final_plan": result["final_purchase_plan"],
                "why_selected": {
                    item["candidate_id"]: item.get("why_selected", [])
                    for item in result["final_purchase_plan"]
                },
                "pipeline_version": result["pipeline_version"],
                "v2_status": result["v2_status"],
                "fallback_triggered": result["fallback_triggered"],
                "contract_violations": contract_violations,
            })
            any_failure = any_failure or bool(contract_violations)
        except Exception as exc:
            any_failure = True
            reports.append({
                "case": scenario["slug"],
                "pipeline_version": "V2",
                "v2_status": "FAILED",
                "fallback_triggered": False,
                "contract_violations": ["PIPELINE_EXCEPTION"],
                "error_type": type(exc).__name__,
                "error": str(exc),
            })
    output = reports
    if args.summary:
        output = [
            {
                "case": item["case"],
                "intent": {
                    key: item.get("intent", {}).get(key)
                    for key in (
                        "budget",
                        "traffic_expectation",
                        "occasion",
                        "category_preference",
                        "hard_constraints",
                        "soft_preferences",
                    )
                },
                "intent_source": item.get("intent_source"),
                "eligible_count": len(item.get("candidate_pool", {}).get("eligible", [])),
                "recommended_count": sum(
                    1
                    for row in item.get("ai_decision", {}).get("candidate_decisions", [])
                    if row.get("recommended")
                ),
                "final_line_count": len(item.get("final_plan", [])),
                "total_cost": item.get("optimizer_result", {}).get("total_cost"),
                "remaining_budget": item.get("optimizer_result", {}).get("remaining_budget"),
                "validator_status": item.get("validator_result", {}).get("status"),
                "repair_count": item.get("repair_count"),
                "retry_count": item.get("retry_count"),
                "pipeline_version": item.get("pipeline_version"),
                "v2_status": item.get("v2_status"),
                "fallback_triggered": item.get("fallback_triggered"),
                "contract_violations": item.get("contract_violations", []),
                "error": item.get("error"),
            }
            for item in reports
        ]
    elif args.compact:
        output = [
            {
                "case": item["case"],
                "intent": item.get("intent"),
                "intent_source": item.get("intent_source"),
                "event_context": item.get("event_context"),
                "eligible_count": len(item.get("candidate_pool", {}).get("eligible", [])),
                "recommended": [
                    {
                        "id": row["candidate_id"],
                        "priority": row["priority"],
                        "intensity": row["replenishment_intensity"],
                    }
                    for row in item.get("ai_decision", {}).get("candidate_decisions", [])
                    if row.get("recommended")
                ],
                "baseline_sources": sorted({
                    row.get("baseline_source")
                    for row in item.get("optimizer_result", {}).get("purchase_plan", [])
                    if row.get("baseline_source")
                }),
                "total_cost": item.get("optimizer_result", {}).get("total_cost"),
                "remaining_budget": item.get("optimizer_result", {}).get("remaining_budget"),
                "validator_status": item.get("validator_result", {}).get("status"),
                "repair_count": item.get("repair_count"),
                "retry_count": item.get("retry_count"),
                "final_plan": [
                    {
                        "id": row["candidate_id"],
                        "qty": row["final_qty"],
                        "sales_unit": row["sales_unit"],
                        "cost": row["estimated_cost"],
                        "priority": row["priority"],
                        "why": row.get("why_selected", []),
                    }
                    for row in item.get("final_plan", [])
                ],
                "pipeline_version": item.get("pipeline_version"),
                "v2_status": item.get("v2_status"),
                "fallback_triggered": item.get("fallback_triggered"),
                "contract_violations": item.get("contract_violations", []),
                "error": item.get("error"),
            }
            for item in reports
        ]
    print(json.dumps(output, ensure_ascii=False, indent=2, default=str))
    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
