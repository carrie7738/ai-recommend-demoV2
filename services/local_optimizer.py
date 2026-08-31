from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import pandas as pd


class LocalOptimizerError(ValueError):
    """Raised when private inputs cannot produce a deterministic purchase plan."""


@dataclass(frozen=True)
class OptimizerPolicy:
    """Initial V2 evaluation parameters; callers may replace them without changing logic."""

    coverage_period_days: int = 14
    demand_history_days: int = 90
    intensity_factors: dict[str, float] = field(
        default_factory=lambda: {"HIGH": 1.25, "MEDIUM": 1.0, "LOW": 0.75}
    )
    discovery_trial_sales_units: int = 1

    def __post_init__(self) -> None:
        if self.coverage_period_days <= 0:
            raise LocalOptimizerError("coverage_period_days must be positive.")
        if self.demand_history_days <= 0:
            raise LocalOptimizerError("demand_history_days must be positive.")
        if self.discovery_trial_sales_units <= 0:
            raise LocalOptimizerError("discovery_trial_sales_units must be positive.")
        if set(self.intensity_factors) != {"HIGH", "MEDIUM", "LOW"}:
            raise LocalOptimizerError("intensity_factors must define HIGH, MEDIUM, and LOW.")
        if any(value <= 0 for value in self.intensity_factors.values()):
            raise LocalOptimizerError("intensity_factors must be positive.")


