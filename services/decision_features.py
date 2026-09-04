from __future__ import annotations

from typing import Any

import pandas as pd

from services.v2_policy import V2FeaturePolicy


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
        feature_rows: list[dict[str, Any]] = []

        for candidate in candidates:
            if not candidate.get("eligible", True):
                continue
            product_id = str(candidate.get("candidate_id") or "")
            purchase_frequency = self._purchase_frequency(
                orders,
                customer_id,
                product_id,
                as_of,
                policy,
            )
            stockout_risk = self._stockout_risk(
                orders,
                inventory,
                customer_id,
                product_id,
                as_of,
                policy,
            )
            trend = self._demand_trend(trends, customer_industry, product_id, as_of)
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
    ) -> str:
        cutoff = as_of - pd.Timedelta(days=policy.purchase_frequency_window_days)
        count = len(orders.loc[
            (orders["CustomerId"].astype(str) == str(customer_id))
            & (orders["ProductId"].astype(str) == product_id)
            & (orders["OrderDate"] >= cutoff)
        ])
        if count >= policy.purchase_frequency_high_threshold:
            return "HIGH"
        if count <= policy.purchase_frequency_low_threshold:
            return "LOW"
        return "MEDIUM"

    @staticmethod
    def _stockout_risk(
        orders: pd.DataFrame,
        inventory: pd.DataFrame,
        customer_id: str,
        product_id: str,
        as_of: pd.Timestamp,
        policy: V2FeaturePolicy,
    ) -> str:
        cutoff = as_of - pd.Timedelta(days=policy.purchase_frequency_window_days)
        recent_orders = orders.loc[
            (orders["CustomerId"].astype(str) == str(customer_id))
            & (orders["ProductId"].astype(str) == product_id)
            & (orders["OrderDate"] >= cutoff)
        ]
        demand = pd.to_numeric(recent_orders.get("Quantity"), errors="coerce").fillna(0).sum()
        average_daily_demand = float(demand) / policy.purchase_frequency_window_days
        if average_daily_demand <= 0:
            return "UNKNOWN"

        stock_rows = inventory.loc[
            (inventory["CustomerId"].astype(str) == str(customer_id))
            & (inventory["ProductId"].astype(str) == product_id)
            & inventory["LastUpdated"].notna()
            & (inventory["LastUpdated"] <= as_of)
        ].sort_values("LastUpdated")
        if stock_rows.empty:
            return "UNKNOWN"
        current_stock = float(stock_rows.iloc[-1].get("CurrentStock") or 0)
        coverage_days = max(current_stock, 0.0) / average_daily_demand
        if coverage_days <= policy.stockout_high_risk_coverage_days:
            return "HIGH"
        if coverage_days >= policy.stockout_low_risk_coverage_days:
            return "LOW"
        return "MEDIUM"

    @staticmethod
    def _demand_trend(
        trends: pd.DataFrame,
        industry: str,
        product_id: str,
        as_of: pd.Timestamp,
    ) -> str:
        rows = trends.loc[
            (trends["Industry"].astype(str).str.casefold() == industry.casefold())
            & (trends["ProductId"].astype(str) == product_id)
        ].copy()
        if "AsOfDate" in rows.columns:
            rows = rows.loc[rows["AsOfDate"].notna() & (rows["AsOfDate"] <= as_of)].sort_values("AsOfDate")
        if rows.empty:
            return "UNKNOWN"
        raw = str(rows.iloc[-1].get("TrendDirection") or "").strip().upper()
        return raw if raw in {"UP", "DOWN", "STABLE"} else "UNKNOWN"

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
    ) -> str:
        if occasion in {"", "NONE"}:
            return "NONE"
        comparable_event_id = self._comparable_event_id(workbook["EventConfig"], occasion, as_of)
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
        for source in policy.event_baseline_fallback_order:
            if source == "STORE_EVENT" and not event_orders.empty:
                if not event_orders.loc[
                    event_orders["CustomerId"].astype(str) == str(customer_id)
                ].empty:
                    return source
            elif source == "PEER_EVENT" and not event_orders.empty:
                if event_orders["CustomerId"].astype(str).isin(peer_ids).any():
                    return source
            elif source == "RECENT_STORE" and not recent_store_orders.empty:
                return source
        return "NONE"

    @staticmethod
    def _comparable_event_id(events: pd.DataFrame, occasion: str, as_of: pd.Timestamp) -> str | None:
        prepared = events.copy()
        prepared["EventWindowStart"] = pd.to_datetime(prepared["EventWindowStart"], errors="coerce")
        prepared["EventWindowEnd"] = pd.to_datetime(prepared["EventWindowEnd"], errors="coerce")
        rows = prepared.loc[
            prepared["EventName"].astype(str).str.upper().str.contains(occasion, regex=False)
            & (prepared["EventWindowStart"] <= as_of)
            & (prepared["EventWindowEnd"] >= as_of)
        ]
        if rows.empty:
            return None
        comparable = rows.iloc[0].get("ComparableEventId")
        return str(comparable).strip() if pd.notna(comparable) and str(comparable).strip() else None

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
