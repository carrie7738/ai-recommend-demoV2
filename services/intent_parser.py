from __future__ import annotations

from services.runtime_trace import observed, record

import logging
import json
import re
from typing import Any

from jsonschema import Draft202012Validator

from services.ai_client import AIClient, AIClientError
from services.procurement_understanding import ProcurementUnderstandingBuilder
from services.request_constraints import fallback_budget, product_is_excluded

logger = logging.getLogger(__name__)


INTENT_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "budget", "traffic_level", "promotion_flag", "shelf_life_preference",
        "preferred_category", "excluded_category", "time_range", "expected_intent",
        "business_intent", "decision_signals", "uncertainty", "missing_information",
        "recommendation_readiness", "structured_intent", "store_context",
        "store_considerations",
    ],
    "properties": {
        "budget": {"type": ["number", "null"]},
        "traffic_level": {"enum": ["HIGH", "NORMAL"]},
        "promotion_flag": {"type": "boolean"},
        "shelf_life_preference": {"enum": ["LONG", "NORMAL"]},
        "preferred_category": {"type": ["string", "null"]},
        "excluded_category": {"type": ["string", "null"]},
        "time_range": {
            "enum": ["today", "this_week", "next_week", "holiday_window", "normal", "unknown"]
        },
        "expected_intent": {"type": "string"},
        "business_intent": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "primary_intent", "secondary_intents", "decision_type", "urgency",
                "intent_summary",
            ],
            "properties": {
                "primary_intent": {
                    "enum": [
                        "stockout_prevention", "seasonal_preparation", "promotion_support",
                        "trial_growth", "budget_optimization", "waste_reduction",
                        "supplier_planning", "general_planning",
                    ]
                },
                "secondary_intents": {"type": "array", "items": {"type": "string"}},
                "decision_type": {
                    "enum": ["routine_reorder", "urgent_action", "planning", "exploratory", "optimization"]
                },
                "urgency": {"enum": ["low", "medium", "high", "critical"]},
                "intent_summary": {"type": "string"},
            },
        },
        "decision_signals": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "expected_demand_change", "demand_driver", "stockout_sensitivity",
                "waste_sensitivity", "price_sensitivity", "growth_appetite",
                "budget_strictness", "substitution_allowed",
            ],
            "properties": {
                "expected_demand_change": {"enum": ["increase", "decrease", "stable", "unknown"]},
                "demand_driver": {"enum": ["traffic", "holiday", "promotion", "seasonality", "event", "unknown"]},
                "stockout_sensitivity": {"enum": ["low", "medium", "high"]},
                "waste_sensitivity": {"enum": ["low", "medium", "high"]},
                "price_sensitivity": {"enum": ["low", "medium", "high"]},
                "growth_appetite": {"enum": ["low", "medium", "high"]},
                "budget_strictness": {"enum": ["none", "soft", "strict"]},
                "substitution_allowed": {"type": "boolean"},
            },
        },
        "uncertainty": {
            "type": "object",
            "additionalProperties": False,
            "required": ["overall_confidence", "field_sources", "low_confidence_fields"],
            "properties": {
                "overall_confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "field_sources": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "budget", "traffic_level", "promotion_flag",
                        "shelf_life_preference", "category", "time_horizon",
                    ],
                    "properties": {
                        key: {"enum": ["explicit", "inferred", "missing"]}
                        for key in [
                            "budget", "traffic_level", "promotion_flag",
                            "shelf_life_preference", "category", "time_horizon",
                        ]
                    },
                },
                "low_confidence_fields": {"type": "array", "items": {"type": "string"}},
            },
        },
        "missing_information": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["field", "importance", "impact", "suggested_question"],
                "properties": {
                    "field": {"type": "string"},
                    "importance": {"enum": ["optional", "recommended", "high_risk"]},
                    "impact": {"type": "string"},
                    "suggested_question": {"type": "string"},
                },
            },
        },
        "recommendation_readiness": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "can_generate_recommendation", "should_ask_follow_up", "confidence_level",
                "confidence_score", "confidence_drivers", "confidence_risks",
                "follow_up_question",
            ],
            "properties": {
                "can_generate_recommendation": {"type": "boolean"},
                "should_ask_follow_up": {"type": "boolean"},
                "confidence_level": {"enum": ["low", "medium", "high"]},
                "confidence_score": {"type": "number", "minimum": 0, "maximum": 1},
                "confidence_drivers": {"type": "array", "items": {"type": "string"}},
                "confidence_risks": {"type": "array", "items": {"type": "string"}},
                "follow_up_question": {"type": "string"},
            },
        },
        "structured_intent": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "store_id", "budget", "objective", "traffic_expectation", "occasion",
                "category_preference", "hard_constraints", "soft_preferences",
                "explicit_products",
            ],
            "properties": {
                "store_id": {"type": "string"},
                "budget": {"type": ["number", "null"]},
                "objective": {
                    "enum": [
                        "PREVENT_STOCKOUT",
                        "SEASONAL_PREPARATION",
                        "DISCOVER_NEW_OPPORTUNITY",
                        "BUDGET_OPTIMIZATION",
                        "REDUCE_WASTE",
                        "SUPPLIER_PLANNING",
                        "GENERAL_PLANNING",
                    ]
                },
                "traffic_expectation": {"enum": ["HIGH", "NORMAL", "LOW"]},
                "occasion": {"enum": ["CHRISTMAS", "NONE"]},
                "category_preference": {"type": "array", "items": {"type": "string"}},
                "hard_constraints": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["type", "operator", "values"],
                                "properties": {
                                    "type": {"const": "CATEGORY"},
                                    "operator": {"enum": ["INCLUDE_ONLY", "EXCLUDE"]},
                                    "values": {"type": "array", "items": {"type": "string"}},
                                },
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["type", "operator", "value"],
                                "properties": {
                                    "type": {"const": "SHELF_LIFE"},
                                    "operator": {"const": "REQUIRE_LEVEL"},
                                    "value": {"enum": ["LONG", "MEDIUM", "SHORT"]},
                                },
                            },
                            {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["type", "operator", "values"],
                                "properties": {
                                    "type": {"const": "PRODUCT"},
                                    "operator": {"const": "EXCLUDE"},
                                    "values": {"type": "array", "items": {"type": "string"}, "minItems": 1},
                                },
                            },
                        ]
                    },
                },
                "soft_preferences": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["type", "value"],
                        "properties": {
                            "type": {"enum": ["CATEGORY", "SHELF_LIFE"]},
                            "value": {"type": "string"},
                        },
                    },
                },
                "explicit_products": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["sku", "product_name", "quantity_intent"],
                        "properties": {
                            "sku": {"type": "string"},
                            "product_name": {"type": "string"},
                            "quantity_intent": {"enum": ["LOW", "NORMAL", "HIGH"]},
                        },
                    },
                },
            },
        },
        "store_context": {"type": "object", "additionalProperties": False, "properties": {}},
        "store_considerations": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
    },
}


