from __future__ import annotations

import logging
import json
import re
from typing import Any

from services.ai_client import AIClient, AIClientError
from services.procurement_understanding import ProcurementUnderstandingBuilder

logger = logging.getLogger(__name__)


INTENT_SYSTEM_PROMPT = """You are a procurement consultant semantic understanding engine.

Analyze the user's procurement request and return JSON only.

Return both backward-compatible extracted fields and consultant-style understanding.

Top-level JSON fields:
- budget: numeric budget amount, null if not mentioned
- traffic_level: "HIGH" or "NORMAL"
- promotion_flag: boolean
- shelf_life_preference: "LONG" or "NORMAL"
- preferred_category: string or null
- excluded_category: string or null
- time_range: "today", "this_week", "next_week", "holiday_window", "normal", or "unknown"
- expected_intent: brief English summary
- business_intent: object
- decision_signals: object
- uncertainty: object
- missing_information: array
- recommendation_readiness: object
- store_context: object
- store_considerations: array of up to 3 short sentences

business_intent:
- primary_intent: "stockout_prevention", "seasonal_preparation", "promotion_support", "trial_growth", "budget_optimization", "waste_reduction", "supplier_planning", or "general_planning"
- secondary_intents: array of strings
- decision_type: "routine_reorder", "urgent_action", "planning", "exploratory", or "optimization"
- urgency: "low", "medium", "high", or "critical"
- intent_summary: one sentence

decision_signals:
- expected_demand_change: "increase", "decrease", "stable", or "unknown"
- demand_driver: "traffic", "holiday", "promotion", "seasonality", "event", or "unknown"
- stockout_sensitivity: "low", "medium", or "high"
- waste_sensitivity: "low", "medium", or "high"
- price_sensitivity: "low", "medium", or "high"
- growth_appetite: "low", "medium", or "high"
- budget_strictness: "none", "soft", or "strict"
- substitution_allowed: boolean

uncertainty:
- overall_confidence: number from 0 to 1
- field_sources: object with keys budget, traffic_level, promotion_flag, shelf_life_preference, category, time_horizon. Values: "explicit", "inferred", or "missing"
- low_confidence_fields: array of strings

missing_information item:
- field: string
- importance: "optional", "recommended", or "high_risk"
- impact: one sentence
- suggested_question: one question

recommendation_readiness:
- can_generate_recommendation: boolean
- should_ask_follow_up: boolean
- confidence_level: "low", "medium", or "high"
- confidence_score: number from 0 to 1
- confidence_drivers: array of short sentences
- confidence_risks: array of short sentences
- follow_up_question: string, empty when no follow-up is needed

Rules:
- Missing budget is optional and must not block recommendations. Set budget_strictness to "none".
- If user says "under", "within", "do not exceed", or gives a hard budget, set budget_strictness to "strict".
- If user says "around" or "if possible" with budget, set budget_strictness to "soft".
- High traffic, busy periods, events, holidays, or promotions imply demand increase.
- Avoiding short shelf-life or fresh products implies high waste sensitivity.
- High-risk missing information should set should_ask_follow_up=true but can_generate_recommendation must remain true.
- If the request is vague and lacks business goal, demand driver, category and budget, use this exact follow-up question: "Are you optimizing for stockout prevention, budget control, or growth?"
- Otherwise, set should_ask_follow_up to false and continue recommendations.
- A trusted store profile may be supplied in a separate system message. Use it to interpret the request, but do not alter its identity fields.
"""


