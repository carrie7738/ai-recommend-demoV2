from __future__ import annotations

from services.runtime_trace import observed, record

import json
from typing import Any

from jsonschema import Draft202012Validator

from services.ai_client import AIClient, AIClientError


PRIORITIES = ["HIGH", "MEDIUM", "LOW"]
RECOMMENDATION_TYPES = ["REPLENISHMENT", "DISCOVERY"]

AI_DECISION_JSON_SCHEMA: dict[str, Any] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "additionalProperties": False,
    "required": ["procurement_strategy", "candidate_decisions"],
    "properties": {
        "procurement_strategy": {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "primary_objective",
                "primary_signals",
                "secondary_signals",
                "strategy_summary",
            ],
            "properties": {
                "primary_objective": {"type": "string", "minLength": 1, "maxLength": 100},
                "primary_signals": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "uniqueItems": True,
                },
                "secondary_signals": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1},
                    "uniqueItems": True,
                },
                "strategy_summary": {"type": "string", "minLength": 1, "maxLength": 600},
            },
        },
        "candidate_decisions": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "candidate_id",
                    "recommended",
                    "recommendation_type",
                    "priority",
                    "replenishment_intensity",
                    "decision_signals",
                ],
                "properties": {
                    "candidate_id": {"type": "string", "minLength": 1},
                    "recommended": {"type": "boolean"},
                    "recommendation_type": {"enum": RECOMMENDATION_TYPES},
                    "priority": {"enum": PRIORITIES},
                    "replenishment_intensity": {"enum": PRIORITIES},
                    "decision_signals": {
                        "type": "array",
                        "items": {"type": "string", "minLength": 1},
                        "uniqueItems": True,
                    },
                },
            },
        },
    },
}


AI_DECISION_SYSTEM_PROMPT = """You are the AI Decision Layer for a procurement recommendation demo.

You receive only precomputed, non-sensitive decision features. Return one JSON object that follows
the supplied JSON Schema exactly. Do not calculate order quantities, prices, costs, budgets,
inventory values, or supplier availability. Do not add candidates.

Decision rules:
- Return exactly one candidate_decision for every input candidate_id.
- Copy each candidate's recommendation_type exactly.
- decision_signals must be copied exactly from that candidate's allowed decision signals.
- primary_signals and secondary_signals must be copied exactly from allowed_strategy_signals.
- Treat USER_REQUESTED as strong discovery evidence; peer evidence is not required.
- Preferences influence priority but are not hard exclusions.
- Hard constraints and candidate eligibility were already handled upstream; do not reinterpret them.
- replenishment_intensity is qualitative only: HIGH, MEDIUM, or LOW. It is never a quantity.
- Return raw JSON only, with no markdown, code fence, or commentary. Use no fields outside the
  supplied JSON Schema. Do not infer facts that are absent from the supplied structured context.

JSON output shape example (replace placeholders with supplied IDs and allowed signals only):
{"procurement_strategy":{"primary_objective":"GENERAL_PLANNING","primary_signals":[],"secondary_signals":[],"strategy_summary":"Use verified procurement signals."},"candidate_decisions":[{"candidate_id":"P000","recommended":true,"recommendation_type":"REPLENISHMENT","priority":"MEDIUM","replenishment_intensity":"MEDIUM","decision_signals":[]}]}
"""

AI_DECISION_RETRY_PROMPT = """A local hard validator rejected the previous candidate combination.
Use only the structured constraint feedback to reconsider candidate retention and priority. The
feedback intentionally contains no prices, quantities, budget difference, or constraint severity.
Return the complete decision object again for every candidate and follow the original contract.
"""


class AIDecisionError(ValueError):
    """Raised when AI decision input or output violates the Task 4 contract."""


