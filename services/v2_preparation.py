from __future__ import annotations

from typing import Any
import re

import pandas as pd

from services.candidate_pool import CandidatePoolBuilder
from services.decision_features import DecisionFeatureBuilder
from services.intent_parser import IntentParser
from services.event_normalization import EventNormalizer
from services.request_constraints import catalog_exclusions
from services.runtime_trace import is_capturing, observed, record


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

    @observed("prepare", "Workflow")
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
        excluded = catalog_exclusions(user_input, workbook['Product'])
        if excluded:
            structured_intent['hard_constraints'] = [
                *structured_intent.get('hard_constraints', []),
                {'type': 'PRODUCT', 'operator': 'EXCLUDE', 'values': excluded},
            ]
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

        if is_capturing():
            occasion = str(structured_intent.get("occasion") or "NONE").upper()
            event_source: dict[str, Any] = {
                "sheet": "EventConfig",
                "lookup": {
                    "occasion": occasion,
                    "reference_date": str(as_of_date),
                },
                "matched": event_context is not None,
                "record": event_context,
            }
            if event_context is None:
                event_source["evidence_status"] = (
                    "not_applicable" if occasion in {"", "NONE"} else "missing"
                )
            record(
                "business_context",
                "Workflow",
                input={
                    "customer_id": str(customer_id),
                    "requested_as_of_date": as_of_date,
                    "occasion": occasion,
                },
                output={
                    "store": store_context,
                    "event": event_context,
                    "effective_as_of_date": effective_as_of_date,
                },
                sources={
                    "store": {
                        "sheet": "Customer",
                        "lookup": {"CustomerId": str(customer_id)},
                        "record": store_context,
                    },
                    "event": event_source,
                },
            )

        pool = self.candidate_pool_builder.build(
            workbook,
            customer_id,
            structured_intent,
            effective_as_of_date,
        )
        if is_capturing():
            candidate_ids = sorted({
                str(item.get("candidate_id") or "")
                for item in [*pool.eligible_candidates, *pool.rejected_candidates]
                if item.get("candidate_id")
            })
            product_records = self._trace_rows(
                workbook["Product"],
                "ProductId",
                candidate_ids,
                ("ProductId", "ProductName", "Category", "ProductType", "IsSellable", "SalesUnit"),
            )
            supply_records = self._trace_supply_rows(
                workbook["SupplyAvailability"],
                candidate_ids,
                effective_as_of_date,
            )
            record(
                "candidate_pool",
                "Workflow",
                input={
                    "customer_id": str(customer_id),
                    "as_of_date": effective_as_of_date,
                    "filters": {
                        "industry": store_context.get("Industry"),
                        "hard_constraints": structured_intent.get("hard_constraints", []),
                        "explicit_products": structured_intent.get("explicit_products", []),
                    },
                },
                output={
                    "eligible_candidates": pool.eligible_candidates,
                    "rejected_candidates": pool.rejected_candidates,
                    "eligible_count": len(pool.eligible_candidates),
                    "rejected_count": len(pool.rejected_candidates),
                },
                sources={
                    "Customer": {
                        "sheet": "Customer",
                        "lookup": {"CustomerId": str(customer_id)},
                        "record": store_context,
                    },
                    "Product": {
                        "sheet": "Product",
                        "lookup": {"ProductId": candidate_ids},
                        "records": product_records,
                        "evidence_status": "available" if product_records else "missing",
                    },
                    "SupplyAvailability": {
                        "sheet": "SupplyAvailability",
                        "lookup": {"ProductId": candidate_ids},
                        "as_of_date": effective_as_of_date,
                        "records": supply_records,
                        "scope": "latest row per ProductId at or before as_of_date",
                        "evidence_status": "available" if supply_records else "missing",
                    },
                    "OrderHistory": {
                        "sheet": "OrderHistory",
                        "evidence_status": "not_collected",
                        "records": [],
                        "store_history": {
                            "filter": {
                                "CustomerId": str(customer_id),
                                "OrderDate_lte": effective_as_of_date,
                            },
                            "purpose": "historical purchase candidates",
                        },
                        "peer_history": {
                            "filter": {
                                "Industry": store_context.get("Industry"),
                                "CustomerId_excluding": str(customer_id),
                                "OrderDate_lte": effective_as_of_date,
                            },
                            "purpose": "peer purchase ratio for discovery candidates",
                        },
                    },
                },
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
        excluded = set(catalog_exclusions(user_input, products))
        excluded_names = {str(row.get('ProductName') or '').strip().casefold() for _, row in products.iterrows() if str(row['ProductId']).upper() in excluded}
        resolved = [dict(item) for item in existing if isinstance(item, dict)
                    and str(item.get('sku') or '').upper() not in excluded
                    and str(item.get('product_name') or '').strip().casefold() not in excluded_names] if isinstance(existing, list) else []
        known_ids = {str(item.get("sku") or "").upper() for item in resolved}
        request = user_input.casefold()
        for _, product in products.iterrows():
            product_id = str(product.get("ProductId") or "").strip().upper()
            product_name = str(product.get("ProductName") or "").strip()
            if not product_id or not product_name or product_id in known_ids or product_id in excluded:
                continue
            if re.search(r'(?<![a-z0-9])' + re.escape(product_name.casefold()) + r'(?![a-z0-9])', request):
                resolved.append({
                    "sku": product_id,
                    "product_name": product_name,
                    "quantity_intent": "NORMAL",
                })
                known_ids.add(product_id)
        return resolved

    @staticmethod
    def _trace_rows(
        frame: pd.DataFrame,
        key: str,
        values: list[str],
        columns: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        if frame.empty or not values:
            return []
        selected_columns = [column for column in columns if column in frame.columns]
        if key not in frame.columns or not selected_columns:
            return []
        rows = frame.loc[frame[key].astype(str).isin(values), selected_columns]
        records: list[dict[str, Any]] = []
        for _, row in rows.iterrows():
            item: dict[str, Any] = {}
            for column in selected_columns:
                value = row.get(column)
                if pd.isna(value):
                    item[column] = None
                elif isinstance(value, pd.Timestamp):
                    item[column] = value.isoformat()
                elif hasattr(value, "item"):
                    try:
                        item[column] = value.item()
                    except (AttributeError, ValueError):
                        item[column] = value
                else:
                    item[column] = value
            records.append(item)
        return records

    @staticmethod
    def _trace_supply_rows(
        frame: pd.DataFrame,
        values: list[str],
        as_of_date: Any,
    ) -> list[dict[str, Any]]:
        prepared = frame.copy()
        if "LastUpdated" in prepared.columns:
            prepared["LastUpdated"] = pd.to_datetime(
                prepared["LastUpdated"], errors="coerce"
            )
            as_of = pd.to_datetime(as_of_date, errors="coerce")
            if pd.notna(as_of):
                prepared = prepared.loc[
                    prepared["LastUpdated"].notna()
                    & (prepared["LastUpdated"] <= as_of)
                ].sort_values("LastUpdated")
        if "ProductId" in prepared.columns:
            prepared = prepared.drop_duplicates(subset=["ProductId"], keep="last")
        return V2PreparationPipeline._trace_rows(
            prepared,
            "ProductId",
            values,
            ("ProductId", "AvailableStock", "LastUpdated"),
        )
