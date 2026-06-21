from __future__ import annotations

from typing import Any

import pandas as pd


class RiskEngine:
    def generate_risks(
        self,
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        inventory = workbook["Inventory"].copy()
        products = workbook["Product"].copy()
        orders = workbook["OrderHistory"].copy()

        inventory["LastUpdated"] = pd.to_datetime(inventory["LastUpdated"])
        inventory["BatchExpiryDate"] = pd.to_datetime(inventory["BatchExpiryDate"], errors="coerce")
        orders["OrderDate"] = pd.to_datetime(orders["OrderDate"])

        inventory = inventory.loc[inventory["CustomerId"] == customer_id].copy()
        orders = orders.loc[orders["CustomerId"] == customer_id].copy()
        product_map = products.set_index("ProductId").to_dict(orient="index")
        reference_date = max(inventory["LastUpdated"].max(), orders["OrderDate"].max())

        results: list[dict[str, Any]] = []
        for _, row in inventory.iterrows():
            product_id = row["ProductId"]
            if product_id not in product_map:
                continue

            product = product_map[product_id]
            product_orders = orders.loc[orders["ProductId"] == product_id]
            recent_orders = product_orders.loc[product_orders["OrderDate"] >= reference_date - pd.Timedelta(days=90)]
            avg_daily_demand = float(recent_orders["Quantity"].sum()) / 90.0 if not recent_orders.empty else 0.0
            coverage_days = float(row["CurrentStock"]) / avg_daily_demand if avg_daily_demand > 0 else float("inf")

            threshold = self._threshold_days(product.get("ProductType"))
            risk_level = self._risk_level(
                coverage_days=coverage_days,
                threshold=threshold,
                expiry_date=row.get("BatchExpiryDate"),
                reference_date=reference_date,
            )
            results.append(
                {
                    "product": product["ProductName"],
                    "product_id": product_id,
                    "quantity": float(row["CurrentStock"]),
                    "unit": product.get("Unit", ""),
                    "score": self._risk_score(risk_level),
                    "recommendation_strength": risk_level,
                    "why": [
                        f"Inventory covers {coverage_days:.1f} days." if coverage_days != float("inf") else "Recent demand is too low to estimate coverage.",
                        f"Alert threshold for {product.get('ProductType')} is {threshold} days.",
                    ],
                    "why_not": [],
                    "risk_level": risk_level,
                    "coverage_days": None if coverage_days == float("inf") else round(coverage_days, 1),
                }
            )

        results.sort(key=lambda item: (-item["score"], item["product"]))
        return results[:limit]

    @staticmethod
    def _threshold_days(product_type: Any) -> int:
        if product_type == "Frozen":
            return 14
        if product_type == "Dry":
            return 21
        return 7

    @staticmethod
    def _risk_level(
        coverage_days: float,
        threshold: int,
        expiry_date: Any,
        reference_date: pd.Timestamp,
    ) -> str:
        if pd.notna(expiry_date):
            days_to_expiry = (expiry_date - reference_date).days
            if days_to_expiry <= 2:
                return "Critical"
        if coverage_days == float("inf"):
            return "Low"
        if coverage_days < threshold * 0.5:
            return "Critical"
        if coverage_days < threshold:
            return "High"
        if coverage_days < threshold * 1.5:
            return "Medium"
        return "Low"

    @staticmethod
    def _risk_score(risk_level: str) -> int:
        return {
            "Critical": 100,
            "High": 80,
            "Medium": 60,
            "Low": 20,
        }[risk_level]
