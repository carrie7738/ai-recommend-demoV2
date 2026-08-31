from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from services.v2_policy import V2FeaturePolicy


class CandidatePoolError(ValueError):
    """Raised when candidate generation cannot safely use the supplied data."""


@dataclass(frozen=True)
class CandidatePoolResult:
    eligible_candidates: list[dict[str, Any]]
    rejected_candidates: list[dict[str, Any]]

    def find(self, product_id: str) -> dict[str, Any] | None:
        for candidate in [*self.eligible_candidates, *self.rejected_candidates]:
            if candidate.get("candidate_id") == product_id:
                return candidate
        return None


def classify_shelf_life(product: dict[str, Any]) -> str:
    """Use the existing V1 product-type semantics without inventing new day thresholds."""
    product_type = str(product.get("ProductType") or "").strip().casefold()
    if product_type in {"dry", "frozen"}:
        return "LONG"
    if product_type == "fresh":
        return "SHORT"
    if product_type == "chilled":
        return "MEDIUM"
    return "UNKNOWN"


class CandidatePoolBuilder:
    REQUIRED_SHEETS = {"Customer", "Product", "OrderHistory", "SupplyAvailability", "V2FeaturePolicy"}

    def build(
        self,
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        structured_intent: dict[str, Any],
        as_of_date: Any,
    ) -> CandidatePoolResult:
        self._validate_workbook(workbook)
        policy = V2FeaturePolicy.from_workbook(workbook)
        as_of = self._as_timestamp(as_of_date)

        customers = workbook["Customer"].copy()
        products = workbook["Product"].copy()
        orders = workbook["OrderHistory"].copy()
        supply = workbook["SupplyAvailability"].copy()
        orders["OrderDate"] = pd.to_datetime(orders["OrderDate"], errors="coerce")
        orders = orders.loc[orders["OrderDate"].notna() & (orders["OrderDate"] <= as_of)].copy()

        customer_rows = customers.loc[customers["CustomerId"].astype(str) == str(customer_id)]
        if customer_rows.empty:
            raise CandidatePoolError(f"Unknown customer: {customer_id}")
        target_industry = str(customer_rows.iloc[0].get("Industry") or "").strip()

        supply_map = (
            supply.drop_duplicates(subset=["ProductId"], keep="last")
            .set_index("ProductId")
            .to_dict(orient="index")
        )
        product_rows = {
            str(row["ProductId"]): row.to_dict()
            for _, row in products.iterrows()
            if pd.notna(row.get("ProductId"))
        }
        explicit = self._resolve_explicit_products(structured_intent, product_rows)
        history_cutoff = as_of - pd.DateOffset(months=policy.discovery_history_lookback_months)
        lookback_orders = orders.loc[orders["OrderDate"] >= history_cutoff].copy()
        target_product_ids = set(
            lookback_orders.loc[
                lookback_orders["CustomerId"].astype(str) == str(customer_id),
                "ProductId",
            ].astype(str)
        )
        peer_customer_ids = set(
            customers.loc[
                customers["Industry"].astype(str).str.casefold() == target_industry.casefold(),
                "CustomerId",
            ].astype(str)
        )

        eligible: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for product_id, product in product_rows.items():
            reference = explicit.get(product_id)
            base = self._candidate_base(product_id, product, supply_map.get(product_id), reference)
            rejection = self._eligibility_rejection(product, supply_map.get(product_id), structured_intent)
            if rejection:
                if reference or product_id in target_product_ids:
                    rejected.append({**base, "eligible": False, "rejection_code": rejection})
                continue

            peer_ratio = self._peer_purchase_ratio(
                lookback_orders,
                product_id,
                peer_customer_ids,
            )
            if reference:
                has_occasion = str(structured_intent.get("occasion") or "NONE").upper() != "NONE"
                recommendation_type = (
                    "REPLENISHMENT"
                    if product_id in target_product_ids or has_occasion
                    else "DISCOVERY"
                )
                source = "USER_REQUESTED"
            elif product_id in target_product_ids:
                recommendation_type = "REPLENISHMENT"
                source = "HISTORICAL_PURCHASE"
            elif peer_ratio >= policy.discovery_peer_ratio_threshold:
                recommendation_type = "DISCOVERY"
                source = "PEER_SIGNAL"
            else:
                continue

            eligible.append({
                **base,
                "eligible": True,
                "rejection_code": None,
                "recommendation_type": recommendation_type,
                "candidate_source": source,
                "peer_purchase_ratio": round(peer_ratio, 4),
            })

        eligible.sort(key=lambda item: item["candidate_id"])
        rejected.sort(key=lambda item: item["candidate_id"])
        return CandidatePoolResult(eligible_candidates=eligible, rejected_candidates=rejected)

    @staticmethod
    def _candidate_base(
        product_id: str,
        product: dict[str, Any],
        supply: dict[str, Any] | None,
        explicit_reference: dict[str, str] | None,
    ) -> dict[str, Any]:
        available_stock = CandidatePoolBuilder._available_stock(supply)
        sales_unit = CandidatePoolBuilder._sales_unit(product.get("SalesUnit"))
        return {
            "candidate_id": product_id,
            "product_name": str(product.get("ProductName") or ""),
            "category": str(product.get("Category") or ""),
            "product_type": str(product.get("ProductType") or ""),
            "shelf_life_level": classify_shelf_life(product),
            "sales_unit": sales_unit,
            "available_stock": max(available_stock, 0.0),
            "quantity_intent": (explicit_reference or {}).get("quantity_intent", "NORMAL"),
        }

    def _eligibility_rejection(
        self,
        product: dict[str, Any],
        supply: dict[str, Any] | None,
        structured_intent: dict[str, Any],
    ) -> str | None:
        if not self._as_bool(product.get("IsSellable")):
            return "INELIGIBLE_CANDIDATE"
        if self._available_stock(supply) <= 0:
            return "NO_AVAILABLE_STOCK"
        if not self._passes_hard_constraints(product, structured_intent.get("hard_constraints", [])):
            return "HARD_CONSTRAINT_FILTER"
        return None

    @staticmethod
    def _passes_hard_constraints(product: dict[str, Any], constraints: Any) -> bool:
        if not isinstance(constraints, list):
            return True
        category = str(product.get("Category") or "").strip().casefold()
        shelf_life = classify_shelf_life(product)
        for constraint in constraints:
            if not isinstance(constraint, dict):
                continue
            kind = str(constraint.get("type") or "").upper()
            operator = str(constraint.get("operator") or "").upper()
            values = {str(value).strip().casefold() for value in constraint.get("values", [])}
            if kind == "CATEGORY" and operator == "INCLUDE_ONLY" and category not in values:
                return False
            if kind == "CATEGORY" and operator == "EXCLUDE" and category in values:
                return False
            if kind == "SHELF_LIFE" and operator == "REQUIRE_LEVEL":
                if shelf_life != str(constraint.get("value") or "").upper():
                    return False
        return True

    @staticmethod
    def _resolve_explicit_products(
        structured_intent: dict[str, Any],
        products: dict[str, dict[str, Any]],
    ) -> dict[str, dict[str, str]]:
        resolved: dict[str, dict[str, str]] = {}
        by_name = {
            str(product.get("ProductName") or "").strip().casefold(): product_id
            for product_id, product in products.items()
        }
        raw_items = structured_intent.get("explicit_products", [])
        if not isinstance(raw_items, list):
            return resolved
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            product_id = str(item.get("sku") or "").strip().upper()
            if not product_id:
                product_id = by_name.get(str(item.get("product_name") or "").strip().casefold(), "")
            if product_id not in products:
                continue
            quantity_intent = str(item.get("quantity_intent") or "NORMAL").upper()
            if quantity_intent not in {"LOW", "NORMAL", "HIGH"}:
                quantity_intent = "NORMAL"
            resolved[product_id] = {"quantity_intent": quantity_intent}
        return resolved

    @staticmethod
    def _peer_purchase_ratio(
        orders: pd.DataFrame,
        product_id: str,
        peer_customer_ids: set[str],
    ) -> float:
        product_orders = orders.loc[orders["ProductId"].astype(str) == product_id]
        total = len(product_orders)
        if total == 0:
            return 0.0
        peer_count = product_orders["CustomerId"].astype(str).isin(peer_customer_ids).sum()
        return float(peer_count) / float(total)

    @classmethod
    def _validate_workbook(cls, workbook: dict[str, pd.DataFrame]) -> None:
        missing = sorted(name for name in cls.REQUIRED_SHEETS if name not in workbook)
        if missing:
            raise CandidatePoolError(f"Missing candidate-pool sheets: {', '.join(missing)}")

    @staticmethod
    def _as_timestamp(value: Any) -> pd.Timestamp:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise CandidatePoolError(f"Invalid as_of_date: {value!r}")
        return pd.Timestamp(parsed).normalize()

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if pd.isna(value):
            return False
        return str(value).strip().casefold() in {"true", "1", "yes", "y"}

    @staticmethod
    def _available_stock(supply: dict[str, Any] | None) -> float:
        if supply is None:
            return 0.0
        value = supply.get("AvailableStock")
        if pd.isna(value):
            return 0.0
        try:
            return max(float(value), 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _sales_unit(value: Any) -> int:
        if pd.isna(value):
            return 1
        try:
            return max(int(float(value)), 1)
        except (TypeError, ValueError):
            return 1
