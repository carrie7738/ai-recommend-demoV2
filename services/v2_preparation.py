from __future__ import annotations

from typing import Any

import pandas as pd

from services.candidate_pool import CandidatePoolBuilder
from services.decision_features import DecisionFeatureBuilder
from services.intent_parser import IntentParser
from services.event_normalization import EventNormalizer


class V2PreparationPipeline:
    """Run the deterministic V2 preparation stages before the AI decision layer."""

    def __init__(
        self,
        intent_parser: IntentParser | None = None,
        candidate_pool_builder: CandidatePoolBuilder | None = None,
        decision_feature_builder: DecisionFeatureBuilder | None = None,
    ) -> None:
        self.intent_parser = intent_parser or IntentParser()
        self.candidate_pool_builder = candidate_pool_builder or CandidatePoolBuilder()
        self.decision_feature_builder = decision_feature_builder or DecisionFeatureBuilder()

    def prepare(
        self,
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        user_input: str,
        as_of_date: Any,
        parsed_intent: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        store_context = self._store_context(workbook["Customer"], customer_id)
        intent = (
            dict(parsed_intent)
            if parsed_intent is not None
            else self.intent_parser.parse_intent(user_input, store_context=store_context)
        )
        structured_intent = dict(intent.get("StructuredIntent") or {})
        structured_intent["explicit_products"] = self._resolve_catalog_mentions(
            user_input,
            workbook["Product"],
            structured_intent.get("explicit_products", []),
        )
        intent["StructuredIntent"] = structured_intent
        event_context = EventNormalizer.normalize(
            workbook,
            structured_intent.get("occasion", "NONE"),
            as_of_date,
        )
        effective_as_of_date = (
            event_context["event_window_start"] if event_context else as_of_date
        )

        pool = self.candidate_pool_builder.build(
            workbook,
            customer_id,
            structured_intent,
            effective_as_of_date,
        )
        decision_features = self.decision_feature_builder.build(
            workbook,
            customer_id,
            structured_intent,
            pool.eligible_candidates,
            effective_as_of_date,
        )
        return {
            "intent": intent,
            "event_context": event_context,
            "effective_as_of_date": pd.Timestamp(effective_as_of_date).normalize(),
            "candidate_pool": {
                "eligible_candidates": pool.eligible_candidates,
                "rejected_candidates": pool.rejected_candidates,
            },
            "safe_decision_context": {
                "structured_intent": structured_intent,
                "candidates": decision_features,
            },
        }

    @staticmethod
    def _store_context(customers: pd.DataFrame, customer_id: str) -> dict[str, str]:
        rows = customers.loc[customers["CustomerId"].astype(str) == str(customer_id)]
        if rows.empty:
            raise ValueError(f"Unknown customer: {customer_id}")
        row = rows.iloc[0]
        return {
            key: str(row.get(key) or "")
            for key in ("CustomerId", "StoreName", "Industry", "Region", "StoreLevel", "CustomerStage")
        }

    @staticmethod
    def _resolve_catalog_mentions(
        user_input: str,
        products: pd.DataFrame,
        existing: Any,
    ) -> list[dict[str, str]]:
        resolved = [dict(item) for item in existing if isinstance(item, dict)] if isinstance(existing, list) else []
        known_ids = {str(item.get("sku") or "").upper() for item in resolved}
        request = user_input.casefold()
        for _, product in products.iterrows():
            product_id = str(product.get("ProductId") or "").strip().upper()
            product_name = str(product.get("ProductName") or "").strip()
            if not product_id or not product_name or product_id in known_ids:
                continue
            if product_name.casefold() in request:
                resolved.append({
                    "sku": product_id,
                    "product_name": product_name,
                    "quantity_intent": "NORMAL",
                })
                known_ids.add(product_id)
        return resolved