class LocalOptimizer:
    """Convert qualitative AI decisions into executable quantities using private data."""

    REQUIRED_SHEETS = {
        "Customer",
        "Product",
        "OrderHistory",
        "Inventory",
        "SupplyAvailability",
        "EventConfig",
    }
    PRIORITY_ORDER = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}

    def __init__(self, policy: OptimizerPolicy | None = None) -> None:
        self.policy = policy or OptimizerPolicy()

    def optimize(
        self,
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        structured_intent: dict[str, Any],
        eligible_candidates: list[dict[str, Any]],
        ai_decision: dict[str, Any],
        as_of_date: Any,
    ) -> dict[str, Any]:
        self._validate_inputs(workbook, eligible_candidates, ai_decision)
        as_of = self._as_timestamp(as_of_date)
        candidates = {item["candidate_id"]: item for item in eligible_candidates}
        products = self._indexed_rows(workbook["Product"], "ProductId")
        supply = self._indexed_rows(workbook["SupplyAvailability"], "ProductId")
        decisions = sorted(
            (item for item in ai_decision["candidate_decisions"] if item["recommended"]),
            key=lambda item: (
                self.PRIORITY_ORDER[item["priority"]],
                item["candidate_id"],
            ),
        )

        budget = self._optional_non_negative_float(structured_intent.get("budget"), "budget")
        remaining_budget = budget
        plan: list[dict[str, Any]] = []
        unallocated: list[dict[str, str]] = []

        for decision in decisions:
            candidate_id = decision["candidate_id"]
            candidate = candidates[candidate_id]
            product = products.get(candidate_id)
            if product is None:
                raise LocalOptimizerError(f"Missing Product row for {candidate_id}.")

            sales_unit = self._positive_int(candidate.get("sales_unit"), "sales_unit")
            available_stock = self._non_negative_float(
                (supply.get(candidate_id) or {}).get(
                    "AvailableStock", candidate.get("available_stock")
                ),
                "available_stock",
            )
            unit_cost = self._non_negative_float(product.get("AvgCost"), "AvgCost")
            current_stock = self._current_stock(
                workbook["Inventory"], customer_id, candidate_id, as_of
            )
            baseline_source, baseline_quantity = self._demand_baseline(
                workbook,
                customer_id,
                candidate_id,
                structured_intent,
                candidate,
                as_of,
                sales_unit,
            )
            base_quantity = max(baseline_quantity - current_stock, 0.0)
            intensity = decision["replenishment_intensity"]
            requested_quantity = base_quantity * self.policy.intensity_factors[intensity]
            desired_quantity, adjustments = self._apply_supply_constraints(
                requested_quantity,
                sales_unit,
                available_stock,
            )

            if desired_quantity <= 0:
                unallocated.append({
                    "candidate_id": candidate_id,
                    "reason": "NO_EXECUTABLE_QUANTITY",
                })
                continue

            final_quantity = desired_quantity
            if remaining_budget is not None:
                final_quantity = self._fit_budget(
                    desired_quantity,
                    sales_unit,
                    available_stock,
                    unit_cost,
                    remaining_budget,
                )
                if final_quantity < desired_quantity:
                    adjustments.append("BUDGET_CAPPED")
                if final_quantity <= 0:
                    unallocated.append({
                        "candidate_id": candidate_id,
                        "reason": "BUDGET_CONFLICT",
                    })
                    continue

            estimated_cost = round(final_quantity * unit_cost, 2)
            if remaining_budget is not None:
                remaining_budget = round(max(remaining_budget - estimated_cost, 0.0), 2)
            plan.append({
                "candidate_id": candidate_id,
                "product_name": str(product.get("ProductName") or candidate.get("product_name") or ""),
                "recommendation_type": decision["recommendation_type"],
                "priority": decision["priority"],
                "replenishment_intensity": intensity,
                "baseline_source": baseline_source,
                "final_qty": final_quantity,
                "sales_unit": sales_unit,
                "unit": str(product.get("Unit") or ""),
                "unit_cost": round(unit_cost, 2),
                "estimated_cost": estimated_cost,
                "constraint_adjustments": adjustments,
                "decision_signals": list(decision["decision_signals"]),
            })

        return {
            "purchase_plan": plan,
            "unallocated_candidates": unallocated,
            "total_cost": round(sum(item["estimated_cost"] for item in plan), 2),
            "remaining_budget": remaining_budget,
            "evaluation_parameters": {
                "coverage_period_days": self.policy.coverage_period_days,
                "demand_history_days": self.policy.demand_history_days,
                "intensity_factors": dict(self.policy.intensity_factors),
                "discovery_trial_sales_units": self.policy.discovery_trial_sales_units,
            },
        }

    def _demand_baseline(
        self,
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        candidate_id: str,
        structured_intent: dict[str, Any],
        candidate: dict[str, Any],
        as_of: pd.Timestamp,
        sales_unit: int,
    ) -> tuple[str, float]:
        if candidate.get("recommendation_type") == "DISCOVERY":
            return (
                "DISCOVERY_TRIAL",
                float(sales_unit * self.policy.discovery_trial_sales_units),
            )

        occasion = str(structured_intent.get("occasion") or "NONE").upper()
        preferred_source = str(
            (candidate.get("features") or {}).get("baseline_source") or "NONE"
        ).upper()
        if occasion != "NONE" and preferred_source in {"STORE_EVENT", "PEER_EVENT"}:
            event_quantity = self._event_baseline(
                workbook,
                customer_id,
                candidate_id,
                occasion,
                as_of,
                preferred_source,
            )
            if event_quantity is not None:
                return preferred_source, event_quantity
        return "RECENT_STORE", self._recent_store_baseline(
            workbook["OrderHistory"], customer_id, candidate_id, as_of
        )

    def _recent_store_baseline(
        self,
        orders: pd.DataFrame,
        customer_id: str,
        candidate_id: str,
        as_of: pd.Timestamp,
    ) -> float:
        prepared = orders.copy()
        prepared["OrderDate"] = pd.to_datetime(prepared["OrderDate"], errors="coerce")
        cutoff = as_of - pd.Timedelta(days=self.policy.demand_history_days)
        rows = prepared.loc[
            (prepared["CustomerId"].astype(str) == str(customer_id))
            & (prepared["ProductId"].astype(str) == candidate_id)
            & prepared["OrderDate"].notna()
            & (prepared["OrderDate"] <= as_of)
            & (prepared["OrderDate"] >= cutoff)
        ]
        historical_demand = float(
            pd.to_numeric(rows.get("Quantity"), errors="coerce").fillna(0).sum()
        )
        average_daily_demand = historical_demand / self.policy.demand_history_days
        return average_daily_demand * self.policy.coverage_period_days

    @staticmethod
    def _event_baseline(
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        candidate_id: str,
        occasion: str,
        as_of: pd.Timestamp,
        source: str,
    ) -> float | None:
        events = workbook["EventConfig"].copy()
        events["EventWindowStart"] = pd.to_datetime(events["EventWindowStart"], errors="coerce")
        events["EventWindowEnd"] = pd.to_datetime(events["EventWindowEnd"], errors="coerce")
        current = events.loc[
            events["EventName"].astype(str).str.upper().str.contains(occasion, regex=False)
            & (events["EventWindowStart"] <= as_of)
            & (events["EventWindowEnd"] >= as_of)
        ]
        if current.empty:
            return None
        comparable_id = current.iloc[0].get("ComparableEventId")
        if pd.isna(comparable_id) or not str(comparable_id).strip():
            return None

        orders = workbook["OrderHistory"].copy()
        rows = orders.loc[
            (orders["ProductId"].astype(str) == candidate_id)
            & (orders["EventId"].astype(str) == str(comparable_id))
        ].copy()
        rows["Quantity"] = pd.to_numeric(rows["Quantity"], errors="coerce").fillna(0)
        if source == "STORE_EVENT":
            store_rows = rows.loc[rows["CustomerId"].astype(str) == str(customer_id)]
            return float(store_rows["Quantity"].sum()) if not store_rows.empty else None

        customers = workbook["Customer"]
        target = customers.loc[customers["CustomerId"].astype(str) == str(customer_id)]
        if target.empty:
            return None
        industry = str(target.iloc[0].get("Industry") or "").casefold()
        peer_ids = set(customers.loc[
            (customers["Industry"].astype(str).str.casefold() == industry)
            & (customers["CustomerId"].astype(str) != str(customer_id)),
            "CustomerId",
        ].astype(str))
        peer_rows = rows.loc[rows["CustomerId"].astype(str).isin(peer_ids)]
        if peer_rows.empty:
            return None
        per_store = peer_rows.groupby(peer_rows["CustomerId"].astype(str))["Quantity"].sum()
        return float(per_store.mean())

    @staticmethod
    def _current_stock(
        inventory: pd.DataFrame,
        customer_id: str,
        candidate_id: str,
        as_of: pd.Timestamp,
    ) -> float:
        prepared = inventory.copy()
        prepared["LastUpdated"] = pd.to_datetime(prepared["LastUpdated"], errors="coerce")
        rows = prepared.loc[
            (prepared["CustomerId"].astype(str) == str(customer_id))
            & (prepared["ProductId"].astype(str) == candidate_id)
            & prepared["LastUpdated"].notna()
            & (prepared["LastUpdated"] <= as_of)
        ].sort_values("LastUpdated")
        if rows.empty:
            return 0.0
        value = pd.to_numeric(pd.Series([rows.iloc[-1].get("CurrentStock")]), errors="coerce").iloc[0]
        return max(float(value), 0.0) if pd.notna(value) else 0.0

    @staticmethod
    def _apply_supply_constraints(
        requested_quantity: float,
        sales_unit: int,
        available_stock: float,
    ) -> tuple[int, list[str]]:
        if requested_quantity <= 0 or available_stock <= 0:
            return 0, []
        adjustments: list[str] = []
        if available_stock < sales_unit:
            quantity = int(math.floor(available_stock))
            if quantity > 0:
                adjustments.append("TAIL_STOCK_EXCEPTION")
            return quantity, adjustments

        rounded = int(math.ceil(requested_quantity / sales_unit) * sales_unit)
        if not math.isclose(rounded, requested_quantity):
            adjustments.append("SALES_UNIT_ROUNDED")
        supply_cap = int(math.floor(available_stock / sales_unit) * sales_unit)
        quantity = min(rounded, supply_cap)
        if quantity < rounded:
            adjustments.append("AVAILABLE_STOCK_CAPPED")
        return quantity, adjustments

    @staticmethod
    def _fit_budget(
        desired_quantity: int,
        sales_unit: int,
        available_stock: float,
        unit_cost: float,
        remaining_budget: float,
    ) -> int:
        if unit_cost <= 0:
            return desired_quantity
        affordable = int(math.floor(remaining_budget / unit_cost))
        if available_stock < sales_unit:
            return desired_quantity if desired_quantity <= affordable else 0
        return min(desired_quantity, int(math.floor(affordable / sales_unit) * sales_unit))

    @classmethod
    def _validate_inputs(
        cls,
        workbook: dict[str, pd.DataFrame],
        candidates: Any,
        decision: Any,
    ) -> None:
        missing = sorted(cls.REQUIRED_SHEETS - set(workbook))
        if missing:
            raise LocalOptimizerError(f"Missing optimizer sheets: {', '.join(missing)}")
        if not isinstance(candidates, list):
            raise LocalOptimizerError("eligible_candidates must be a list.")
        if not isinstance(decision, dict) or not isinstance(decision.get("candidate_decisions"), list):
            raise LocalOptimizerError("ai_decision must contain candidate_decisions.")
        candidate_ids = {item.get("candidate_id") for item in candidates if isinstance(item, dict)}
        unknown = sorted({
            item.get("candidate_id")
            for item in decision["candidate_decisions"]
            if isinstance(item, dict) and item.get("candidate_id") not in candidate_ids
        })
        if unknown:
            raise LocalOptimizerError(f"AI decision contains unknown candidates: {unknown}.")

    @staticmethod
    def _indexed_rows(frame: pd.DataFrame, key: str) -> dict[str, dict[str, Any]]:
        return {
            str(row[key]): row.to_dict()
            for _, row in frame.drop_duplicates(subset=[key], keep="last").iterrows()
            if pd.notna(row.get(key))
        }

    @staticmethod
    def _as_timestamp(value: Any) -> pd.Timestamp:
        parsed = pd.to_datetime(value, errors="coerce")
        if pd.isna(parsed):
            raise LocalOptimizerError(f"Invalid as_of_date: {value!r}")
        return pd.Timestamp(parsed).normalize()

    @staticmethod
    def _positive_int(value: Any, field_name: str) -> int:
        try:
            parsed = int(float(value))
        except (TypeError, ValueError):
            raise LocalOptimizerError(f"{field_name} must be a positive integer.") from None
        if parsed <= 0:
            raise LocalOptimizerError(f"{field_name} must be a positive integer.")
        return parsed

    @staticmethod
    def _non_negative_float(value: Any, field_name: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            raise LocalOptimizerError(f"{field_name} must be a non-negative number.") from None
        if not math.isfinite(parsed) or parsed < 0:
            raise LocalOptimizerError(f"{field_name} must be a non-negative number.")
        return parsed

    @classmethod
    def _optional_non_negative_float(cls, value: Any, field_name: str) -> float | None:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return None
        return cls._non_negative_float(value, field_name)
