from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from engines.scoring_utils import strength


HIGH_SCORE_THRESHOLD = 60
MEDIUM_SCORE_THRESHOLD = 40


@dataclass(frozen=True)
class ReplenishmentWeights:
    frequency: float = 0.20
    cycle: float = 0.20
    inventory: float = 0.20
    shelf_life: float = 0.15
    holiday: float = 0.15
    favorite: float = 0.10


class ReplenishmentEngine:
    def __init__(self) -> None:
        self.weights = ReplenishmentWeights()

    def generate_recommendations(
        self,
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        orders = self._prepare_orders(workbook, customer_id)
        inventory = self._prepare_inventory(workbook, customer_id)
        products = workbook["Product"].copy()
        favorites = workbook.get("Favorites", pd.DataFrame()).copy()
        holiday_products = workbook.get("HolidayProduct", pd.DataFrame()).copy()

        reference_date = max(
            orders["OrderDate"].max(),
            inventory["LastUpdated"].max() if not inventory.empty else orders["OrderDate"].max(),
        )
        recent_cutoff = reference_date - pd.Timedelta(days=90)

        favorite_ids = set(
            favorites.loc[favorites.get("CustomerId", pd.Series(dtype=str)) == customer_id, "ProductId"]
            if not favorites.empty
            else []
        )
        holiday_map = (
            holiday_products.sort_values("Weight", ascending=False)
            .drop_duplicates(subset=["ProductId"])
            .set_index("ProductId")
            .to_dict(orient="index")
            if not holiday_products.empty
            else {}
        )

        recommendations: list[dict[str, Any]] = []
        purchased_products = orders["ProductId"].dropna().unique().tolist()
        inventory_map = inventory.set_index("ProductId").to_dict(orient="index")
        product_map = products.set_index("ProductId").to_dict(orient="index")

        for product_id in purchased_products:
            if product_id not in product_map or product_id not in inventory_map:
                continue

            product_orders = orders.loc[orders["ProductId"] == product_id].sort_values("OrderDate")
            recent_orders = product_orders.loc[product_orders["OrderDate"] >= recent_cutoff]
            inventory_row = inventory_map[product_id]
            product_row = product_map[product_id]

            score_pack = self._score_product(
                product_id=product_id,
                product_row=product_row,
                product_orders=product_orders,
                recent_orders=recent_orders,
                inventory_row=inventory_row,
                context=context,
                is_favorite=product_id in favorite_ids,
                holiday_info=holiday_map.get(product_id),
                reference_date=reference_date,
            )

            if score_pack["quantity"] <= 0:
                continue

            recommendations.append(score_pack)

        recommendations.sort(key=lambda item: (-item["score"], -item["quantity"], item["product"]))

        high_score = [r for r in recommendations if r["score"] >= HIGH_SCORE_THRESHOLD]
        if high_score:
            return high_score[:limit]

        medium_score = [r for r in recommendations if r["score"] >= MEDIUM_SCORE_THRESHOLD]
        if medium_score:
            return medium_score[:limit]

        return recommendations[:limit]

    def _score_product(
        self,
        product_id: str,
        product_row: dict[str, Any],
        product_orders: pd.DataFrame,
        recent_orders: pd.DataFrame,
        inventory_row: dict[str, Any],
        context: dict[str, Any],
        is_favorite: bool,
        holiday_info: dict[str, Any] | None,
        reference_date: pd.Timestamp,
    ) -> dict[str, Any]:
        order_count = len(recent_orders)
        avg_cycle_days = self._average_cycle_days(product_orders)
        days_since_last = max((reference_date - product_orders["OrderDate"].max()).days, 0)
        avg_daily_demand = self._average_daily_demand(recent_orders, product_orders, reference_date)
        current_stock = float(inventory_row["CurrentStock"])
        coverage_days = current_stock / avg_daily_demand if avg_daily_demand > 0 else float("inf")
        historical_avg_qty = float(product_orders.tail(3)["Quantity"].mean())

        frequency_raw = self._frequency_score(order_count)
        cycle_raw = self._cycle_score(days_since_last, avg_cycle_days)
        inventory_raw = self._inventory_score(coverage_days)
        shelf_raw = self._shelf_life_score(product_row, context)
        holiday_raw = self._holiday_score(context, holiday_info)
        favorite_raw = 100 if is_favorite else 0
        context_adjustment = self._context_adjustment(product_row, context)

        weighted_score = (
            frequency_raw * self.weights.frequency
            + cycle_raw * self.weights.cycle
            + inventory_raw * self.weights.inventory
            + shelf_raw * self.weights.shelf_life
            + holiday_raw * self.weights.holiday
            + favorite_raw * self.weights.favorite
        )
        final_score = max(0.0, min(100.0, weighted_score + context_adjustment))
        quantity = self._recommended_quantity(
            product_row=product_row,
            context=context,
            historical_avg_qty=historical_avg_qty,
            avg_daily_demand=avg_daily_demand,
            current_stock=current_stock,
        )

        why = [
            f"Purchased {order_count} times in last 90 days." if order_count else None,
            f"Average cycle is {avg_cycle_days:.1f} days and last purchase was {days_since_last} days ago.",
            f"Inventory covers {coverage_days:.1f} days." if coverage_days != float('inf') else "Inventory coverage is not limited by recent demand.",
            "Favorited by the customer." if is_favorite else None,
            holiday_info["Reason"] if holiday_info and context.get("TimeRange") == "holiday_window" else None,
        ]
        why_not = [
            f"Fresh product is constrained by long shelf-life preference."
            if context.get("ShelfLifePreference") == "LONG" and product_row.get("ProductType") == "Fresh"
            else None
        ]

        return {
            "product": product_row["ProductName"],
            "product_id": product_id,
            "quantity": int(round(quantity)),
            "current_stock": round(current_stock, 2),
            "unit": product_row.get("Unit", ""),
            "product_type": product_row.get("ProductType", ""),
            "score": round(final_score, 1),
            "recommendation_strength": strength(final_score),
            "why": [item for item in why if item],
            "why_not": [item for item in why_not if item],
            "estimated_cost": round(quantity * float(product_row.get("AvgCost", 0.0)), 2),
            "unit_cost": round(float(product_row.get("AvgCost", 0.0)), 2),
            "coverage_days": None if coverage_days == float("inf") else round(coverage_days, 1),
            "avg_daily_demand": round(avg_daily_demand, 2),
            "historical_avg_qty": round(historical_avg_qty, 2),
        }

    @staticmethod
    def _prepare_orders(workbook: dict[str, pd.DataFrame], customer_id: str) -> pd.DataFrame:
        orders = workbook["OrderHistory"].copy()
        orders["OrderDate"] = pd.to_datetime(orders["OrderDate"])
        return orders.loc[orders["CustomerId"] == customer_id].copy()

    @staticmethod
    def _prepare_inventory(workbook: dict[str, pd.DataFrame], customer_id: str) -> pd.DataFrame:
        inventory = workbook["Inventory"].copy()
        inventory["LastUpdated"] = pd.to_datetime(inventory["LastUpdated"])
        if "BatchExpiryDate" in inventory.columns:
            inventory["BatchExpiryDate"] = pd.to_datetime(inventory["BatchExpiryDate"], errors="coerce")
        return inventory.loc[inventory["CustomerId"] == customer_id].copy()

    @staticmethod
    def _frequency_score(order_count: int) -> int:
        if order_count >= 12:
            return 100
        if order_count >= 8:
            return 80
        if order_count >= 4:
            return 60
        if order_count >= 1:
            return 40
        return 0

    @staticmethod
    def _cycle_score(days_since_last: int, avg_cycle_days: float) -> int:
        if avg_cycle_days <= 0:
            return 20
        cycle_ratio = days_since_last / avg_cycle_days
        if cycle_ratio >= 1:
            return 100
        if cycle_ratio >= 0.8:
            return 80
        if cycle_ratio >= 0.5:
            return 60
        return 20

    @staticmethod
    def _inventory_score(coverage_days: float) -> int:
        if coverage_days <= 3:
            return 100
        if coverage_days <= 7:
            return 80
        if coverage_days <= 14:
            return 50
        return 20

    @staticmethod
    def _shelf_life_score(product_row: dict[str, Any], context: dict[str, Any]) -> int:
        product_type = str(product_row.get("ProductType", "")).strip()
        shelf_days = float(product_row.get("ShelfLifeDays", 0))
        preference = context.get("ShelfLifePreference")

        if product_type == "Frozen":
            return 100
        if product_type == "Dry":
            return 100
        if product_type == "Chilled":
            return 80 if preference != "LONG" else 90
        if preference == "LONG":
            if shelf_days >= 14:
                return 60
            if shelf_days >= 7:
                return 40
            return 30
        return 75

    @staticmethod
    def _holiday_score(context: dict[str, Any], holiday_info: dict[str, Any] | None) -> int:
        if not holiday_info:
            return 0
        if context.get("TimeRange") != "holiday_window":
            return 0
        return int(min(float(holiday_info.get("Weight", 0)), 100))

    @staticmethod
    def _context_adjustment(product_row: dict[str, Any], context: dict[str, Any]) -> float:
        adjustment = 0.0
        if context.get("TrafficLevel") == "HIGH":
            adjustment += 5
        if context.get("PromotionFlag"):
            adjustment += 5
        if context.get("PreferredCategory") and context["PreferredCategory"] == product_row.get("Category"):
            adjustment += 5
        if context.get("ExcludedCategory") and context["ExcludedCategory"] == product_row.get("Category"):
            adjustment -= 15
        if context.get("ShelfLifePreference") == "LONG":
            product_type = product_row.get("ProductType")
            if product_type in {"Frozen", "Dry"}:
                adjustment += 3
            elif product_type == "Fresh":
                adjustment -= 8
        return max(-15.0, min(15.0, adjustment))

    def _recommended_quantity(
        self,
        product_row: dict[str, Any],
        context: dict[str, Any],
        historical_avg_qty: float,
        avg_daily_demand: float,
        current_stock: float,
    ) -> int:
        target_coverage_days = {
            "Fresh": 7,
            "Chilled": 10,
            "Frozen": 21,
            "Dry": 30,
        }.get(str(product_row.get("ProductType", "")).strip(), 10)
        if context.get("TrafficLevel") == "HIGH":
            target_coverage_days += 2
        if context.get("PromotionFlag"):
            target_coverage_days += 2
        if context.get("TimeRange") == "holiday_window":
            target_coverage_days += 2

        inventory_gap_qty = max(target_coverage_days * avg_daily_demand - current_stock, 0.0)
        preliminary_qty = max(historical_avg_qty, inventory_gap_qty)

        if context.get("ShelfLifePreference") == "LONG":
            product_type = product_row.get("ProductType")
            if product_type == "Fresh":
                preliminary_qty = min(preliminary_qty, historical_avg_qty)
            elif product_type == "Chilled":
                preliminary_qty = min(preliminary_qty, historical_avg_qty * 1.5)

        budget = context.get("Budget")
        if budget:
            avg_cost = float(product_row.get("AvgCost", 0.0))
            if avg_cost > 0:
                preliminary_qty = min(preliminary_qty, budget / avg_cost)

        return max(int(round(preliminary_qty)), 0)

    @staticmethod
    def _average_cycle_days(product_orders: pd.DataFrame) -> float:
        if len(product_orders) < 2:
            return 30.0
        diffs = product_orders["OrderDate"].sort_values().diff().dt.days.dropna()
        return float(diffs.mean()) if not diffs.empty else 30.0

    @staticmethod
    def _average_daily_demand(
        recent_orders: pd.DataFrame,
        product_orders: pd.DataFrame,
        reference_date: pd.Timestamp,
    ) -> float:
        if not recent_orders.empty:
            return float(recent_orders["Quantity"].sum()) / 90.0
        span_days = max((reference_date - product_orders["OrderDate"].min()).days, 1)
        return float(product_orders["Quantity"].sum()) / span_days


