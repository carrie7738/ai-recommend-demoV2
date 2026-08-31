from __future__ import annotations

from typing import Any

import pandas as pd

from services.ai_decision import AIDecisionLayer
from services.local_optimizer import LocalOptimizer
from services.hard_validator import HardValidator
from services.decision_trace import DecisionTraceBuilder
from services.v2_preparation import V2PreparationPipeline


class V2DecisionPipeline:
    """Compose Task 1-3 preparation with the provider-neutral Task 4 decision layer."""

    def __init__(
        self,
        preparation: V2PreparationPipeline | None = None,
        decision_layer: AIDecisionLayer | None = None,
        optimizer: LocalOptimizer | None = None,
        validator: HardValidator | None = None,
        trace_builder: DecisionTraceBuilder | None = None,
    ) -> None:
        self.preparation = preparation or V2PreparationPipeline()
        self.decision_layer = decision_layer or AIDecisionLayer()
        self.optimizer = optimizer or LocalOptimizer()
        self.validator = validator or HardValidator()
        self.trace_builder = trace_builder or DecisionTraceBuilder()

    def run(
        self,
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        user_input: str,
        as_of_date: Any,
        parsed_intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        prepared = self.preparation.prepare(
            workbook,
            customer_id,
            user_input,
            as_of_date,
            parsed_intent=parsed_intent,
        )
        ai_decision = self.decision_layer.decide(prepared["safe_decision_context"])
        safe_candidates = {
            item["candidate_id"]: item
            for item in prepared["safe_decision_context"]["candidates"]
        }
        optimizer_candidates = [
            {**item, "features": safe_candidates.get(item["candidate_id"], {}).get("features", {})}
            for item in prepared["candidate_pool"]["eligible_candidates"]
        ]
        optimizer_result = self.optimizer.optimize(
            workbook=workbook,
            customer_id=customer_id,
            structured_intent=prepared["safe_decision_context"]["structured_intent"],
            eligible_candidates=optimizer_candidates,
            ai_decision=ai_decision,
            as_of_date=prepared.get("effective_as_of_date", as_of_date),
        )
        validation_result = self.validator.validate(
            workbook=workbook,
            structured_intent=prepared["safe_decision_context"]["structured_intent"],
            eligible_candidates=prepared["candidate_pool"]["eligible_candidates"],
            ai_decision=ai_decision,
            optimizer_result=optimizer_result,
        )
        repair_attempts: list[dict[str, Any]] = []
        if not validation_result["valid"] and not validation_result["requires_model_retry"]:
            repaired = self.validator.repair(
                workbook,
                prepared["safe_decision_context"]["structured_intent"],
                optimizer_result,
                validation_result["violations"],
            )
            if repaired.get("repair_applied"):
                repair_attempts.append({
                    "before": optimizer_result,
                    "actions": repaired.get("repair_actions", []),
                })
                optimizer_result = repaired
                validation_result = self.validator.validate(
                    workbook=workbook,
                    structured_intent=prepared["safe_decision_context"]["structured_intent"],
                    eligible_candidates=prepared["candidate_pool"]["eligible_candidates"],
                    ai_decision=ai_decision,
                    optimizer_result=optimizer_result,
                )
        decision_attempts = [ai_decision]
        if validation_result["requires_model_retry"]:
            ai_decision = self.decision_layer.retry_decision(
                prepared["safe_decision_context"],
                ai_decision,
                validation_result["retry_feedback"],
            )
            decision_attempts.append(ai_decision)
            optimizer_result = self.optimizer.optimize(
                workbook=workbook,
                customer_id=customer_id,
                structured_intent=prepared["safe_decision_context"]["structured_intent"],
                eligible_candidates=optimizer_candidates,
                ai_decision=ai_decision,
                as_of_date=prepared.get("effective_as_of_date", as_of_date),
            )
            validation_result = self.validator.validate(
                workbook=workbook,
                structured_intent=prepared["safe_decision_context"]["structured_intent"],
                eligible_candidates=prepared["candidate_pool"]["eligible_candidates"],
                ai_decision=ai_decision,
                optimizer_result=optimizer_result,
            )
            if not validation_result["valid"] and not validation_result["requires_model_retry"]:
                repaired = self.validator.repair(
                    workbook,
                    prepared["safe_decision_context"]["structured_intent"],
                    optimizer_result,
                    validation_result["violations"],
                )
                if repaired.get("repair_applied"):
                    repair_attempts.append({
                        "before": optimizer_result,
                        "actions": repaired.get("repair_actions", []),
                    })
                    optimizer_result = repaired
                    validation_result = self.validator.validate(
                        workbook=workbook,
                        structured_intent=prepared["safe_decision_context"]["structured_intent"],
                        eligible_candidates=prepared["candidate_pool"]["eligible_candidates"],
                        ai_decision=ai_decision,
                        optimizer_result=optimizer_result,
                    )
        decision_trace = self.trace_builder.build(
            user_request=user_input,
            prepared=prepared,
            decision_attempts=decision_attempts,
            optimizer_result=optimizer_result,
            validation_result=validation_result,
        )
        v2_status = "SUCCESS" if validation_result["status"] == "PASS" else "FAILED"
        pipeline_status = {
            "pipeline_version": "V2",
            "v2_status": v2_status,
            "fallback_triggered": False,
            "fallback_reason": None,
        }
        decision_trace["pipeline_status"] = pipeline_status
        return {
            **prepared,
            "ai_decision": ai_decision,
            "optimizer_result": optimizer_result,
            "validation_result": validation_result,
            "decision_attempts": decision_attempts,
            "retry_count": len(decision_attempts) - 1,
            "repair_attempts": repair_attempts,
            "repair_count": len(repair_attempts),
            "decision_trace": decision_trace,
            "final_purchase_plan": decision_trace["final_result"]["purchase_plan"],
            **pipeline_status,
        }
