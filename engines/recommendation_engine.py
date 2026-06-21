from __future__ import annotations

from typing import Any

import pandas as pd

from engines.growth_engine import GrowthEngine
from engines.price_trend_engine import PriceTrendEngine
from engines.replenishment_engine import ReplenishmentEngine
from engines.risk_engine import RiskEngine
from services.context_engine import ContextEngine


class InsufficientDataError(Exception):
    """Raised when the required workbook inputs are not available."""


class RecommendationEngine:
    def __init__(
        self,
        context_engine: ContextEngine | None = None,
        replenishment_engine: ReplenishmentEngine | None = None,
        growth_engine: GrowthEngine | None = None,
        risk_engine: RiskEngine | None = None,
        price_trend_engine: PriceTrendEngine | None = None,
    ) -> None:
        self.context_engine = context_engine or ContextEngine()
        self.replenishment_engine = replenishment_engine or ReplenishmentEngine()
        self.growth_engine = growth_engine or GrowthEngine()
        self.risk_engine = risk_engine or RiskEngine()
        self.price_trend_engine = price_trend_engine or PriceTrendEngine()

    def generate_session_recommendations(
        self,
        workbook: dict[str, pd.DataFrame],
        session_id: str,
        context_override: dict[str, Any] | None = None,
        clear_context_keys: set[str] | None = None,
    ) -> dict[str, Any]:
        self._validate_workbook(workbook)
        context = self.context_engine.build_context(workbook, session_id)
        if clear_context_keys:
            for key in clear_context_keys:
                context[key] = None
        if context_override:
            context = self._merge_context_override(context, context_override)
        customer_id = context["CustomerId"]

        replenishment = self.replenishment_engine.generate_recommendations(workbook, customer_id, context)
        replenishment = self.price_trend_engine.enrich_recommendations(replenishment, workbook)
        growth = self.growth_engine.generate_opportunities(workbook, customer_id, context)
        growth = self.price_trend_engine.enrich_recommendations(growth, workbook)
        risks = self.risk_engine.generate_risks(workbook, customer_id)
        procurement_plan, remaining_budget = self._build_procurement_plan(
            replenishment=replenishment,
            growth=growth,
            budget=context.get("Budget"),
        )

        return {
            "session_id": session_id,
            "customer_id": customer_id,
            "context": context,
            "replenishment": replenishment,
            "growth": growth,
            "risks": risks,
            "procurement_plan": procurement_plan,
            "remaining_budget": remaining_budget,
        }

    @staticmethod
    def _merge_context_override(
        base_context: dict[str, Any],
        context_override: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(base_context)
        for key, value in context_override.items():
            if value is None or value == "":
                continue
            merged[key] = value
        return merged

    @staticmethod
    def _validate_workbook(workbook: dict[str, pd.DataFrame]) -> None:
        required = ["Customer", "Product", "OrderHistory", "Inventory", "IndustryTrend", "ConversationContext"]
        missing = [name for name in required if name not in workbook or workbook[name] is None]
        if missing:
            raise InsufficientDataError(f"Insufficient Data: missing sheets {', '.join(missing)}")
        if workbook["OrderHistory"].empty:
            raise InsufficientDataError("Insufficient Data: no order history.")
        if workbook["Inventory"].empty:
            raise InsufficientDataError("Insufficient Data: no inventory.")
        if workbook["Product"].empty:
            raise InsufficientDataError("Insufficient Data: missing product data.")
        if workbook["IndustryTrend"].empty:
            raise InsufficientDataError("Insufficient Data: missing industry data.")

    @staticmethod
    def _build_procurement_plan(
        replenishment: list[dict[str, Any]],
        growth: list[dict[str, Any]],
        budget: float | None,
    ) -> tuple[list[dict[str, Any]], float | None]:
        plan: list[dict[str, Any]] = []
        growth_trials = [
            item for item in growth
            if item.get("priority") == "Trial Buy" and item["score"] >= 60
        ]
        candidates = [
            RecommendationEngine._with_allocation_tier(item)
            for item in replenishment + growth_trials
        ]
        candidates.sort(
            key=lambda item: (
                item["allocation_tier"],
                -item["score"],
                item["estimated_cost"],
                item["product"],
            )
        )

        if budget is None:
            for candidate in candidates:
                quantity = max(int(candidate.get("quantity", 0) or 0), 1)
                estimated_cost = float(candidate.get("estimated_cost", 0.0))
                unit_cost = float(candidate.get("unit_cost") or 0.0)
                if unit_cost <= 0 and quantity > 0:
                    unit_cost = estimated_cost / quantity if estimated_cost > 0 else 0.0
                if estimated_cost <= 0 and unit_cost > 0:
                    estimated_cost = round(quantity * unit_cost, 2)
                if estimated_cost <= 0:
                    continue

                plan.append(
                    {
                        "product": candidate["product"],
                        "product_id": candidate["product_id"],
                        "quantity": quantity,
                        "unit": candidate.get("unit", ""),
                        "estimated_cost": round(estimated_cost, 2),
                        "remaining_budget": None,
                        "recommendation_strength": candidate["recommendation_strength"],
                        "priority": candidate.get("priority") or candidate["recommendation_strength"],
                        "why": candidate.get("why", []),
                        "coverage_days": candidate.get("coverage_days"),
                        "score": candidate.get("score"),
                        "price_trend": candidate.get("price_trend"),
                        "unit_cost": unit_cost,
                        "product_type": candidate.get("product_type"),
                        "allocation_tier": candidate.get("allocation_tier"),
                        "action": candidate.get("action"),
                    }
                )
            return plan, None

        remaining_budget = float(budget)

        for candidate in candidates:
            unit_cost = 0.0
            quantity = candidate.get("quantity", 0)
            estimated_cost = float(candidate.get("estimated_cost", 0.0))
            if quantity > 0:
                unit_cost = estimated_cost / quantity if quantity else 0.0
            else:
                quantity = 1
                unit_cost = candidate.get("estimated_cost", 0.0)
                estimated_cost = unit_cost

            if unit_cost <= 0:
                continue
            affordable_qty = int(remaining_budget // unit_cost)
            if affordable_qty <= 0:
                continue
            final_qty = min(quantity, affordable_qty)
            final_cost = round(final_qty * unit_cost, 2)
            remaining_budget = round(remaining_budget - final_cost, 2)

            plan.append(
                {
                    "product": candidate["product"],
                    "product_id": candidate["product_id"],
                    "quantity": final_qty,
                    "unit": candidate.get("unit", ""),
                    "estimated_cost": final_cost,
                    "remaining_budget": remaining_budget,
                    "recommendation_strength": candidate["recommendation_strength"],
                    "priority": candidate.get("priority") or candidate["recommendation_strength"],
                    "why": candidate.get("why", []),
                    "coverage_days": candidate.get("coverage_days"),
                    "score": candidate.get("score"),
                    "price_trend": candidate.get("price_trend"),
                    "unit_cost": candidate.get("unit_cost"),
                    "product_type": candidate.get("product_type"),
                    "allocation_tier": candidate.get("allocation_tier"),
                    "action": candidate.get("action"),
                }
            )

        return plan, remaining_budget

    @staticmethod
    def _with_allocation_tier(candidate: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(candidate)
        price_signal = (candidate.get("price_trend") or {}).get("price_signal")
        priority = candidate.get("priority") or candidate.get("recommendation_strength")
        coverage_days = candidate.get("coverage_days")
        strength = candidate.get("recommendation_strength", "")

        if priority == "Trial Buy":
            tier = 3
            action = "Trial Buy"
        elif coverage_days is not None and coverage_days <= 3:
            tier = 1
            action = "Order Now"
        elif strength in {"Very High", "High"}:
            tier = 1
            action = "Order Now"
        elif price_signal == "Buy Now":
            tier = 2
            action = "Buy on Price Advantage"
        elif price_signal == "Wait":
            tier = 4
            action = "Monitor Price"
        else:
            tier = 2
            action = "Order This Week"

        enriched["allocation_tier"] = tier
        enriched["action"] = action
        return enriched
