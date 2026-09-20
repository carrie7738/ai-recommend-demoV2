from __future__ import annotations

from typing import Any

import pandas as pd

from services.v2_policy import V2FeaturePolicy
from services.runtime_trace import is_capturing, observed, record


class DecisionFeatureError(ValueError):
    """Raised when safe decision features cannot be derived deterministically."""


class DecisionFeatureBuilder:
    REQUIRED_SHEETS = {
        "Customer",
        "OrderHistory",
        "Inventory",
        "IndustryTrend",
        "EventConfig",
        "V2FeaturePolicy",
    }

    @observed("features", "Feature Builder")
    def build(
        self,
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        structured_intent: dict[str, Any],
        candidates: list[dict[str, Any]],
        as_of_date: Any,
    ) -> list[dict[str, Any]]:
        self._validate_workbook(workbook)
        policy = V2FeaturePolicy.from_workbook(workbook)
        as_of = self._as_timestamp(as_of_date)

        orders = workbook["OrderHistory"].copy()
        inventory = workbook["Inventory"].copy()
        trends = workbook["IndustryTrend"].copy()
        orders["OrderDate"] = pd.to_datetime(orders["OrderDate"], errors="coerce")
        inventory["LastUpdated"] = pd.to_datetime(inventory["LastUpdated"], errors="coerce")
        if "AsOfDate" in trends.columns:
            trends["AsOfDate"] = pd.to_datetime(trends["AsOfDate"], errors="coerce")
        orders = orders.loc[orders["OrderDate"].notna() & (orders["OrderDate"] <= as_of)].copy()

        customer_industry = self._customer_industry(workbook["Customer"], customer_id)
        preference_category = self._preferred_category(structured_intent)
        occasion = str(structured_intent.get("occasion") or "NONE").upper()
        capturing = is_capturing()
        policy_thresholds = self._policy_thresholds(policy) if capturing else None
        feature_rows: list[dict[str, Any]] = []

        for candidate in candidates:
            if not candidate.get("eligible", True):
                continue
            product_id = str(candidate.get("candidate_id") or "")
            evidence: dict[str, Any] | None = {} if capturing else None
            if evidence is not None:
                evidence["candidate"] = {
                    "candidate_id": product_id,
                    "recommendation_type": candidate.get("recommendation_type"),
                    "candidate_source": candidate.get("candidate_source"),
                    "category": candidate.get("category"),
                    "shelf_life_level": candidate.get("shelf_life_level"),
                    "peer_purchase_ratio": candidate.get("peer_purchase_ratio"),
                    "quantity_intent": candidate.get("quantity_intent"),
                }
            purchase_frequency = self._purchase_frequency(
                orders,
                customer_id,
                product_id,
                as_of,
                policy,
                evidence=evidence,
            )
            stockout_risk = self._stockout_risk(
                orders,
                inventory,
                customer_id,
                product_id,
                as_of,
                policy,
                evidence=evidence,
            )
            trend = self._demand_trend(
                trends,
                customer_industry,
                product_id,
                as_of,
                evidence=evidence,
            )
            category_relevance = self._category_relevance(
                str(candidate.get("category") or ""),
                preference_category,
            )
            peer_ratio_pct = round(float(candidate.get("peer_purchase_ratio") or 0.0) * 100)
            baseline_source = self._event_baseline_source(
                workbook,
                orders,
                customer_id,
                customer_industry,
                product_id,
                occasion,
                as_of,
                policy,
                evidence=evidence,
            )

            features = {
                "purchase_frequency": purchase_frequency,
                "stockout_risk": stockout_risk,
                "product_demand_trend": trend,
                "shelf_life_level": str(candidate.get("shelf_life_level") or "UNKNOWN"),
                "peer_purchase_ratio": f"{peer_ratio_pct}%",
                "peer_popularity": (
                    "HIGH" if peer_ratio_pct / 100 >= policy.discovery_peer_ratio_threshold else "LOW"
                ),
                "category_relevance": category_relevance,
                "occasion": occasion,
                "baseline_source": baseline_source,
                "quantity_intent": str(candidate.get("quantity_intent") or "NORMAL").upper(),
            }
            signals = self._signals(candidate, features)
            if evidence is not None:
                evidence["category_relevance"] = {
                    "candidate_category": str(candidate.get("category") or ""),
                    "preferred_category": preference_category,
                    "output": category_relevance,
                }
                evidence["shelf_life_level"] = {
                    "candidate_value": candidate.get("shelf_life_level"),
                    "output": features["shelf_life_level"],
                }
                evidence["peer_purchase_ratio"] = {
                    "source": "CandidatePoolBuilder",
                    "raw_ratio": candidate.get("peer_purchase_ratio"),
                    "rounded_percentage": peer_ratio_pct,
                    "threshold": policy.discovery_peer_ratio_threshold,
                    "output": {
                        "peer_purchase_ratio": features["peer_purchase_ratio"],
                        "peer_popularity": features["peer_popularity"],
                    },
                }
                evidence["quantity_intent"] = {
                    "source": "CandidatePoolBuilder",
                    "raw_value": candidate.get("quantity_intent"),
                    "output": features["quantity_intent"],
                }
                record(
                    "features",
                    "Feature Builder",
                    input={
                        "candidate_id": product_id,
                        "customer_id": str(customer_id),
                        "as_of_date": as_of,
                        "raw_evidence": evidence,
                        "policy_thresholds": policy_thresholds,
                    },
                    output={
                        "candidate_id": product_id,
                        "features": features,
                        "signals": signals,
                        "raw_evidence": evidence,
                        "policy_thresholds": policy_thresholds,
                    },
                    sources={
                        "OrderHistory": "purchase frequency, stockout demand, event baseline",
                        "Inventory": "latest store stock for stockout coverage",
                        "IndustryTrend": "latest industry/product trend as of date",
                        "EventConfig": "comparable event lookup for baseline source",
                        "V2FeaturePolicy": "loaded thresholds used by this calculation",
                    },
                )
            feature_rows.append({
                "candidate_id": product_id,
                "recommendation_type": candidate.get("recommendation_type"),
                "candidate_source": candidate.get("candidate_source"),
                "features": features,
                "signals": signals,
            })

        feature_rows.sort(key=lambda item: item["candidate_id"])
        return feature_rows

    @staticmethod
    def _purchase_frequency(
        orders: pd.DataFrame,
        customer_id: str,
        product_id: str,
        as_of: pd.Timestamp,
        policy: V2FeaturePolicy,
        evidence: dict[str, Any] | None = None,
    ) -> str:
        cutoff = as_of - pd.Timedelta(days=policy.purchase_frequency_window_days)
        matching_orders = orders.loc[
            (orders["CustomerId"].astype(str) == str(customer_id))
            & (orders["ProductId"].astype(str) == product_id)
            & (orders["OrderDate"] >= cutoff)
        ]
        count = len(matching_orders)
        if evidence is not None:
            evidence["purchase_frequency"] = {
                "source": "OrderHistory",
                "filter": {
                    "CustomerId": str(customer_id),
                    "ProductId": product_id,
                    "OrderDate_gte": cutoff,
                    "OrderDate_lte": as_of,
                },
                "order_count": int(count),
                "records": DecisionFeatureBuilder._trace_records(
                    matching_orders,
                    ("OrderId", "OrderDate", "Quantity", "EventId"),
                ),
                "thresholds": {
                    "high": policy.purchase_frequency_high_threshold,
                    "low": policy.purchase_frequency_low_threshold,
                },
            }
        if count >= policy.purchase_frequency_high_threshold:
            result = "HIGH"
        elif count <= policy.purchase_frequency_low_threshold:
            result = "LOW"
        else:
            result = "MEDIUM"
        if evidence is not None:
            evidence["purchase_frequency"]["output"] = result
        return result

    @staticmethod
    def _stockout_risk(
        orders: pd.DataFrame,
        inventory: pd.DataFrame,
        customer_id: str,
        product_id: str,
        as_of: pd.Timestamp,
        policy: V2FeaturePolicy,
        evidence: dict[str, Any] | None = None,
    ) -> str:
        cutoff = as_of - pd.Timedelta(days=policy.purchase_frequency_window_days)
        recent_orders = orders.loc[
            (orders["CustomerId"].astype(str) == str(customer_id))
            & (orders["ProductId"].astype(str) == product_id)
            & (orders["OrderDate"] >= cutoff)
        ]
        demand = pd.to_numeric(recent_orders.get("Quantity"), errors="coerce").fillna(0).sum()
        average_daily_demand = float(demand) / policy.purchase_frequency_window_days
        stockout_evidence: dict[str, Any] | None = None
        if evidence is not None:
            stockout_evidence = evidence["stockout_risk"] = {
                "sources": ["OrderHistory", "Inventory"],
                "order_filter": {
                    "CustomerId": str(customer_id),
                    "ProductId": product_id,
                    "OrderDate_gte": cutoff,
                    "OrderDate_lte": as_of,
                },
                "recent_order_count": int(len(recent_orders)),
                "recent_order_quantity_total": float(demand),
                "average_daily_demand": average_daily_demand,
                "order_records": DecisionFeatureBuilder._trace_records(
                    recent_orders,
                    ("OrderId", "OrderDate", "Quantity", "EventId"),
                ),
                "inventory_filter": {
                    "CustomerId": str(customer_id),
                    "ProductId": product_id,
                    "LastUpdated_lte": as_of,
                },
                "thresholds": {
                    "high_risk_coverage_days": policy.stockout_high_risk_coverage_days,
                    "low_risk_coverage_days": policy.stockout_low_risk_coverage_days,
                },
            }
        if average_daily_demand <= 0:
            if stockout_evidence is not None:
                stockout_evidence.update({
                    "inventory_records": [],
                    "evidence_status": "missing",
                    "missing_reason": "NO_RECENT_DEMAND",
                    "output": "UNKNOWN",
                })
            return "UNKNOWN"

        stock_rows = inventory.loc[
            (inventory["CustomerId"].astype(str) == str(customer_id))
            & (inventory["ProductId"].astype(str) == product_id)
            & inventory["LastUpdated"].notna()
            & (inventory["LastUpdated"] <= as_of)
        ].sort_values("LastUpdated")
        if stock_rows.empty:
            if stockout_evidence is not None:
                stockout_evidence.update({
                    "inventory_records": [],
                    "evidence_status": "missing",
                    "missing_reason": "NO_STOCK_RECORD_AS_OF_DATE",
                    "output": "UNKNOWN",
                })
            return "UNKNOWN"
        current_stock = float(stock_rows.iloc[-1].get("CurrentStock") or 0)
        coverage_days = max(current_stock, 0.0) / average_daily_demand
        if stockout_evidence is not None:
            stockout_evidence.update({
                "inventory_records": DecisionFeatureBuilder._trace_records(
                    stock_rows.tail(1),
                    ("CustomerId", "ProductId", "LastUpdated", "CurrentStock"),
                ),
                "current_stock": current_stock,
                "coverage_days": coverage_days,
                "evidence_status": "available",
            })
        if coverage_days <= policy.stockout_high_risk_coverage_days:
            result = "HIGH"
        elif coverage_days >= policy.stockout_low_risk_coverage_days:
            result = "LOW"
        else:
            result = "MEDIUM"
        if stockout_evidence is not None:
            stockout_evidence["output"] = result
        return result

    @staticmethod
    def _demand_trend(
        trends: pd.DataFrame,
        industry: str,
        product_id: str,
        as_of: pd.Timestamp,
        evidence: dict[str, Any] | None = None,
    ) -> str:
        rows = trends.loc[
            (trends["Industry"].astype(str).str.casefold() == industry.casefold())
            & (trends["ProductId"].astype(str) == product_id)
        ].copy()
        if "AsOfDate" in rows.columns:
            rows = rows.loc[rows["AsOfDate"].notna() & (rows["AsOfDate"] <= as_of)].sort_values("AsOfDate")
        trend_evidence: dict[str, Any] | None = None
        if evidence is not None:
            trend_evidence = evidence["product_demand_trend"] = {
                "source": "IndustryTrend",
                "filter": {
                    "Industry": industry,
                    "ProductId": product_id,
                    "AsOfDate_lte": as_of,
                },
                "matching_row_count": int(len(rows)),
                "records": DecisionFeatureBuilder._trace_records(
                    rows,
                    ("Industry", "ProductId", "AsOfDate", "TrendDirection", "CoverageRate", "PopularityScore"),
                ),
            }
        if rows.empty:
            if trend_evidence is not None:
                trend_evidence.update({
                    "evidence_status": "missing",
                    "missing_reason": "NO_TREND_RECORD_AS_OF_DATE",
                    "output": "UNKNOWN",
                })
            return "UNKNOWN"
        raw = str(rows.iloc[-1].get("TrendDirection") or "").strip().upper()
        result = raw if raw in {"UP", "DOWN", "STABLE"} else "UNKNOWN"
        if trend_evidence is not None:
            trend_evidence.update({
                "raw_trend_direction": raw,
                "evidence_status": "available",
                "output": result,
            })
        return result

    @staticmethod
    def _category_relevance(category: str, preferred_category: str | None) -> str:
        if not preferred_category:
            return "MEDIUM"
        return "HIGH" if category.casefold() == preferred_category.casefold() else "LOW"

    @staticmethod
    def _preferred_category(structured_intent: dict[str, Any]) -> str | None:
        preferences = structured_intent.get("soft_preferences", [])
        if isinstance(preferences, list):
            for item in preferences:
                if isinstance(item, dict) and str(item.get("type") or "").upper() == "CATEGORY":
                    value = str(item.get("value") or "").strip()
                    if value:
                        return value
        values = structured_intent.get("category_preference", [])
        if isinstance(values, list) and values:
            return str(values[0]).strip() or None
        return None

    def _event_baseline_source(
        self,
        workbook: dict[str, pd.DataFrame],
        orders: pd.DataFrame,
        customer_id: str,
        industry: str,
        product_id: str,
        occasion: str,
        as_of: pd.Timestamp,
        policy: V2FeaturePolicy,
        evidence: dict[str, Any] | None = None,
    ) -> str:
        if occasion in {"", "NONE"}:
            if evidence is not None:
                evidence["event_baseline"] = {
                    "sources": ["EventConfig", "OrderHistory"],
                    "occasion": occasion,
                    "fallback_order": list(policy.event_baseline_fallback_order),
                    "selected_source": "NONE",
                    "evidence_status": "not_applicable",
                }
            return "NONE"
        event_evidence: dict[str, Any] | None = None
        if evidence is not None:
            event_evidence = evidence["event_baseline"] = {
                "sources": ["EventConfig", "OrderHistory", "Customer"],
                "occasion": occasion,
                "as_of_date": as_of,
                "fallback_order": list(policy.event_baseline_fallback_order),
            }
        comparable_event_id = self._comparable_event_id(
            workbook["EventConfig"],
            occasion,
            as_of,
            evidence=event_evidence,
        )
        event_orders = pd.DataFrame()
        peer_ids: set[str] = set()
        if comparable_event_id:
            event_orders = orders.loc[
                (orders["ProductId"].astype(str) == product_id)
                & (orders.get("EventId", pd.Series(index=orders.index, dtype=object)).astype(str) == comparable_event_id)
            ]
            customers = workbook["Customer"]
            peer_ids = set(customers.loc[
                (customers["Industry"].astype(str).str.casefold() == industry.casefold())
                & (customers["CustomerId"].astype(str) != str(customer_id)),
                "CustomerId",
            ].astype(str))

        cutoff = as_of - pd.Timedelta(days=policy.recent_store_baseline_days)
        recent_store_orders = orders.loc[
            (orders["CustomerId"].astype(str) == str(customer_id))
            & (orders["ProductId"].astype(str) == product_id)
            & (orders["OrderDate"] >= cutoff)
        ]
        if event_evidence is not None:
            event_evidence.update({
                "comparable_event_id": comparable_event_id,
                "event_order_count": int(len(event_orders)),
                "event_order_records": self._trace_records(
                    event_orders,
                    ("OrderId", "CustomerId", "ProductId", "OrderDate", "Quantity", "EventId"),
                ),
                "peer_customer_count": int(len(peer_ids)),
                "peer_customer_ids": sorted(peer_ids),
                "recent_store_order_count": int(len(recent_store_orders)),
                "recent_store_order_records": self._trace_records(
                    recent_store_orders,
                    ("OrderId", "CustomerId", "ProductId", "OrderDate", "Quantity", "EventId"),
                ),
            })
        for source in policy.event_baseline_fallback_order:
            if source == "STORE_EVENT" and not event_orders.empty:
                if not event_orders.loc[
                    event_orders["CustomerId"].astype(str) == str(customer_id)
                ].empty:
                    if event_evidence is not None:
                        event_evidence.update({
                            "selected_source": source,
                            "evidence_status": "available",
                        })
                    return source
            elif source == "PEER_EVENT" and not event_orders.empty:
                if event_orders["CustomerId"].astype(str).isin(peer_ids).any():
                    if event_evidence is not None:
                        event_evidence.update({
                            "selected_source": source,
                            "evidence_status": "available",
                        })
                    return source
            elif source == "RECENT_STORE" and not recent_store_orders.empty:
                if event_evidence is not None:
                    event_evidence.update({
                        "selected_source": source,
                        "evidence_status": "available",
                    })
                return source
        if event_evidence is not None:
            event_evidence.update({
                "selected_source": "NONE",
                "evidence_status": "missing",
                "missing_reason": "NO_COMPARABLE_EVENT_OR_RECENT_STORE_ORDER",
            })
        return "NONE"

    @staticmethod
    def _comparable_event_id(
        events: pd.DataFrame,
        occasion: str,
        as_of: pd.Timestamp,
        evidence: dict[str, Any] | None = None,
    ) -> str | None:
        prepared = events.copy()
        prepared["EventWindowStart"] = pd.to_datetime(prepared["EventWindowStart"], errors="coerce")
        prepared["EventWindowEnd"] = pd.to_datetime(prepared["EventWindowEnd"], errors="coerce")
        rows = prepared.loc[
            prepared["EventName"].astype(str).str.upper().str.contains(occasion, regex=False)
            & (prepared["EventWindowStart"] <= as_of)
            & (prepared["EventWindowEnd"] >= as_of)
        ]
        if evidence is not None:
            evidence["event_config"] = {
                "source": "EventConfig",
                "filter": {
                    "occasion": occasion,
                    "EventWindowStart_lte": as_of,
                    "EventWindowEnd_gte": as_of,
                },
                "matching_row_count": int(len(rows)),
                "records": DecisionFeatureBuilder._trace_records(
                    rows,
                    (
                        "EventId",
                        "EventName",
                        "EventType",
                        "EventWindowStart",
                        "EventWindowEnd",
                        "ComparableEventId",
                    ),
                ),
            }
        if rows.empty:
            if evidence is not None:
                evidence["event_config"].update({
                    "evidence_status": "missing",
                    "missing_reason": "NO_ACTIVE_EVENT_RECORD",
                })
            return None
        comparable = rows.iloc[0].get("ComparableEventId")
        result = str(comparable).strip() if pd.notna(comparable) and str(comparable).strip() else None
        if evidence is not None:
            evidence["event_config"].update({
                "comparable_event_id": result,
                "evidence_status": "available" if result else "missing",
                "missing_reason": None if result else "NO_COMPARABLE_EVENT_ID",
            })
        return result

    @staticmethod
    def _signals(candidate: dict[str, Any], features: dict[str, str]) -> list[str]:
        signals = [
            f"PURCHASE_FREQUENCY={features['purchase_frequency']}",
            f"STOCKOUT_RISK={features['stockout_risk']}",
            f"SHELF_LIFE_LEVEL={features['shelf_life_level']}",
            f"PEER_PURCHASE_RATIO={features['peer_purchase_ratio']}",
            f"CATEGORY_RELEVANCE={features['category_relevance']}",
            f"PEER_POPULARITY={features['peer_popularity']}",
        ]
        if candidate.get("candidate_source") == "USER_REQUESTED":
            signals.append("USER_REQUESTED")
            if features.get("quantity_intent") in {"HIGH", "LOW"}:
                signals.append(f"USER_QUANTITY_INTENT={features['quantity_intent']}")
        elif candidate.get("candidate_source") == "HISTORICAL_PURCHASE":
            signals.append("STORE_PURCHASE_HISTORY")
        if features["occasion"] != "NONE":
            signals.append(f"OCCASION={features['occasion']}")
        if features["baseline_source"] != "NONE":
            signals.append(f"BASELINE_SOURCE={features['baseline_source']}")
        if features["product_demand_trend"] != "UNKNOWN":
            signals.append(f"PRODUCT_DEMAND_TREND={features['product_demand_trend']}")
        return signals

    @staticmethod
    def _policy_thresholds(policy: V2FeaturePolicy) -> dict[str, Any]:
        return {
            "purchase_frequency_window_days": policy.purchase_frequency_window_days,
            "purchase_frequency_high_threshold": policy.purchase_frequency_high_threshold,
            "purchase_frequency_low_threshold": policy.purchase_frequency_low_threshold,
            "stockout_high_risk_coverage_days": policy.stockout_high_risk_coverage_days,
            "stockout_low_risk_coverage_days": policy.stockout_low_risk_coverage_days,
            "discovery_history_lookback_months": policy.discovery_history_lookback_months,
            "discovery_peer_ratio_threshold": policy.discovery_peer_ratio_threshold,
            "recent_store_baseline_days": policy.recent_store_baseline_days,
            "event_baseline_fallback_order": list(policy.event_baseline_fallback_order),
        }

    @staticmethod
    def _trace_records(
        frame: pd.DataFrame,
        columns: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        if frame is None or frame.empty:
            return []
        available_columns = [column for column in columns if column in frame.columns]
        if not available_columns:
            return []
        records: list[dict[str, Any]] = []
        for _, row in frame.loc[:, available_columns].iterrows():
            item: dict[str, Any] = {}
            for column in available_columns:
                value = row.get(column)
                if pd.isna(value):
                    item[column] = None
                    continue
                if isinstance(value, pd.Timestamp):
                    item[column] = value.isoformat()
                    continue
                if hasattr(value, "item"):
                    try:
                        value = value.item()
                    except (AttributeError, ValueError):
                        pass
                item[column] = value
            records.append(item)
        return records

    @staticmethod
    def _customer_industry(customers: pd.DataFrame, customer_id: str) -> str:
        rows = customers.loc[customers["CustomerId"].astype(str) == str(customer_id)]
        if rows.empty:
            raise DecisionFeatureError(f"Unknown customer: {customer_id}")
        return str(rows.iloc[0].get("Industry") or "").strip()

    @classmethod
    def _validate_workbook(cls, workbook: dict[str, pd.DataFrame]) -> None:
        missing = sorted(name for name in cls.REQUIRED_SHEETS if name not in workbook)
        if missing:
            raise DecisionFeatureError(f"Missing decision-feature sheets: {', '.join(missing)}")

    @staticmethod
    def _as_timestamp(value: Any) -> pd.Timestamp:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise DecisionFeatureError(f"Invalid as_of_date: {value!r}")
        return pd.Timestamp(parsed).normalize()
