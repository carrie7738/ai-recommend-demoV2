from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from services.intent_parser import IntentParser

logger = logging.getLogger(__name__)


class ContextEngine:
    """Builds structured session context from the workbook."""

    def __init__(self, intent_parser: IntentParser | None = None) -> None:
        self.intent_parser = intent_parser or IntentParser()

    def build_context(self, workbook: dict[str, pd.DataFrame], session_id: str) -> dict[str, Any]:
        context_df = workbook.get("ConversationContext")
        if context_df is None or context_df.empty:
            raise ValueError("ConversationContext data is required.")

        row = context_df.loc[context_df["SessionId"] == session_id]
        if row.empty:
            raise ValueError(f"Session '{session_id}' was not found.")

        record = row.iloc[0].to_dict()
        record["PromotionFlag"] = self._as_bool(record.get("PromotionFlag"))
        record["Budget"] = self._as_float(record.get("Budget"))
        record["TrafficLevel"] = self._as_text(record.get("TrafficLevel"))
        record["PreferredCategory"] = self._as_text(record.get("PreferredCategory"))
        record["ExcludedCategory"] = self._as_text(record.get("ExcludedCategory"))
        record["ShelfLifePreference"] = self._as_text(record.get("ShelfLifePreference"))
        record["TimeRange"] = self._as_text(record.get("TimeRange"))
        return record

    def list_sessions(self, workbook: dict[str, pd.DataFrame], customer_id: str | None = None) -> list[dict[str, Any]]:
        context_df = workbook.get("ConversationContext")
        if context_df is None or context_df.empty:
            return []

        if customer_id:
            context_df = context_df.loc[context_df["CustomerId"] == customer_id]
        return context_df.fillna("").to_dict(orient="records")

    def suggest_session(
        self,
        workbook: dict[str, pd.DataFrame],
        user_input: str,
        parsed_intent: dict[str, Any] | None = None,
    ) -> str:
        """Pick the best-matching session from ConversationContext.

        Kept even though the current demo has a single session (S1):
        the matching logic supports multi-session workbooks for future demos
        and is covered by test_context_engine_reuses_parsed_intent_for_session_matching.
        """
        sessions = self.list_sessions(workbook)
        if not sessions:
            raise ValueError("ConversationContext data is required.")

        if not user_input or not user_input.strip():
            return sessions[0]["SessionId"]

        if parsed_intent is None:
            parsed_intent = self.intent_parser.parse_intent(user_input)
        logger.info("Parsed intent for session matching: %s", parsed_intent)

        best_session_id = sessions[0]["SessionId"]
        best_score = -1.0

        for session in sessions:
            score = self._intent_match_score(parsed_intent, session)
            if score > best_score:
                best_score = score
                best_session_id = session["SessionId"]

        return best_session_id

    def _intent_match_score(self, intent: dict[str, Any], session: dict[str, Any]) -> float:
        score = 0.0

        if intent.get("Budget") and session.get("Budget"):
            try:
                budget_diff = abs(float(intent["Budget"]) - float(session["Budget"]))
                budget_score = max(0, 10 - budget_diff / 100)
                score += budget_score * 3
            except (ValueError, TypeError):
                pass

        if intent.get("TrafficLevel") and session.get("TrafficLevel"):
            if str(intent["TrafficLevel"]).upper() == str(session["TrafficLevel"]).upper():
                score += 10

        if intent.get("PromotionFlag") is not None and session.get("PromotionFlag") is not None:
            if self._as_bool(intent["PromotionFlag"]) == self._as_bool(session["PromotionFlag"]):
                score += 8

        if intent.get("ShelfLifePreference") and session.get("ShelfLifePreference"):
            if str(intent["ShelfLifePreference"]).upper() == str(session["ShelfLifePreference"]).upper():
                score += 8

        if intent.get("TimeRange") and session.get("TimeRange"):
            if str(intent["TimeRange"]).lower() == str(session["TimeRange"]).lower():
                score += 10

        if intent.get("PreferredCategory") and session.get("PreferredCategory"):
            if str(intent["PreferredCategory"]).lower() == str(session["PreferredCategory"]).lower():
                score += 6

        if intent.get("ExcludedCategory") and session.get("ExcludedCategory"):
            if str(intent["ExcludedCategory"]).lower() == str(session["ExcludedCategory"]).lower():
                score += 6

        if intent.get("ExpectedIntent") and session.get("ExpectedIntent"):
            intent_words = set(str(intent["ExpectedIntent"]).lower().split())
            session_words = set(str(session["ExpectedIntent"]).lower().split())
            overlap = len(intent_words & session_words)
            score += overlap * 2

        return score

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if pd.isna(value):
            return False
        return str(value).strip().lower() in {"true", "1", "yes", "y"}

    @staticmethod
    def _as_float(value: Any) -> float | None:
        if pd.isna(value):
            return None
        return float(value)

    @staticmethod
    def _as_text(value: Any) -> str | None:
        if pd.isna(value):
            return None
        return str(value).strip()
