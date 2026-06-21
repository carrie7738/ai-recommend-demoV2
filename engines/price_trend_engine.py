from __future__ import annotations

from typing import Any

import pandas as pd

from engines.scoring_utils import strength


class PriceTrendEngine:
    """Computes product-level price trend signals from an optional PriceHistory sheet."""

    REQUIRED_COLUMNS = {"ProductId", "PriceDate", "UnitPrice"}

    def enrich_recommendations(
        self,
        recommendations: list[dict[str, Any]],
        workbook: dict[str, pd.DataFrame],
    ) -> list[dict[str, Any]]:
        if not recommendations:
            return recommendations

        price_history = workbook.get("PriceHistory")
        if price_history is None or price_history.empty:
            return recommendations

        price_history = self._prepare_price_history(price_history)
        if price_history.empty:
            return recommendations

        enriched: list[dict[str, Any]] = []
        for item in recommendations:
            price_signal = self.calculate_signal(price_history, item["product_id"])
            enriched_item = dict(item)
            if price_signal:
                enriched_item = self._adjust_quantity_and_cost(enriched_item, price_signal)
                enriched_item["price_trend"] = price_signal
                enriched_item["score"] = self._adjust_score(
                    base_score=float(enriched_item.get("score", 0)),
                    price_signal=price_signal,
                    coverage_days=enriched_item.get("coverage_days"),
                )
                enriched_item["recommendation_strength"] = strength(enriched_item["score"])
                enriched_item["why"] = self._append_price_reason(
                    enriched_item.get("why", []),
                    price_signal,
                )
            enriched.append(enriched_item)

        enriched.sort(key=lambda item: (-item["score"], -item.get("quantity", 0), item["product"]))
        return enriched

    def _adjust_quantity_and_cost(
        self,
        item: dict[str, Any],
        price_signal: dict[str, Any],
    ) -> dict[str, Any]:
        adjusted = dict(item)
        quantity = int(round(float(adjusted.get("quantity", 0))))
        if quantity <= 0:
            return adjusted

        product_type = str(adjusted.get("product_type", "")).strip()
        coverage_days = adjusted.get("coverage_days")
        signal = price_signal.get("price_signal")

        adjusted_quantity = quantity
        if signal == "Buy Now" and product_type not in {"Fresh", "Chilled"}:
            adjusted_quantity = int(round(quantity * 1.2))
        elif signal == "Buy Now" and product_type == "Chilled":
            adjusted_quantity = int(round(quantity * 1.1))
        elif signal == "Wait" and (coverage_days is None or coverage_days > 7):
            adjusted_quantity = int(round(quantity * 0.85))

        if product_type == "Fresh":
            historical_avg_qty = float(adjusted.get("historical_avg_qty", quantity))
            adjusted_quantity = min(adjusted_quantity, max(int(round(historical_avg_qty)), 1))

        adjusted_quantity = max(adjusted_quantity, 1)
        current_price = float(price_signal.get("current_price", 0.0))
        if current_price > 0:
            adjusted["quantity"] = adjusted_quantity
            adjusted["estimated_cost"] = round(adjusted_quantity * current_price, 2)
            adjusted["unit_cost"] = round(current_price, 2)
            if adjusted_quantity != quantity:
                adjusted["why"] = self._append_quantity_reason(
                    adjusted.get("why", []),
                    signal,
                    product_type,
                )

        return adjusted

    def calculate_signal(
        self,
        price_history: pd.DataFrame,
        product_id: str,
    ) -> dict[str, Any] | None:
        product_prices = price_history.loc[price_history["ProductId"] == product_id].copy()
        if product_prices.empty:
            return None

        latest_date = product_prices["PriceDate"].max()
        recent_prices = product_prices.loc[
            product_prices["PriceDate"] >= latest_date - pd.Timedelta(days=90)
        ].copy()
        if recent_prices.empty:
            return None

        latest_row = recent_prices.sort_values("PriceDate").iloc[-1]
        current_price = float(latest_row["UnitPrice"])
        min_price = float(recent_prices["UnitPrice"].min())
        max_price = float(recent_prices["UnitPrice"].max())
        avg_30d_price = float(
            recent_prices.loc[
                recent_prices["PriceDate"] >= latest_date - pd.Timedelta(days=30),
                "UnitPrice",
            ].mean()
        )
        avg_90d_price = float(recent_prices["UnitPrice"].mean())

        price_range = max_price - min_price
        price_position = 0.5 if price_range <= 0 else (current_price - min_price) / price_range
        price_position = max(0.0, min(1.0, price_position))
        signal = self._price_signal(price_position)

        return {
            "current_price": round(current_price, 2),
            "avg_30d_price": round(avg_30d_price, 2),
            "avg_90d_price": round(avg_90d_price, 2),
            "min_90d_price": round(min_price, 2),
            "max_90d_price": round(max_price, 2),
            "price_position": round(price_position, 2),
            "price_signal": signal,
            "price_adjustment": self._price_adjustment(signal),
        }

    @classmethod
    def _prepare_price_history(cls, price_history: pd.DataFrame) -> pd.DataFrame:
        if not cls.REQUIRED_COLUMNS.issubset(set(price_history.columns)):
            return pd.DataFrame()

        prepared = price_history.copy()
        prepared["PriceDate"] = pd.to_datetime(prepared["PriceDate"], errors="coerce")
        prepared["UnitPrice"] = pd.to_numeric(prepared["UnitPrice"], errors="coerce")
        prepared = prepared.dropna(subset=["ProductId", "PriceDate", "UnitPrice"])
        prepared["ProductId"] = prepared["ProductId"].astype(str)
        return prepared

    @staticmethod
    def _price_signal(price_position: float) -> str:
        if price_position <= 0.25:
            return "Buy Now"
        if price_position >= 0.75:
            return "Wait"
        return "Fair Price"

    @staticmethod
    def _price_adjustment(signal: str) -> float:
        if signal == "Buy Now":
            return 8.0
        if signal == "Wait":
            return -8.0
        return 0.0

    @staticmethod
    def _adjust_score(
        base_score: float,
        price_signal: dict[str, Any],
        coverage_days: float | None,
    ) -> float:
        adjustment = float(price_signal.get("price_adjustment", 0.0))
        if price_signal.get("price_signal") == "Wait" and coverage_days is not None and coverage_days <= 3:
            adjustment = max(adjustment, -3.0)
        return round(max(0.0, min(100.0, base_score + adjustment)), 1)

    @staticmethod
    def _append_price_reason(reasons: list[str], price_signal: dict[str, Any]) -> list[str]:
        signal = price_signal.get("price_signal")
        if signal == "Buy Now":
            reason = "Current price is near the 90-day low."
        elif signal == "Wait":
            reason = "Current price is near the 90-day high; quantity is budget protected."
        else:
            reason = "Current price is close to the recent average."

        if reason in reasons:
            return reasons
        return [*reasons, reason]

    @staticmethod
    def _append_quantity_reason(
        reasons: list[str],
        signal: str | None,
        product_type: str,
    ) -> list[str]:
        if signal == "Buy Now":
            reason = "Quantity increased modestly because price is attractive and shelf life supports holding stock."
        elif signal == "Wait":
            reason = "Quantity reduced because current price is high and inventory coverage is safe."
        else:
            return reasons

        if product_type == "Fresh":
            return reasons
        if reason in reasons:
            return reasons
        return [*reasons, reason]