class AIDecisionLayer:
    FORBIDDEN_CONTEXT_KEYS = {
        "unitprice",
        "unit_price",
        "avgcost",
        "avg_cost",
        "price",
        "cost",
        "currentstock",
        "current_stock",
        "availablestock",
        "available_stock",
        "quantity",
        "qty",
        "recommended_qty",
        "estimated_cost",
    }

    def __init__(self, ai_client: AIClient | None = None) -> None:
        self.ai_client = ai_client or AIClient()
        self._schema_validator = Draft202012Validator(AI_DECISION_JSON_SCHEMA)

    def decide(self, safe_decision_context: dict[str, Any]) -> dict[str, Any]:
        candidates = self._validate_input(safe_decision_context)
        if not self.ai_client.is_available:
            raise AIDecisionError("AI decision provider is not configured.")

        allowed_strategy_signals = self._allowed_strategy_signals(safe_decision_context)
        model_input = {
            "structured_intent": safe_decision_context["structured_intent"],
            "candidates": candidates,
            "allowed_strategy_signals": allowed_strategy_signals,
            "output_schema": AI_DECISION_JSON_SCHEMA,
        }
        messages = [
            {"role": "system", "content": AI_DECISION_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(model_input, ensure_ascii=True)},
        ]
        return self._request_and_validate(
            messages,
            candidates,
            allowed_strategy_signals,
        )

    def retry_decision(
        self,
        safe_decision_context: dict[str, Any],
        previous_decision: dict[str, Any],
        constraint_feedback: dict[str, Any],
    ) -> dict[str, Any]:
        candidates = self._validate_input(safe_decision_context)
        if not self.ai_client.is_available:
            raise AIDecisionError("AI decision provider is not configured.")
        allowed_strategy_signals = self._allowed_strategy_signals(safe_decision_context)
        self._validate_schema(previous_decision)
        self._validate_semantics(previous_decision, candidates, allowed_strategy_signals)
        self._validate_retry_feedback(constraint_feedback, candidates)
        model_input = {
            "structured_intent": safe_decision_context["structured_intent"],
            "candidates": candidates,
            "allowed_strategy_signals": allowed_strategy_signals,
            "previous_decision": previous_decision,
            "constraint_feedback": constraint_feedback,
            "output_schema": AI_DECISION_JSON_SCHEMA,
        }
        messages = [
            {"role": "system", "content": AI_DECISION_SYSTEM_PROMPT},
            {"role": "system", "content": AI_DECISION_RETRY_PROMPT},
            {"role": "user", "content": json.dumps(model_input, ensure_ascii=True)},
        ]
        return self._request_and_validate(messages, candidates, allowed_strategy_signals)

    @observed("decision_output", "AI")
    def _request_and_validate(
        self,
        messages: list[dict[str, str]],
        candidates: list[dict[str, Any]],
        allowed_strategy_signals: list[str],
    ) -> dict[str, Any]:
        record("decision_input", "AI", input={"messages": messages, "schema": AI_DECISION_JSON_SCHEMA}, input_contract="PASS")
        try:
            if getattr(self.ai_client, "supports_json_schema", False):
                result = self.ai_client.chat_completion_json(
                    messages,
                    json_schema=AI_DECISION_JSON_SCHEMA,
                    schema_name="procurement_decision",
                )
            else:
                result = self.ai_client.chat_completion_json(messages)
        except AIClientError as exc:
            raise AIDecisionError(f"AI decision request failed: {exc}") from exc

        record("decision_output", "AI", output={"raw_json": result}, operation="before_contract_validation")
        self._validate_schema(result)
        self._validate_semantics(result, candidates, allowed_strategy_signals)
        return result

    @classmethod
    def _validate_retry_feedback(
        cls,
        feedback: Any,
        candidates: list[dict[str, Any]],
    ) -> None:
        required = {"type", "affected_candidates", "reason", "required_action"}
        if not isinstance(feedback, dict) or set(feedback) != required:
            raise AIDecisionError("Retry feedback does not match the approved contract.")
        if feedback["type"] != "BUDGET_CONFLICT":
            raise AIDecisionError("Only BUDGET_CONFLICT retry is supported in V2.")
        affected = feedback["affected_candidates"]
        known_ids = {item["candidate_id"] for item in candidates}
        if (
            not isinstance(affected, list)
            or not affected
            or not all(isinstance(item, str) for item in affected)
            or not set(affected).issubset(known_ids)
        ):
            raise AIDecisionError("Retry feedback contains invalid affected candidates.")
        if not all(
            isinstance(feedback[field], str) and feedback[field].strip()
            for field in ("reason", "required_action")
        ):
            raise AIDecisionError("Retry feedback reason and action must be non-empty strings.")
        cls._reject_forbidden_keys(feedback)

    @observed("decision_input", "Workflow input contract")
    def _validate_input(self, context: Any) -> list[dict[str, Any]]:
        if not isinstance(context, dict):
            raise AIDecisionError("safe_decision_context must be an object.")
        self._reject_forbidden_keys(context)
        if not isinstance(context.get("structured_intent"), dict):
            raise AIDecisionError("structured_intent must be an object.")
        candidates = context.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise AIDecisionError("At least one eligible candidate is required.")

        ids: list[str] = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise AIDecisionError("Each candidate must be an object.")
            candidate_id = candidate.get("candidate_id")
            recommendation_type = candidate.get("recommendation_type")
            signals = candidate.get("signals")
            if not isinstance(candidate_id, str) or not candidate_id:
                raise AIDecisionError("Each candidate requires a candidate_id.")
            if recommendation_type not in RECOMMENDATION_TYPES:
                raise AIDecisionError(f"Invalid recommendation_type for {candidate_id}.")
            if not isinstance(signals, list) or not all(isinstance(item, str) for item in signals):
                raise AIDecisionError(f"Candidate {candidate_id} requires string signals.")
            ids.append(candidate_id)
        if len(ids) != len(set(ids)):
            raise AIDecisionError("Candidate IDs must be unique.")
        return candidates

    def _validate_schema(self, result: Any) -> None:
        errors = sorted(self._schema_validator.iter_errors(result), key=lambda item: list(item.path))
        if errors:
            error = errors[0]
            path = ".".join(str(item) for item in error.path) or "root"
            raise AIDecisionError(f"AI decision schema violation at {path}: {error.message}")

    @staticmethod
    def _validate_semantics(
        result: dict[str, Any],
        candidates: list[dict[str, Any]],
        allowed_strategy_signals: list[str],
    ) -> None:
        candidate_by_id = {item["candidate_id"]: item for item in candidates}
        decisions = result["candidate_decisions"]
        decision_ids = [item["candidate_id"] for item in decisions]
        expected_ids = set(candidate_by_id)
        if len(decision_ids) != len(set(decision_ids)):
            raise AIDecisionError("AI decision contains duplicate candidate IDs.")
        if set(decision_ids) != expected_ids:
            missing = sorted(expected_ids - set(decision_ids))
            unknown = sorted(set(decision_ids) - expected_ids)
            raise AIDecisionError(
                f"AI decision candidate mismatch; missing={missing}, unknown={unknown}."
            )

        for decision in decisions:
            source = candidate_by_id[decision["candidate_id"]]
            if decision["recommendation_type"] != source["recommendation_type"]:
                raise AIDecisionError(
                    f"AI changed recommendation_type for {decision['candidate_id']}."
                )
            invalid_signals = set(decision["decision_signals"]) - set(source["signals"])
            if invalid_signals:
                raise AIDecisionError(
                    f"AI invented decision signals for {decision['candidate_id']}: "
                    f"{sorted(invalid_signals)}."
                )

        strategy = result["procurement_strategy"]
        strategy_signals = strategy["primary_signals"] + strategy["secondary_signals"]
        invalid_strategy_signals = set(strategy_signals) - set(allowed_strategy_signals)
        if invalid_strategy_signals:
            raise AIDecisionError(
                f"AI invented strategy signals: {sorted(invalid_strategy_signals)}."
            )

    @classmethod
    def _reject_forbidden_keys(cls, value: Any, path: str = "root") -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).casefold()
                if normalized in cls.FORBIDDEN_CONTEXT_KEYS:
                    raise AIDecisionError(f"Forbidden raw field in AI context: {path}.{key}")
                cls._reject_forbidden_keys(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                cls._reject_forbidden_keys(child, f"{path}[{index}]")

    @staticmethod
    def _allowed_strategy_signals(context: dict[str, Any]) -> list[str]:
        allowed = {
            signal
            for candidate in context["candidates"]
            for signal in candidate["signals"]
        }
        intent = context["structured_intent"]
        allowed.add(f"OBJECTIVE={str(intent.get('objective') or 'GENERAL_PLANNING').upper()}")
        allowed.add(
            f"TRAFFIC_EXPECTATION={str(intent.get('traffic_expectation') or 'NORMAL').upper()}"
        )
        allowed.add(f"OCCASION={str(intent.get('occasion') or 'NONE').upper()}")
        allowed.add(
            "BUDGET_CONSTRAINT=PRESENT"
            if intent.get("budget") is not None
            else "BUDGET_CONSTRAINT=NONE"
        )
        return sorted(allowed)
