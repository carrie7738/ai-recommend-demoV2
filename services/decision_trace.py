from __future__ import annotations

from copy import deepcopy
from typing import Any


class WhySelectedBuilder:
    """Turn verified decision signals into deterministic user-facing reasons."""

    EXACT_REASONS = {
        "USER_REQUESTED": "Explicitly requested by the user.",
        "STOCKOUT_RISK=HIGH": "High stockout risk makes replenishment urgent.",
        "STOCKOUT_RISK=MEDIUM": "Moderate stockout risk supports planned replenishment.",
        "PURCHASE_FREQUENCY=HIGH": "Frequently purchased by this store.",
        "PURCHASE_FREQUENCY=MEDIUM": "Regular purchase history supports replenishment.",
        "PRODUCT_DEMAND_TREND=UP": "Demand trend is increasing.",
        "BASELINE_SOURCE=STORE_EVENT": "Supported by this store's comparable event history.",
        "BASELINE_SOURCE=PEER_EVENT": "Supported by comparable peer event history.",
        "BASELINE_SOURCE=RECENT_STORE": "Supported by the store's recent purchase baseline.",
    }

    def build(
        self,
        decision: dict[str, Any],
        structured_intent: dict[str, Any] | None = None,
    ) -> list[str]:
        reasons: list[str] = []
        for signal in decision.get("decision_signals", []):
            reason = self._intent_reason(signal, structured_intent or {})
            reason = reason or self.EXACT_REASONS.get(signal) or self._family_reason(signal)
            if reason and reason not in reasons:
                reasons.append(reason)
        return reasons

    @staticmethod
    def _intent_reason(signal: str, intent: dict[str, Any]) -> str | None:
        soft = intent.get("soft_preferences", [])
        hard = intent.get("hard_constraints", [])
        if signal == "SHELF_LIFE_LEVEL=LONG":
            if any(
                isinstance(item, dict)
                and str(item.get("type") or "").upper() == "SHELF_LIFE"
                and str(item.get("value") or "").upper() == "LONG"
                for item in hard
            ):
                return "Satisfies the user's long shelf-life requirement."
            if any(
                isinstance(item, dict)
                and str(item.get("type") or "").upper() == "SHELF_LIFE"
                and str(item.get("value") or "").upper() == "LONG"
                for item in soft
            ):
                return "Matches the user's long shelf-life preference."
        if signal == "CATEGORY_RELEVANCE=HIGH":
            if any(
                isinstance(item, dict)
                and str(item.get("type") or "").upper() == "CATEGORY"
                for item in hard
            ):
                return "Satisfies the user's category constraint."
            if any(
                isinstance(item, dict)
                and str(item.get("type") or "").upper() == "CATEGORY"
                for item in soft
            ) or intent.get("category_preference"):
                return "Matches the user's category preference."
        return None

    @staticmethod
    def _family_reason(signal: str) -> str | None:
        if signal.startswith("PEER_PURCHASE_RATIO="):
            return "Peer purchase evidence supports this candidate."
        if signal.startswith("OCCASION="):
            occasion = signal.partition("=")[2].replace("_", " ").title()
            return f"Relevant to the {occasion} purchase window."
        if signal.startswith("SHELF_LIFE_LEVEL="):
            level = signal.partition("=")[2].lower()
            return f"Shelf-life profile is {level}."
        if signal.startswith("CATEGORY_RELEVANCE="):
            level = signal.partition("=")[2].lower()
            return f"Category relevance is {level}."
        if signal.startswith("STOCKOUT_RISK="):
            level = signal.partition("=")[2].lower()
            return f"Stockout risk is {level}."
        if signal.startswith("PURCHASE_FREQUENCY="):
            level = signal.partition("=")[2].lower()
            return f"Purchase frequency is {level}."
        if signal.startswith("PRODUCT_DEMAND_TREND="):
            direction = signal.partition("=")[2].lower()
            return f"Product demand trend is {direction}."
        if signal.startswith("BASELINE_SOURCE="):
            source = signal.partition("=")[2].replace("_", " ").lower()
            return f"Quantity baseline comes from {source} data."
        return None


class DecisionTraceBuilder:
    """Build the compact V2 trajectory used for audit and presentation."""

    def __init__(self, why_builder: WhySelectedBuilder | None = None) -> None:
        self.why_builder = why_builder or WhySelectedBuilder()

    def build(
        self,
        user_request: str,
        prepared: dict[str, Any],
        decision_attempts: list[dict[str, Any]],
        optimizer_result: dict[str, Any],
        validation_result: dict[str, Any],
    ) -> dict[str, Any]:
        final_decision = decision_attempts[-1]
        structured_intent = prepared["safe_decision_context"]["structured_intent"]
        decisions = {
            item["candidate_id"]: item
            for item in final_decision["candidate_decisions"]
        }
        product_names = {
            item["candidate_id"]: str(item.get("product_name") or item["candidate_id"])
            for item in prepared["candidate_pool"]["eligible_candidates"]
        }
        presented_decisions = [
            {
                **deepcopy(item),
                "product_name": product_names.get(item["candidate_id"], item["candidate_id"]),
                "why_selected": self.why_builder.build(item, structured_intent),
            }
            for item in final_decision["candidate_decisions"]
        ]
        final_plan: list[dict[str, Any]] = []
        if validation_result.get("status") == "PASS" and validation_result.get("valid") is True:
            for item in optimizer_result["purchase_plan"]:
                decision = decisions[item["candidate_id"]]
                final_plan.append({
                    **deepcopy(item),
                    "why_selected": self.why_builder.build(decision, structured_intent),
                })

        raw_pool = prepared["candidate_pool"]
        candidate_summary = {
            "eligible": [
                {
                    "candidate_id": item["candidate_id"],
                    "recommendation_type": item["recommendation_type"],
                    "candidate_source": item["candidate_source"],
                    "product_name": str(item.get("product_name") or item["candidate_id"]),
                }
                for item in raw_pool["eligible_candidates"]
            ],
            "rejected": [
                {
                    "candidate_id": item["candidate_id"],
                    "rejection_code": item["rejection_code"],
                }
                for item in raw_pool["rejected_candidates"]
            ],
        }
        return {
            "user_request": user_request,
            "structured_intent": deepcopy(structured_intent),
            "candidate_pool": candidate_summary,
            "decision_features": deepcopy(prepared["safe_decision_context"]["candidates"]),
            "model_decision_attempts": deepcopy(decision_attempts),
            "procurement_strategy": deepcopy(final_decision["procurement_strategy"]),
            "candidate_decisions": presented_decisions,
            "optimizer_result": deepcopy(optimizer_result),
            "validation_result": deepcopy(validation_result),
            "final_result": {
                "status": "VALID" if final_plan or validation_result["valid"] else "VALIDATION_FAILED",
                "purchase_plan": final_plan,
                "unallocated_candidates": deepcopy(
                    optimizer_result["unallocated_candidates"]
                ),
            },
        }
