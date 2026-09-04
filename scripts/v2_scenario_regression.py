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


# The video scenario file intentionally contains presentation slugs only.  Keep
# the join to the V2 workbook explicit so a workbook row cannot be selected by
# position, store name, or a guessed date.  01 and 06 are paired against the
# same normal-replenishment baseline by design.
SCENARIO_ID_BY_SLUG = {
    "01_high_traffic": "V2-001",
    "02_holiday_promo": "V2-018",
    "03_low_budget": "V2-004",
    "04_long_shelf": "V2-006",
    "05_fruit_focus": "V2-008",
    "06_no_budget": "V2-001",
}

SCENARIO_DECISION_PATH_BY_SLUG = {
    "01_high_traffic": "NORMAL_REPLENISHMENT",
    "02_holiday_promo": "STORE_EVENT_BASELINE",
    "03_low_budget": "HIGH_STOCKOUT_RISK",
    "04_long_shelf": "LONG_SHELF_LIFE_SOFT",
    "05_fruit_focus": "CATEGORY_PREFERENCE_SOFT",
    "06_no_budget": "NORMAL_REPLENISHMENT",
}

from services.ai_client import AIClient  # noqa: E402
from services.ai_decision import AIDecisionLayer  # noqa: E402
from services.intent_parser import IntentParser  # noqa: E402
from services.local_optimizer import LocalOptimizer  # noqa: E402
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


def load_scenario_bindings(
    workbook: dict[str, pd.DataFrame],
    video_scenarios: list[dict],
) -> list[dict]:
    """Join video slugs to exactly one audited V2 workbook scenario row.

    The video JSON remains the source of the user-facing request.  The V2
    workbook supplies the evaluation customer and date, and its DecisionPath
    is checked against the explicit mapping above.  No fallback customer or
    date is permitted because that would make a regression result ambiguous.
    """
    expected_slugs = set(SCENARIO_ID_BY_SLUG)
    observed_slugs = [str(item.get("slug") or "").strip() for item in video_scenarios]
    if len(observed_slugs) != len(set(observed_slugs)):
        raise ValueError(
            "Video scenario slugs must be unique; "
            f"observed={observed_slugs!r}"
        )
    observed_set = set(observed_slugs)
    missing_slugs = sorted(expected_slugs - observed_set)
    unknown_slugs = sorted(observed_set - expected_slugs)
    if missing_slugs or unknown_slugs:
        raise ValueError(
            "Video scenario slug set does not match the audited mapping: "
            f"missing={missing_slugs!r}, unknown={unknown_slugs!r}"
        )

    scenarios_sheet = workbook.get("V2TestScenarios")
    if scenarios_sheet is None or scenarios_sheet.empty:
        raise ValueError("V2TestScenarios sheet is required for scenario binding")
    required_columns = {"ScenarioId", "CustomerId", "AsOfDate", "DecisionPath"}
    missing_columns = sorted(required_columns - set(scenarios_sheet.columns))
    if missing_columns:
        raise ValueError(
            "V2TestScenarios is missing binding columns: "
            f"{missing_columns!r}"
        )

    scenario_ids = scenarios_sheet["ScenarioId"].astype(str).str.strip()
    expected_candidates = workbook.get("V2ExpectedCandidates")
    bindings: list[dict] = []
    for video in video_scenarios:
        slug = str(video.get("slug") or "").strip()
        scenario_id = SCENARIO_ID_BY_SLUG[slug]
        matches = scenarios_sheet.loc[scenario_ids == scenario_id]
        if len(matches) != 1:
            evidence = matches[
                [column for column in scenarios_sheet.columns if column in required_columns]
            ].to_dict("records")
            raise ValueError(
                "Scenario mapping must resolve to exactly one V2TestScenarios row: "
                f"slug={slug!r}, scenario_id={scenario_id!r}, "
                f"row_count={len(matches)}, rows={evidence!r}"
            )

        row = matches.iloc[0]
        expected_path = SCENARIO_DECISION_PATH_BY_SLUG[slug]
        raw_path = row["DecisionPath"]
        actual_path = "" if pd.isna(raw_path) else str(raw_path).strip()
        if actual_path != expected_path:
            raise ValueError(
                "Scenario mapping DecisionPath mismatch: "
                f"slug={slug!r}, scenario_id={scenario_id!r}, "
                f"expected={expected_path!r}, actual={actual_path!r}"
            )

        raw_customer_id = row["CustomerId"]
        customer_id = "" if pd.isna(raw_customer_id) else str(raw_customer_id).strip()
        if not customer_id:
            raise ValueError(
                f"Scenario mapping has empty CustomerId: slug={slug!r}, "
                f"scenario_id={scenario_id!r}"
            )
        as_of_date = pd.to_datetime(row["AsOfDate"], errors="coerce")
        if pd.isna(as_of_date):
            raise ValueError(
                f"Scenario mapping has invalid AsOfDate: slug={slug!r}, "
                f"scenario_id={scenario_id!r}, value={row['AsOfDate']!r}"
            )

        expected_candidate_count = None
        if expected_candidates is not None:
            if "ScenarioId" not in expected_candidates.columns:
                raise ValueError("V2ExpectedCandidates must contain ScenarioId")
            expected_candidate_count = int(
                (expected_candidates["ScenarioId"].astype(str).str.strip() == scenario_id).sum()
            )
            if expected_candidate_count == 0:
                raise ValueError(
                    "Mapped ScenarioId has no V2ExpectedCandidates rows: "
                    f"slug={slug!r}, scenario_id={scenario_id!r}"
                )

        bindings.append({
            **video,
            "scenario_id": scenario_id,
            "customer_id": customer_id,
            "as_of_date": pd.Timestamp(as_of_date).normalize().strftime("%Y-%m-%d"),
            "decision_path": actual_path,
            "expected_candidate_count": expected_candidate_count,
        })
    return bindings