class IntentContractError(ValueError):
    """Raised when a schema-capable provider violates the structured intent contract."""


INTENT_SYSTEM_PROMPT = """You are a procurement consultant semantic understanding engine.

Analyze the user's procurement request and return exactly one raw JSON object. Do not wrap it in
Markdown or a code fence. Use only the fields defined below. Information not explicitly stated by
the user or present in trusted store context must be null, empty, or "unknown" as allowed by the
contract; never fill missing facts from general knowledge.

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
- structured_intent: object
- store_context: exactly {}, reserved for trusted local enrichment; never copy profile fields here
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

structured_intent:
- store_id: string, empty when not resolved from trusted master data
- budget: number or null
- objective: exactly one of "PREVENT_STOCKOUT", "SEASONAL_PREPARATION", "DISCOVER_NEW_OPPORTUNITY", "BUDGET_OPTIMIZATION", "REDUCE_WASTE", "SUPPLIER_PLANNING", or "GENERAL_PLANNING".
  These values differ from business_intent.primary_intent: stockout_prevention maps to PREVENT_STOCKOUT,
  seasonal_preparation or promotion_support to SEASONAL_PREPARATION, trial_growth to DISCOVER_NEW_OPPORTUNITY,
  waste_reduction to REDUCE_WASTE. Never uppercase primary_intent to invent an objective.
- traffic_expectation: "HIGH", "NORMAL", or "LOW"
- occasion: exactly "CHRISTMAS" or "NONE"
- category_preference: array of category names
- hard_constraints: array. Supported objects are CATEGORY with operator INCLUDE_ONLY or EXCLUDE,
  and SHELF_LIFE with operator REQUIRE_LEVEL and value LONG/MEDIUM/SHORT
- soft_preferences: array of CATEGORY or SHELF_LIFE objects with a value
- explicit_products: array of objects with sku, product_name, and quantity_intent LOW/NORMAL/HIGH

Rules:
- Missing budget is optional and must not block recommendations. Set budget_strictness to "none".
- If user says "under", "within", "do not exceed", or gives a hard budget, set budget_strictness to "strict".
- If user says "around" or "if possible" with budget, set budget_strictness to "soft".
- High traffic, busy periods, events, holidays, or promotions imply demand increase.
- Avoiding short shelf-life or fresh products implies high waste sensitivity.
- "prefer" and "focus on" are soft preferences. They must not become filters.
- Use hard constraints only for explicit wording such as "only", "must", "do not accept", or "no other categories".
- A user-requested product is strong evidence. Put it in explicit_products even when peer evidence may be low.
- Never treat a negated product mention as a purchase request. Put explicitly excluded SKUs or product names in a PRODUCT / EXCLUDE hard constraint with values; do not put them in explicit_products.
- High-risk missing information should set should_ask_follow_up=true but can_generate_recommendation must remain true.
- If the request is vague and lacks business goal, demand driver, category and budget, use this exact follow-up question: "Are you optimizing for stockout prevention, budget control, or growth?"
- Otherwise, set should_ask_follow_up to false and continue recommendations.
- A trusted store profile may be supplied in a separate system message. Use it to interpret the request. Return store_context as exactly {}; the application attaches the trusted profile locally. Only structured_intent.store_id may reference its CustomerId.

JSON output example (the field names and nesting are mandatory; values are illustrative only):
{"budget":null,"traffic_level":"NORMAL","promotion_flag":false,"shelf_life_preference":"NORMAL","preferred_category":null,"excluded_category":null,"time_range":"unknown","expected_intent":"General procurement planning.","business_intent":{"primary_intent":"general_planning","secondary_intents":[],"decision_type":"planning","urgency":"low","intent_summary":"General procurement planning."},"decision_signals":{"expected_demand_change":"unknown","demand_driver":"unknown","stockout_sensitivity":"medium","waste_sensitivity":"medium","price_sensitivity":"medium","growth_appetite":"medium","budget_strictness":"none","substitution_allowed":false},"uncertainty":{"overall_confidence":0.5,"field_sources":{"budget":"missing","traffic_level":"missing","promotion_flag":"missing","shelf_life_preference":"missing","category":"missing","time_horizon":"missing"},"low_confidence_fields":[]},"missing_information":[],"recommendation_readiness":{"can_generate_recommendation":true,"should_ask_follow_up":false,"confidence_level":"medium","confidence_score":0.5,"confidence_drivers":[],"confidence_risks":[],"follow_up_question":""},"structured_intent":{"store_id":"","budget":null,"objective":"GENERAL_PLANNING","traffic_expectation":"NORMAL","occasion":"NONE","category_preference":[],"hard_constraints":[],"soft_preferences":[],"explicit_products":[]},"store_context":{},"store_considerations":[]}
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

    @observed("intent_output", "AI / Workflow")
    def parse_intent(
        self,
        user_input: str,
        store_context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.ai_client.is_available:
            record("intent_input", "AI", status="skipped", reason="Provider not configured")
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
                    "Authoritative output JSON Schema. Follow every enum, required field, "
                    "and additionalProperties restriction exactly, including nested objects.\n"
                    + json.dumps(INTENT_JSON_SCHEMA, ensure_ascii=True)
                ),
            },
            {
                "role": "system",
                "content": (
                    "Trusted store context from the internal customer master. "
                    "Use this profile as context only. Return store_context as exactly {}; "
                    "do not echo these profile fields into that output object: "
                    f"{json.dumps(store_context or {}, ensure_ascii=True)}"
                ),
            },
            {
                "role": "user",
                "content": (
                    "Analyze the following user_request, not the illustrative JSON example. "
                    "Extract every explicitly stated fact and return the complete contracted JSON object.\n"
                    f"user_request: {json.dumps(user_input, ensure_ascii=True)}"
                ),
            },
        ]

        record("intent_input", "AI", input={"messages": messages, "schema": INTENT_JSON_SCHEMA})
        try:
            if getattr(self.ai_client, "supports_json_schema", False):
                result = self.ai_client.chat_completion_json(
                    messages,
                    json_schema=INTENT_JSON_SCHEMA,
                    schema_name="procurement_intent",
                )
            else:
                result = self.ai_client.chat_completion_json(messages)
            # Provider capabilities only control the wire format.  The local
            # business contract must be identical for every configured model.
            record("intent_output", "AI", output={"raw_json": result}, operation="before_contract_validation")
            self._validate_structured_output(result)
            return self._with_store_context(
                self._with_analysis_source(
                    self._normalize_intent(result),
                    "live",
                    getattr(self.ai_client, "provider_name", "deepseek"),
                ),
                store_context,
                result.get("store_considerations"),
            )
        except (AIClientError, IntentContractError) as exc:
            record("intent_output", "Workflow", status="fallback", error=str(exc))
            logger.warning("Intent parsing failed, using fallback: %s", exc)
            return self._with_store_context(
                self._with_analysis_source(self._fallback_parse(user_input), "fallback"),
                store_context,
            )

    @staticmethod
    def _with_analysis_source(
        intent: dict[str, Any],
        status: str,
        provider_name: str = "deepseek",
    ) -> dict[str, Any]:
        """Preserve whether understanding came from the configured model or fallback rules."""
        enriched = dict(intent)
        enriched["AIAnalysisStatus"] = status
        display_names = {"deepseek": "DeepSeek", "glm": "GLM", "gemini": "Gemini"}
        enriched["AIAnalysisSource"] = (
            display_names.get(provider_name.casefold(), provider_name)
            if status == "live"
            else "Rules fallback"
        )
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
        structured_intent = dict(enriched.get("StructuredIntent") or {})
        structured_intent["store_id"] = trusted_context["CustomerId"]
        enriched["StructuredIntent"] = structured_intent

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
        for chinese, english in {'水果': 'fruit', '蔬菜': 'vegetable', '乳制品': 'dairy', '冷冻': 'frozen', '干货': 'dry', '生鲜': 'fresh'}.items():
            lower = lower.replace(chinese, english)
        intent = self._empty_intent()

        intent["Budget"] = fallback_budget(user_input)

        if any(w in lower for w in ["traffic", "busy", "rush", "crowd"]):
            intent["TrafficLevel"] = "HIGH"

        if "stockout" in lower or "out of stock" in lower:
            intent["Objective"] = "PREVENT_STOCKOUT"

        if any(w in lower for w in ["christmas", "holiday", "festival", "promotion"]):
            intent["PromotionFlag"] = True
            intent["TimeRange"] = "holiday_window"
            intent["Occasion"] = "CHRISTMAS" if "christmas" in lower else "HOLIDAY"
            if intent["Objective"] != "PREVENT_STOCKOUT":
                intent["Objective"] = "SEASONAL_PREPARATION"
        elif "next week" in lower:
            intent["TimeRange"] = "next_week"
        elif "this week" in lower:
            intent["TimeRange"] = "this_week"

        if any(w in lower for w in ["short shelf", "perishable", "avoid fresh", "no fresh", "long shelf"]):
            intent["ShelfLifePreference"] = "LONG"

        exclude_patterns = ["avoid ", "exclude ", "no ", "不要", "不采购", "排除"]
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

        hard_constraints: list[dict[str, Any]] = []
        soft_preferences: list[dict[str, str]] = []
        for cat in ["fruit", "vegetable", "dairy", "frozen", "dry", "fresh"]:
            readable = cat.capitalize()
            if re.search(rf"\bonly\s+{re.escape(cat)}\b", lower) or (
                cat in lower and any(phrase in lower for phrase in ["no other categor", "不要其他品类", "只采购"])
            ):
                hard_constraints.append({
                    "type": "CATEGORY",
                    "operator": "INCLUDE_ONLY",
                    "values": [readable],
                })
            elif intent["PreferredCategory"] == readable:
                soft_preferences.append({"type": "CATEGORY", "value": readable})

        hard_shelf_phrases = [
            "only long shelf",
            "must be long shelf",
            "do not accept short shelf",
            "不接受短保质期",
            "只要长保质期",
            "必须长保质期",
        ]
        if any(phrase in lower for phrase in hard_shelf_phrases):
            hard_constraints.append({
                "type": "SHELF_LIFE",
                "operator": "REQUIRE_LEVEL",
                "value": "LONG",
            })
        elif intent["ShelfLifePreference"] == "LONG":
            soft_preferences.append({"type": "SHELF_LIFE", "value": "LONG"})

        explicit_products = [
            {"sku": sku.upper(), "product_name": "", "quantity_intent": "NORMAL"}
            for sku in dict.fromkeys(re.findall(r"\bP\d{3}\b", user_input, flags=re.IGNORECASE))
            if not product_is_excluded(user_input, sku)
        ]
        excluded = [sku.upper() for sku in dict.fromkeys(re.findall(r'\bP\d{3}\b', user_input, flags=re.IGNORECASE)) if product_is_excluded(user_input, sku)]
        if excluded:
            hard_constraints.append({'type': 'PRODUCT', 'operator': 'EXCLUDE', 'values': excluded})
        intent["HardConstraints"] = hard_constraints
        intent["SoftPreferences"] = soft_preferences
        intent["ExplicitProducts"] = explicit_products

        intent["ExpectedIntent"] = user_input[:100]
        return self.understanding_builder.build_from_base(intent)

    @staticmethod
    def _validate_structured_output(result: Any) -> None:
        errors = sorted(
            Draft202012Validator(INTENT_JSON_SCHEMA).iter_errors(result),
            key=lambda item: list(item.path),
        )
        if errors:
            error = errors[0]
            path = ".".join(str(item) for item in error.path) or "root"
            raise IntentContractError(
                f"Intent schema violation at {path}: {error.message}"
            )

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
            "Occasion": "NONE",
            "Objective": None,
            "HardConstraints": [],
            "SoftPreferences": [],
            "ExplicitProducts": [],
        }
