from __future__ import annotations

import math
from typing import Any

import pandas as pd

from engines.growth_engine import GrowthEngine
from engines.price_trend_engine import PriceTrendEngine
from engines.replenishment_engine import MEDIUM_SCORE_THRESHOLD, ReplenishmentEngine
from engines.risk_engine import RiskEngine
from engines.scoring_utils import HIGH_STRENGTH_SCORE
from services.context_engine import ContextEngine
from services.store_resolver import StoreResolver


class InsufficientDataError(Exception):
    """Raised when the required workbook inputs are not available."""


class RecommendationEngine:
    STORE_LEVEL_FACTORS = {
        "bronze": 0.85,
        "silver": 1.00,
        "gold": 1.10,
        "platinum": 1.20,
    }
    NEW_STORE_TRIAL_FACTOR = 0.60
    BUDGET_MIN_UTILIZATION = 0.85
    BUDGET_TARGET_UTILIZATION = 0.90
    BUDGET_SOFT_CAP_UTILIZATION = 0.95
    MAX_TOP_UP_MULTIPLIER = 1.50

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
        trusted_store_context = StoreResolver().build_store_context(workbook, customer_id)
        context["StoreContext"] = trusted_store_context
        context.setdefault("StoreConsiderations", [])

        replenishment = self.replenishment_engine.generate_recommendations(workbook, customer_id, context)
        replenishment_candidates = self.replenishment_engine.generate_candidate_pool(
            workbook,
            customer_id,
            context,
        )
        replenishment = self.price_trend_engine.enrich_recommendations(replenishment, workbook)
        replenishment_candidates = self.price_trend_engine.enrich_recommendations(
            replenishment_candidates,
            workbook,
        )
        replenishment = self._apply_store_adjustments(replenishment, trusted_store_context)
        replenishment_candidates = self._apply_store_adjustments(
            replenishment_candidates,
            trusted_store_context,
        )
        growth = self.growth_engine.generate_opportunities(workbook, customer_id, context)
        growth = self.price_trend_engine.enrich_recommendations(growth, workbook)
        growth = self._apply_store_adjustments(growth, trusted_store_context)
        risks = self.risk_engine.generate_risks(workbook, customer_id)
        procurement_plan, remaining_budget = self._build_procurement_plan(
            replenishment=replenishment,
            growth=growth,
            budget=context.get("Budget"),
            replenishment_candidates=replenishment_candidates,
        )
        context["BudgetUtilization"] = self._budget_utilization_summary(
            procurement_plan,
            context.get("Budget"),
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

    @classmethod
    def _apply_store_adjustments(
        cls,
        recommendations: list[dict[str, Any]],
        store_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        level = str(store_context.get("StoreLevel") or "Silver").casefold()
        stage = str(store_context.get("CustomerStage") or "Mature").casefold()
        level_factor = cls.STORE_LEVEL_FACTORS.get(level, 1.0)

        adjusted_recommendations: list[dict[str, Any]] = []
        for item in recommendations:
            adjusted = dict(item)
            original_quantity = max(int(round(float(item.get("quantity", 0) or 0))), 1)
            is_trial = item.get("priority") == "Trial Buy"
            trial_factor = cls.NEW_STORE_TRIAL_FACTOR if is_trial and stage == "new" else 1.0
            combined_factor = level_factor * trial_factor
            adjusted_quantity = max(1, math.ceil(original_quantity * combined_factor))
            unit_cost = float(item.get("unit_cost") or 0.0)
            if unit_cost <= 0:
                estimated_cost = float(item.get("estimated_cost") or 0.0)
                unit_cost = estimated_cost / original_quantity if estimated_cost > 0 else 0.0

            adjusted["quantity"] = adjusted_quantity
            adjusted["unit_cost"] = round(unit_cost, 2)
            adjusted["estimated_cost"] = round(adjusted_quantity * unit_cost, 2)
            adjusted["store_adjustment"] = {
                "original_quantity": original_quantity,
                "adjusted_quantity": adjusted_quantity,
                "store_level_factor": level_factor,
                "trial_factor": trial_factor,
                "combined_factor": combined_factor,
                "reason": cls._store_adjustment_reason(level, stage, is_trial),
            }
            adjusted_recommendations.append(adjusted)
        return adjusted_recommendations

    @staticmethod
    def _store_adjustment_reason(level: str, stage: str, is_trial: bool) -> str:
        readable_level = level.title()
        if is_trial and stage == "new":
            return f"{readable_level} store scale and new-store trial controls adjusted the quantity."
        return f"{readable_level} store scale adjusted the quantity."

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
        replenishment_candidates: list[dict[str, Any]] | None = None,
    ) -> tuple[list[dict[str, Any]], float | None]:
        plan: list[dict[str, Any]] = []
        growth_trials = [
            item for item in growth
            if item.get("priority") == "Trial Buy" and item["score"] >= 60
        ]
        core_candidates = [
            RecommendationEngine._with_allocation_tier(item)
            for item in replenishment + growth_trials
        ]
        core_candidates.sort(
            key=lambda item: (
                item["allocation_tier"],
                -item["score"],
                item["estimated_cost"],
                item["product"],
            )
        )

        if budget is None:
            for candidate in core_candidates:
                item = RecommendationEngine._plan_item(
                    candidate,
                    quantity=max(int(candidate.get("quantity", 0) or 0), 1),
                    remaining_budget=None,
                    budget_allocation="Core Replenishment",
                )
                if item:
                    plan.append(item)
            return plan, None

        remaining_budget = float(budget)
        for candidate in core_candidates:
            item, remaining_budget = RecommendationEngine._allocate_candidate(
                candidate,
                remaining_budget,
                budget_allocation="Core Replenishment",
            )
            if item:
                plan.append(item)

        soft_cap = float(budget) * RecommendationEngine.BUDGET_SOFT_CAP_UTILIZATION
        target_spend = float(budget) * RecommendationEngine.BUDGET_TARGET_UTILIZATION
        current_spend = RecommendationEngine._plan_total(plan)
        selected_product_ids = {item["product_id"] for item in plan}
        expansion_candidates = [
            RecommendationEngine._with_allocation_tier(candidate)
            for candidate in (replenishment_candidates or [])
            if candidate.get("product_id") not in selected_product_ids
            and float(candidate.get("score", 0.0)) >= MEDIUM_SCORE_THRESHOLD
            and RecommendationEngine._is_safe_expansion_candidate(candidate)
        ]
        expansion_candidates.sort(
            key=lambda item: (
                item["allocation_tier"],
                -item["score"],
                item["estimated_cost"],
                item["product"],
            )
        )
        for candidate in expansion_candidates:
            if current_spend >= target_spend:
                break
            allowed_budget = min(remaining_budget, max(soft_cap - current_spend, 0.0))
            item, remaining_budget = RecommendationEngine._allocate_candidate(
                candidate,
                remaining_budget,
                budget_allocation="Portfolio Expansion",
                budget_cap=allowed_budget,
            )
            if item:
                plan.append(item)
                current_spend = RecommendationEngine._plan_total(plan)

        if current_spend < target_spend:
            remaining_budget = RecommendationEngine._top_up_safe_products(
                plan,
                remaining_budget,
                target_spend,
                soft_cap,
            )

        return plan, remaining_budget

    @staticmethod
    def _plan_item(
        candidate: dict[str, Any],
        quantity: int,
        remaining_budget: float | None,
        budget_allocation: str,
    ) -> dict[str, Any] | None:
        unit_cost = RecommendationEngine._candidate_unit_cost(candidate)
        if unit_cost <= 0 or quantity <= 0:
            return None

        return {
            "product": candidate["product"],
            "product_id": candidate["product_id"],
            "quantity": quantity,
            "base_quantity": quantity,
            "unit": candidate.get("unit", ""),
            "estimated_cost": round(quantity * unit_cost, 2),
            "remaining_budget": remaining_budget,
            "recommendation_strength": candidate["recommendation_strength"],
            "priority": candidate.get("priority") or candidate["recommendation_strength"],
            "why": candidate.get("why", []),
            "coverage_days": candidate.get("coverage_days"),
            "score": candidate.get("score"),
            "price_trend": candidate.get("price_trend"),
            "unit_cost": round(unit_cost, 2),
            "product_type": candidate.get("product_type"),
            "allocation_tier": candidate.get("allocation_tier"),
            "action": candidate.get("action"),
            "store_adjustment": candidate.get("store_adjustment"),
            "historical_avg_qty": candidate.get("historical_avg_qty"),
            "avg_daily_demand": candidate.get("avg_daily_demand"),
            "budget_allocation": budget_allocation,
        }

    @staticmethod
    def _allocate_candidate(
        candidate: dict[str, Any],
        remaining_budget: float,
        budget_allocation: str,
        budget_cap: float | None = None,
    ) -> tuple[dict[str, Any] | None, float]:
        unit_cost = RecommendationEngine._candidate_unit_cost(candidate)
        if unit_cost <= 0:
            return None, remaining_budget
        quantity = max(int(candidate.get("quantity", 0) or 0), 1)
        available = min(remaining_budget, budget_cap) if budget_cap is not None else remaining_budget
        affordable_quantity = int(available // unit_cost)
        if affordable_quantity <= 0:
            return None, remaining_budget
        item = RecommendationEngine._plan_item(
            candidate,
            quantity=min(quantity, affordable_quantity),
            remaining_budget=None,
            budget_allocation=budget_allocation,
        )
        if item is None:
            return None, remaining_budget
        new_remaining_budget = round(remaining_budget - item["estimated_cost"], 2)
        item["remaining_budget"] = new_remaining_budget
        return item, new_remaining_budget

    @staticmethod
    def _candidate_unit_cost(candidate: dict[str, Any]) -> float:
        unit_cost = float(candidate.get("unit_cost") or 0.0)
        if unit_cost > 0:
            return unit_cost
        estimated_cost = float(candidate.get("estimated_cost") or 0.0)
        suggested_quantity = max(int(candidate.get("quantity", 0) or 0), 1)
        return estimated_cost / suggested_quantity if estimated_cost > 0 else 0.0

    @staticmethod
    def _is_safe_expansion_candidate(candidate: dict[str, Any]) -> bool:
        price_signal = (candidate.get("price_trend") or {}).get("price_signal")
        coverage_days = candidate.get("coverage_days")
        return not (price_signal == "Wait" and coverage_days is not None and coverage_days > 7)

    @classmethod
    def _top_up_safe_products(
        cls,
        plan: list[dict[str, Any]],
        remaining_budget: float,
        target_spend: float,
        soft_cap: float,
    ) -> float:
        eligible_items = sorted(
            (
                item for item in plan
                if item.get("priority") != "Trial Buy"
                and item.get("product_type") != "Fresh"
                and (item.get("price_trend") or {}).get("price_signal") != "Wait"
                and float(item.get("historical_avg_qty") or 0.0) > 0
            ),
            key=lambda item: (item.get("allocation_tier", 9), -float(item.get("score") or 0.0), item["product"]),
        )
        for item in eligible_items:
            current_spend = cls._plan_total(plan)
            if current_spend >= target_spend:
                break
            unit_cost = float(item.get("unit_cost") or 0.0)
            base_quantity = int(item.get("base_quantity") or item.get("quantity") or 0)
            maximum_quantity = max(base_quantity, math.floor(base_quantity * cls.MAX_TOP_UP_MULTIPLIER))
            additional_capacity = maximum_quantity - int(item.get("quantity") or 0)
            allowed_budget = min(remaining_budget, max(soft_cap - current_spend, 0.0))
            affordable_quantity = int(allowed_budget // unit_cost) if unit_cost > 0 else 0
            additional_quantity = min(additional_capacity, affordable_quantity)
            if additional_quantity <= 0:
                continue
            item["quantity"] += additional_quantity
            item["estimated_cost"] = round(item["quantity"] * unit_cost, 2)
            remaining_budget = round(remaining_budget - additional_quantity * unit_cost, 2)
            item["remaining_budget"] = remaining_budget
            item["budget_allocation"] = "Budget Top-up"
        return remaining_budget

    @staticmethod
    def _plan_total(plan: list[dict[str, Any]]) -> float:
        return round(sum(float(item.get("estimated_cost") or 0.0) for item in plan), 2)

    @classmethod
    def _budget_utilization_summary(
        cls,
        plan: list[dict[str, Any]],
        budget: float | None,
    ) -> dict[str, Any]:
        if budget is None or budget <= 0:
            return {"has_budget": False}
        total = cls._plan_total(plan)
        utilization = total / float(budget)
        return {
            "has_budget": True,
            "total_investment": total,
            "utilization": utilization,
            "is_optimized": cls.BUDGET_MIN_UTILIZATION <= utilization <= cls.BUDGET_SOFT_CAP_UTILIZATION,
            "is_held": utilization < cls.BUDGET_MIN_UTILIZATION,
        }

    @staticmethod
    def _with_allocation_tier(candidate: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(candidate)
        price_signal = (candidate.get("price_trend") or {}).get("price_signal")
        priority = candidate.get("priority") or candidate.get("recommendation_strength")
        coverage_days = candidate.get("coverage_days")

        if priority == "Trial Buy":
            tier = 3
            action = "Trial Buy"
        elif coverage_days is not None and coverage_days <= 3:
            tier = 1
            action = "Order Now"
        elif candidate.get("score", 0) >= HIGH_STRENGTH_SCORE:
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
