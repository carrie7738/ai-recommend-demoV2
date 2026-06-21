from __future__ import annotations

from typing import Any

import pandas as pd

from engines.scoring_utils import strength


class GrowthEngine:
    def generate_opportunities(
        self,
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        context: dict[str, Any],
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        customers = workbook["Customer"].copy()
        products = workbook["Product"].copy()
        trends = workbook["IndustryTrend"].copy()
        orders = workbook["OrderHistory"].copy()
        favorites = workbook.get("Favorites", pd.DataFrame()).copy()

        customer_row = customers.loc[customers["CustomerId"] == customer_id]
        if customer_row.empty:
            return []
        industry = customer_row.iloc[0]["Industry"]

        orders = orders.loc[orders["CustomerId"] == customer_id]
        purchased_ids = set(orders["ProductId"].dropna().tolist())
        product_history = orders.merge(products, on="ProductId", how="left")
        favorite_ids = set(
            favorites.loc[favorites.get("CustomerId", pd.Series(dtype=str)) == customer_id, "ProductId"]
            if not favorites.empty
            else []
        )

        margin_scale = max(float(products["ProfitMargin"].max()), 0.01)
        merged = trends.loc[trends["Industry"] == industry].merge(products, on="ProductId", how="left")
        merged = merged.loc[~merged["ProductId"].isin(purchased_ids)].copy()
        if merged.empty:
            return []

        results: list[dict[str, Any]] = []
        for _, row in merged.iterrows():
            if context.get("ExcludedCategory") and context["ExcludedCategory"] == row.get("Category"):
                continue

            favorite_score = 100 if row["ProductId"] in favorite_ids else 0
            profit_score = float(row.get("ProfitMargin", 0.0)) / margin_scale * 100
            score = (
                float(row.get("CoverageRate", 0.0)) * 0.5
                + float(row.get("PopularityScore", 0.0)) * 0.2
                + favorite_score * 0.2
                + profit_score * 0.1
            )
            if context.get("PreferredCategory") and context["PreferredCategory"] == row.get("Category"):
                score += 5
            score = min(score, 100.0)

            trial_quantity = self._trial_quantity(row, product_history)
            avg_cost = float(row.get("AvgCost", 0.0))

            results.append(
                {
                    "product": row["ProductName"],
                    "product_id": row["ProductId"],
                    "quantity": trial_quantity,
                    "unit": row.get("Unit", ""),
                    "product_type": row.get("ProductType", ""),
                    "score": round(score, 1),
                    "recommendation_strength": strength(score),
                    "priority": "Trial Buy",
                    "why": [
                        f"Industry coverage rate is {float(row.get('CoverageRate', 0.0)):.0f}%.",
                        f"Popularity score is {float(row.get('PopularityScore', 0.0)):.0f}.",
                        f"Profit margin is {float(row.get('ProfitMargin', 0.0)):.0%}.",
                        "Trial quantity recommended to test growth opportunity.",
                    ],
                    "why_not": [],
                    "estimated_cost": round(trial_quantity * avg_cost, 2),
                    "unit_cost": round(avg_cost, 2),
                    "coverage_days": None,
                    "historical_avg_qty": trial_quantity,
                }
            )

        results.sort(key=lambda item: (-item["score"], item["product"]))
        return results[:limit]

    @staticmethod
    def _trial_quantity(row: pd.Series, product_history: pd.DataFrame) -> int:
        category = row.get("Category")
        product_type = row.get("ProductType")
        comparable = product_history.loc[
            (product_history["Category"] == category)
            | (product_history["ProductType"] == product_type)
        ].copy()

        if comparable.empty:
            base_quantity = 3.0
        else:
            base_quantity = float(comparable.groupby("ProductId")["Quantity"].mean().mean())

        trial_quantity = max(round(base_quantity * 0.25), 1)
        if product_type == "Fresh":
            return int(min(trial_quantity, 3))
        if product_type == "Chilled":
            return int(min(trial_quantity, 4))
        return int(min(trial_quantity, 6))