def _scenario_contract_violations(
    scenario_slug: str,
    result: dict,
    workbook: dict[str, pd.DataFrame] | None = None,
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
    if not final_plan and scenario_slug != "05_fruit_focus":
        violations.append("FINAL_PLAN_EMPTY")
    budget = structured.get("budget")
    total_cost = result["optimizer_result"].get("total_cost")
    if budget is not None and (total_cost is None or total_cost > budget + 1e-9):
        violations.append(f"BUDGET_EXCEEDED total={total_cost!r}, budget={budget!r}")

    decisions = {
        item.get("candidate_id"): item
        for item in result.get("ai_decision", {}).get("candidate_decisions", [])
    }
    features = {
        item.get("candidate_id"): item.get("features", {})
        for item in result.get("safe_decision_context", {}).get("candidates", [])
    }
    selected_ids = {item.get("candidate_id") for item in final_plan}

    if scenario_slug == "01_high_traffic":
        if not any(
            item.get("recommended") and item.get("replenishment_intensity") == "HIGH"
            for item in decisions.values()
        ):
            violations.append("HIGH_TRAFFIC_DID_NOT_INCREASE_ANY_AI_INTENSITY")
    elif scenario_slug == "02_holiday_promo":
        if not any(item.get("baseline_source") == "STORE_EVENT" for item in final_plan):
            violations.append("STORE_EVENT_BASELINE_NOT_USED_IN_FINAL_PLAN")
    elif scenario_slug == "03_low_budget":
        selected_high = {
            candidate_id
            for candidate_id in selected_ids
            if (decisions.get(candidate_id) or {}).get("priority") == "HIGH"
        }
        if not selected_high:
            violations.append("NO_HIGH_PRIORITY_PRODUCT_RETAINED")
        high_budget_unallocated = [
            item.get("candidate_id")
            for item in result.get("optimizer_result", {}).get("unallocated_candidates", [])
            if item.get("reason") == "BUDGET_CONFLICT"
            and (decisions.get(item.get("candidate_id")) or {}).get("priority") == "HIGH"
        ]
        if high_budget_unallocated:
            violations.append(
                f"HIGH_PRIORITY_BUDGET_CONFLICT={sorted(high_budget_unallocated)!r}"
            )
    elif scenario_slug == "04_long_shelf":
        selected_long = {
            candidate_id
            for candidate_id in selected_ids
            if (features.get(candidate_id) or {}).get("shelf_life_level") == "LONG"
        }
        if not selected_long:
            violations.append("LONG_SHELF_PREFERENCE_NOT_REFLECTED_IN_FINAL_PLAN")
        elif not any(
            "long shelf-life preference" in str(reason).casefold()
            for item in final_plan
            if item.get("candidate_id") in selected_long
            for reason in item.get("why_selected", [])
        ):
            violations.append("LONG_SHELF_PREFERENCE_MISSING_FROM_DECISION_REASON")
    elif scenario_slug == "05_fruit_focus":
        high_relevance = {
            candidate_id
            for candidate_id, row in features.items()
            if row.get("category_relevance") == "HIGH"
        }
        low_relevance = {
            candidate_id
            for candidate_id, row in features.items()
            if row.get("category_relevance") == "LOW"
        }
        # Soft preference is a model decision, not permission to overstock.
        recommended_ids = {
            candidate_id for candidate_id, decision in decisions.items()
            if decision.get("recommended")
        }
        if not recommended_ids.intersection(high_relevance):
            violations.append("PREFERRED_CATEGORY_NOT_RECOMMENDED")
        high_rate = (
            len(recommended_ids.intersection(high_relevance)) / len(high_relevance)
            if high_relevance else 0.0
        )
        low_rate = (
            len(recommended_ids.intersection(low_relevance)) / len(low_relevance)
            if low_relevance else 0.0
        )
        if high_rate < low_rate:
            violations.append(
                f"PREFERRED_CATEGORY_RECOMMENDATION_RATE_LOWER high={high_rate:.3f}, low={low_rate:.3f}"
            )
        # Require workbook evidence for zero-gap exemptions. An unallocated
        # reason alone is not sufficient evidence that a purchase was unnecessary.
        if workbook is None:
            violations.append("PREFERRED_CATEGORY_INVENTORY_EVIDENCE_MISSING")
        else:
            optimizer = LocalOptimizer()
            zero_gap_preferred: set[str] = set()
            as_of = pd.Timestamp(result["effective_as_of_date"])
            candidates = {
                row["candidate_id"]: row
                for row in result["candidate_pool"]["eligible_candidates"]
            }
            unallocated = {
                row["candidate_id"]: row.get("reason")
                for row in result["optimizer_result"].get("unallocated_candidates", [])
            }
            for candidate_id in sorted(high_relevance):
                candidate = {**candidates[candidate_id], "features": features[candidate_id]}
                _, baseline = optimizer._demand_baseline(
                    workbook, structured["store_id"], candidate_id, structured,
                    candidate, as_of, int(candidate["sales_unit"]),
                )
                stock = optimizer._current_stock(
                    workbook["Inventory"], structured["store_id"], candidate_id, as_of,
                )
                if baseline <= stock:
                    zero_gap_preferred.add(candidate_id)
                    if candidate_id in selected_ids:
                        violations.append(f"ZERO_GAP_PREFERRED_CATEGORY_PURCHASED={candidate_id}")
                    if candidate_id in recommended_ids and unallocated.get(candidate_id) != "NO_EXECUTABLE_QUANTITY":
                        violations.append(f"ZERO_GAP_PREFERRED_CATEGORY_REASON_MISSING={candidate_id}")
                elif candidate_id in recommended_ids and candidate_id not in selected_ids:
                    violations.append(f"POSITIVE_GAP_PREFERRED_CATEGORY_NOT_SELECTED={candidate_id}")
            if not final_plan and not recommended_ids.issubset(zero_gap_preferred):
                violations.append("FINAL_PLAN_EMPTY")
    elif scenario_slug == "06_no_budget":
        if result.get("optimizer_result", {}).get("remaining_budget") is not None:
            violations.append("NO_BUDGET_MODE_HAS_REMAINING_BUDGET")
        if any(
            "BUDGET_CAPPED" in item.get("constraint_adjustments", [])
            for item in final_plan
        ):
            violations.append("NO_BUDGET_MODE_APPLIED_BUDGET_CAP")
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
    scenarios = load_scenario_bindings(workbook, scenarios)
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
                scenario["customer_id"],
                scenario["request"],
                scenario["as_of_date"],
            )
            trace = result["decision_trace"]
            contract_violations = _scenario_contract_violations(scenario["slug"], result, workbook)
            reports.append({
                "case": scenario["slug"],
                "scenario_id": scenario["scenario_id"],
                "customer_id": scenario["customer_id"],
                "as_of_date": scenario["as_of_date"],
                "decision_path": scenario["decision_path"],
                "expected_candidate_count": scenario["expected_candidate_count"],
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
                "scenario_id": scenario["scenario_id"],
                "customer_id": scenario["customer_id"],
                "as_of_date": scenario["as_of_date"],
                "decision_path": scenario["decision_path"],
                "expected_candidate_count": scenario["expected_candidate_count"],
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
                "scenario_id": item.get("scenario_id"),
                "customer_id": item.get("customer_id"),
                "as_of_date": item.get("as_of_date"),
                "decision_path": item.get("decision_path"),
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
                "scenario_id": item.get("scenario_id"),
                "customer_id": item.get("customer_id"),
                "as_of_date": item.get("as_of_date"),
                "decision_path": item.get("decision_path"),
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