class IntentParser:
    """Parses user input into structured procurement intent using AI."""

    def __init__(
        self,
        ai_client: AIClient | None = None,
        understanding_builder: ProcurementUnderstandingBuilder | None = None,
    ) -> None:
        self.ai_client = ai_client or AIClient()
        self.understanding_builder = understanding_builder or ProcurementUnderstandingBuilder()

    def parse_intent(
        self,
        user_input: str,
        store_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.ai_client.is_available:
            logger.info("AI not available, using fallback parsing.")
            return self._with_store_context(
                self._with_analysis_source(self._fallback_parse(user_input), "fallback"),
                store_context,
            )

        messages = [
            {"role": "system", "content": INTENT_SYSTEM_PROMPT},
            {
                "role": "system",
                "content": (
                    "Trusted store context from the internal customer master. "
                    "Do not change these identity fields: "
                    f"{json.dumps(store_context or {}, ensure_ascii=True)}"
                ),
            },
            {"role": "user", "content": user_input},
        ]

        try:
            result = self.ai_client.chat_completion_json(messages)
            return self._with_store_context(
                self._with_analysis_source(self._normalize_intent(result), "live"),
                store_context,
                result.get("store_considerations"),
            )
        except AIClientError as exc:
            logger.warning("Intent parsing failed, using fallback: %s", exc)
            return self._with_store_context(
                self._with_analysis_source(self._fallback_parse(user_input), "fallback"),
                store_context,
            )

    @staticmethod
    def _with_analysis_source(intent: dict[str, Any], status: str) -> dict[str, Any]:
        """Preserve whether the understanding came from DeepSeek or local fallback rules."""
        enriched = dict(intent)
        enriched["AIAnalysisStatus"] = status
        enriched["AIAnalysisSource"] = "DeepSeek" if status == "live" else "Rules fallback"
        return enriched

    @staticmethod
    def _with_store_context(
        intent: dict[str, Any],
        store_context: dict[str, Any] | None,
        store_considerations: Any = None,
    ) -> dict[str, Any]:
        """Attach master-data store context and discard any model-supplied identity changes."""
        enriched = dict(intent)
        trusted_context = {
            key: str((store_context or {}).get(key, ""))
            for key in ("CustomerId", "StoreName", "Industry", "Region", "StoreLevel", "CustomerStage")
        }
        enriched["StoreContext"] = trusted_context

        considerations = []
        if isinstance(store_considerations, list):
            considerations = [str(item).strip() for item in store_considerations if str(item).strip()][:3]
        if not considerations and trusted_context["StoreName"]:
            considerations.append(
                f'{trusted_context["StoreLevel"]} store scale is applied to recommended quantities.'
            )
            if trusted_context["CustomerStage"].casefold() == "new":
                considerations.append("New-store trial purchases are kept conservative.")
            if trusted_context["Industry"]:
                considerations.append(
                    f'Growth opportunities are evaluated for the {trusted_context["Industry"]} industry.'
                )
        enriched["StoreConsiderations"] = considerations
        return enriched

    def _normalize_intent(self, raw: dict[str, Any]) -> dict[str, Any]:
        return self.understanding_builder.normalize_ai_response(raw)

    def _fallback_parse(self, user_input: str) -> dict[str, Any]:
        """Simple keyword-based fallback when AI is unavailable."""
        lower = user_input.lower()
        intent = self._empty_intent()

        if any(w in lower for w in ["budget", "nzd", "nz$", "$", "dollar"]):
            match = re.search(r'(\d+(?:\.\d+)?)', lower)
            if match:
                intent["Budget"] = float(match.group(1))

        if any(w in lower for w in ["traffic", "busy", "rush", "crowd"]):
            intent["TrafficLevel"] = "HIGH"

        if any(w in lower for w in ["christmas", "holiday", "festival", "promotion"]):
            intent["PromotionFlag"] = True
            intent["TimeRange"] = "holiday_window"
        elif "next week" in lower:
            intent["TimeRange"] = "next_week"
        elif "this week" in lower:
            intent["TimeRange"] = "this_week"

        if any(w in lower for w in ["short shelf", "perishable", "avoid fresh", "no fresh", "long shelf"]):
            intent["ShelfLifePreference"] = "LONG"

        exclude_patterns = ["avoid ", "exclude ", "no "]
        for cat in ["fruit", "vegetable", "dairy", "frozen", "dry", "fresh"]:
            for pattern in exclude_patterns:
                if f"{pattern}{cat}" in lower:
                    intent["ExcludedCategory"] = cat.capitalize()
                    break
            if intent["ExcludedCategory"]:
                break

        if "prefer" in lower or "focus" in lower:
            for cat in ["fruit", "vegetable", "dairy", "frozen", "dry", "fresh"]:
                if cat in lower:
                    intent["PreferredCategory"] = cat.capitalize()
                    break

        intent["ExpectedIntent"] = user_input[:100]
        return self.understanding_builder.build_from_base(intent)

    @staticmethod
    def _empty_intent() -> dict[str, Any]:
        return {
            "Budget": None,
            "TrafficLevel": "NORMAL",
            "PromotionFlag": False,
            "ShelfLifePreference": "NORMAL",
            "PreferredCategory": None,
            "ExcludedCategory": None,
            "TimeRange": "normal",
            "ExpectedIntent": "",
        }
