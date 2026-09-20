from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import pandas as pd

from services.runtime_trace import is_capturing, observed, record


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

    @observed("optimizer", "Optimizer")
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
        supply = self._supply_rows(workbook["SupplyAvailability"], as_of)
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
        capturing = is_capturing()

        for decision in decisions:
            candidate_id = decision["candidate_id"]
            candidate = candidates[candidate_id]
            trace_input: dict[str, Any] | None = None
            product = products.get(candidate_id)
            if product is None:
                if capturing:
                    record(
                        "optimizer",
                        "Optimizer",
                        input={"candidate_id": candidate_id},
                        status="failed",
                        operation="candidate_allocation",
                        reason="MISSING_PRODUCT",
                    )
                raise LocalOptimizerError(f"Missing Product row for {candidate_id}.")

            sales_unit = self._positive_int(candidate.get("sales_unit"), "sales_unit")
            available_stock = self._non_negative_float(
                (supply.get(candidate_id) or {}).get(
                    "AvailableStock", candidate.get("available_stock")
                ),
                "available_stock",
            )
            unit_cost = self._non_negative_float(product.get("AvgCost"), "AvgCost")
            stock_evidence: dict[str, Any] | None = {} if capturing else None
            current_stock = self._current_stock(
                workbook["Inventory"],
                customer_id,
                candidate_id,
                as_of,
                evidence=stock_evidence,
            )
            if current_stock is None:
                reason = "INVENTORY_UNAVAILABLE"
                unallocated.append({
                    "candidate_id": candidate_id,
                    "reason": reason,
                })
                if capturing:
                    trace_input = {
                        "candidate_id": candidate_id,
                        "decision": {
                            "recommendation_type": decision["recommendation_type"],
                            "priority": decision["priority"],
                            "replenishment_intensity": decision["replenishment_intensity"],
                            "decision_signals": list(decision["decision_signals"]),
                        },
                        "source_evidence": {
                            "Product": {
                                "lookup": {"ProductId": candidate_id},
                                "record": self._trace_record(
                                    product,
                                    ("ProductId", "ProductName", "AvgCost", "Unit", "SalesUnit"),
                                ),
                            },
                            "SupplyAvailability": {
                                "lookup": {"ProductId": candidate_id, "as_of_date": as_of},
                                "record": self._trace_record(
                                    supply.get(candidate_id),
                                    ("ProductId", "AvailableStock", "LastUpdated"),
                                ),
                                "evidence_status": "available" if candidate_id in supply else "missing",
                            },
                            "Inventory": {
                                "lookup": {
                                    "CustomerId": str(customer_id),
                                    "ProductId": candidate_id,
                                    "as_of_date": as_of,
                                },
                                "current_stock": None,
                                "calculation": stock_evidence,
                            },
                        },
                        "quantity_calculation": {
                            "sales_unit": sales_unit,
                            "available_stock": available_stock,
                            "unit_cost": unit_cost,
                            "current_stock": None,
                        },
                        "result": {
                            "status": "unallocated",
                            "reason": reason,
                            "final_quantity": 0,
                            "final_qty": 0,
                            "unallocated_reason": reason,
                        },
                    }
                    record(
                        "optimizer",
                        "Optimizer",
                        input=trace_input,
                        output=trace_input["result"],
                        status="skipped",
                        operation="candidate_allocation",
                        reason=reason,
                    )
                continue
            baseline_evidence: dict[str, Any] | None = {} if capturing else None
            baseline_source, baseline_quantity = self._demand_baseline(
                workbook,
                customer_id,
                candidate_id,
                structured_intent,
                candidate,
                as_of,
                sales_unit,
                evidence=baseline_evidence,
            )
            base_quantity = max(baseline_quantity - current_stock, 0.0)
            intensity = decision["replenishment_intensity"]
            requested_quantity = base_quantity * self.policy.intensity_factors[intensity]
            desired_quantity, adjustments = self._apply_supply_constraints(
                requested_quantity,
                sales_unit,
                available_stock,
            )

            budget_evidence: dict[str, Any] | None = None
            if capturing:
                trace_input = {
                    "candidate_id": candidate_id,
                    "decision": {
                        "recommendation_type": decision["recommendation_type"],
                        "priority": decision["priority"],
                        "replenishment_intensity": intensity,
                        "decision_signals": list(decision["decision_signals"]),
                    },
                    "source_evidence": {
                        "Product": {
                            "lookup": {"ProductId": candidate_id},
                            "record": self._trace_record(
                                product,
                                ("ProductId", "ProductName", "AvgCost", "Unit", "SalesUnit"),
                            ),
                        },
                        "SupplyAvailability": {
                            "lookup": {"ProductId": candidate_id, "as_of_date": as_of},
                            "record": self._trace_record(
                                supply.get(candidate_id),
                                ("ProductId", "AvailableStock", "LastUpdated"),
                            ),
                            "evidence_status": "available" if candidate_id in supply else "missing",
                        },
                        "Inventory": {
                            "lookup": {
                                "CustomerId": str(customer_id),
                                "ProductId": candidate_id,
                                "as_of_date": as_of,
                            },
                            "current_stock": current_stock,
                            "calculation": stock_evidence,
                        },
                        "DemandBaseline": baseline_evidence,
                    },
                    "quantity_calculation": {
                        "sales_unit": sales_unit,
                        "available_stock": available_stock,
                        "unit_cost": unit_cost,
                        "current_stock": current_stock,
                        "baseline_source": baseline_source,
                        "baseline_quantity": baseline_quantity,
                        "base_quantity": base_quantity,
                        "intensity_factor": self.policy.intensity_factors[intensity],
                        "requested_quantity": requested_quantity,
                        "desired_quantity": desired_quantity,
                        "supply_adjustments": list(adjustments),
                    },
                    "policy": {
                        "coverage_period_days": self.policy.coverage_period_days,
                        "demand_history_days": self.policy.demand_history_days,
                        "intensity_factors": dict(self.policy.intensity_factors),
                        "discovery_trial_sales_units": self.policy.discovery_trial_sales_units,
                    },
                    "budget": {
                        "initial_budget": budget,
                        "remaining_before": remaining_budget,
                        "final_quantity_before_budget": desired_quantity,
                    },
                }
                trace_input.update({
                    "sales_unit": sales_unit,
                    "available_stock": available_stock,
                    "unit_cost": unit_cost,
                    "current_stock": current_stock,
                    "baseline_source": baseline_source,
                    "baseline_quantity": baseline_quantity,
                    "base_quantity": base_quantity,
                    "requested_quantity": requested_quantity,
                    "desired_quantity": desired_quantity,
                })

            if desired_quantity <= 0:
                unallocated.append({
                    "candidate_id": candidate_id,
                    "reason": "NO_EXECUTABLE_QUANTITY",
                })
                if trace_input is not None:
                    trace_input.update({
                        "final_quantity": 0,
                        "final_qty": 0,
                        "unallocated_reason": "NO_EXECUTABLE_QUANTITY",
                    })
                    trace_input["result"] = {
                        "status": "unallocated",
                        "reason": "NO_EXECUTABLE_QUANTITY",
                        "final_quantity": 0,
                        "final_qty": 0,
                        "unallocated_reason": "NO_EXECUTABLE_QUANTITY",
                        "adjustments": list(adjustments),
                    }
                    record(
                        "optimizer",
                        "Optimizer",
                        input=trace_input,
                        output=trace_input["result"],
                        operation="candidate_allocation",
                    )
                continue

            final_quantity = desired_quantity
            if remaining_budget is not None:
                budget_evidence = {} if capturing else None
                final_quantity = self._fit_budget(
                    desired_quantity,
                    sales_unit,
                    available_stock,
                    unit_cost,
                    remaining_budget,
                    evidence=budget_evidence,
                )
                if trace_input is not None:
                    trace_input["budget"]["fit"] = budget_evidence
                if final_quantity < desired_quantity:
                    adjustments.append("BUDGET_CAPPED")
                if final_quantity <= 0:
                    unallocated.append({
                        "candidate_id": candidate_id,
                        "reason": "BUDGET_CONFLICT",
                    })
                    if trace_input is not None:
                        trace_input["budget"].update({
                            "budget_applied": True,
                            "final_quantity_after_budget": 0,
                            "budget_adjustment": "BUDGET_CONFLICT",
                            "remaining_after": remaining_budget,
                        })
                        trace_input.update({
                            "final_quantity": 0,
                            "final_qty": 0,
                            "unallocated_reason": "BUDGET_CONFLICT",
                            "budget_adjustment": "BUDGET_CONFLICT",
                        })
                        trace_input["result"] = {
                            "status": "unallocated",
                            "reason": "BUDGET_CONFLICT",
                            "final_quantity": 0,
                            "final_qty": 0,
                            "unallocated_reason": "BUDGET_CONFLICT",
                            "adjustments": list(adjustments),
                        }
                        record(
                            "optimizer",
                            "Optimizer",
                            input=trace_input,
                            output=trace_input["result"],
                            operation="candidate_allocation",
                        )
                    continue

            estimated_cost = round(final_quantity * unit_cost, 2)
            remaining_before = remaining_budget
            if remaining_budget is not None:
                remaining_budget = round(max(remaining_budget - estimated_cost, 0.0), 2)
            if trace_input is not None:
                trace_input["budget"].update({
                    "budget_applied": remaining_before is not None,
                    "final_quantity_after_budget": final_quantity,
                    "budget_adjustment": (
                        "BUDGET_CAPPED" if final_quantity < desired_quantity else None
                    ),
                    "estimated_cost": estimated_cost,
                    "remaining_after": remaining_budget,
                })
                trace_input.update({
                    "final_quantity": final_quantity,
                    "final_qty": final_quantity,
                    "budget_adjustment": (
                        "BUDGET_CAPPED" if final_quantity < desired_quantity else None
                    ),
                })
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
            if trace_input is not None:
                trace_input["result"] = {
                    "status": "allocated",
                    "reason": None,
                    "final_quantity": final_quantity,
                    "final_qty": final_quantity,
                    "estimated_cost": estimated_cost,
                    "constraint_adjustments": list(adjustments),
                    "adjustments": list(adjustments),
                }
                record(
                    "optimizer",
                    "Optimizer",
                    input=trace_input,
                    output=trace_input["result"],
                    operation="candidate_allocation",
                )

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
        evidence: dict[str, Any] | None = None,
    ) -> tuple[str, float]:
        occasion = str(structured_intent.get("occasion") or "NONE").upper()
        preferred_source = str(
            (candidate.get("features") or {}).get("baseline_source") or "NONE"
        ).upper()
        if evidence is not None:
            evidence.update({
                "source": ["OrderHistory", "EventConfig", "Customer"],
                "occasion": occasion,
                "preferred_source": preferred_source,
                "recommendation_type": candidate.get("recommendation_type"),
                "candidate_source": candidate.get("candidate_source"),
            })
        if (
            candidate.get("recommendation_type") == "DISCOVERY"
            and candidate.get("candidate_source") == "USER_REQUESTED"
            and occasion != "NONE"
        ):
            if preferred_source in {"STORE_EVENT", "PEER_EVENT"}:
                event_quantity = self._event_baseline(
                    workbook,
                    customer_id,
                    candidate_id,
                    occasion,
                    as_of,
                    preferred_source,
                    evidence=evidence,
                )
                if event_quantity is not None:
                    if evidence is not None:
                        evidence.update({
                            "selected_source": preferred_source,
                            "baseline_quantity": event_quantity,
                            "evidence_status": "available",
                        })
                    return preferred_source, event_quantity
            if preferred_source == "RECENT_STORE":
                quantity = self._recent_store_baseline(
                    workbook["OrderHistory"],
                    customer_id,
                    candidate_id,
                    as_of,
                    evidence=evidence,
                )
                if evidence is not None:
                    evidence.update({
                        "selected_source": preferred_source,
                        "baseline_quantity": quantity,
                        "evidence_status": "available",
                    })
                return preferred_source, quantity

        if candidate.get("recommendation_type") == "DISCOVERY":
            quantity = float(sales_unit * self.policy.discovery_trial_sales_units)
            if evidence is not None:
                evidence.update({
                    "selected_source": "DISCOVERY_TRIAL",
                    "baseline_quantity": quantity,
                    "trial_sales_units": self.policy.discovery_trial_sales_units,
                    "evidence_status": "available",
                })
            return (
                "DISCOVERY_TRIAL",
                quantity,
            )

        if occasion != "NONE" and preferred_source in {"STORE_EVENT", "PEER_EVENT"}:
            event_quantity = self._event_baseline(
                workbook,
                customer_id,
                candidate_id,
                occasion,
                as_of,
                preferred_source,
                evidence=evidence,
            )
            if event_quantity is not None:
                if evidence is not None:
                    evidence.update({
                        "selected_source": preferred_source,
                        "baseline_quantity": event_quantity,
                        "evidence_status": "available",
                    })
                return preferred_source, event_quantity
        quantity = self._recent_store_baseline(
            workbook["OrderHistory"],
            customer_id,
            candidate_id,
            as_of,
            evidence=evidence,
        )
        if evidence is not None:
            evidence.update({
                "selected_source": "RECENT_STORE",
                "baseline_quantity": quantity,
                "evidence_status": "available",
            })
        return "RECENT_STORE", quantity

    def _recent_store_baseline(
        self,
        orders: pd.DataFrame,
        customer_id: str,
        candidate_id: str,
        as_of: pd.Timestamp,
        evidence: dict[str, Any] | None = None,
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
        quantity = average_daily_demand * self.policy.coverage_period_days
        if evidence is not None:
            evidence["recent_store_baseline"] = {
                "source": "OrderHistory",
                "filter": {
                    "CustomerId": str(customer_id),
                    "ProductId": candidate_id,
                    "OrderDate_gte": cutoff,
                    "OrderDate_lte": as_of,
                },
                "order_count": int(len(rows)),
                "records": self._trace_records(
                    rows,
                    ("OrderId", "OrderDate", "Quantity", "EventId"),
                ),
                "historical_demand": historical_demand,
                "demand_history_days": self.policy.demand_history_days,
                "average_daily_demand": average_daily_demand,
                "coverage_period_days": self.policy.coverage_period_days,
                "output": quantity,
                "evidence_status": "available" if not rows.empty else "missing",
            }
        return quantity

    @staticmethod
    def _event_baseline(
        workbook: dict[str, pd.DataFrame],
        customer_id: str,
        candidate_id: str,
        occasion: str,
        as_of: pd.Timestamp,
        source: str,
        evidence: dict[str, Any] | None = None,
    ) -> float | None:
        event_evidence: dict[str, Any] | None = None
        if evidence is not None:
            event_evidence = evidence["event_lookup"] = {
                "source": ["EventConfig", "OrderHistory", "Customer"],
                "occasion": occasion,
                "requested_source": source,
                "as_of_date": as_of,
            }
        events = workbook["EventConfig"].copy()
        events["EventWindowStart"] = pd.to_datetime(events["EventWindowStart"], errors="coerce")
        events["EventWindowEnd"] = pd.to_datetime(events["EventWindowEnd"], errors="coerce")
        current = events.loc[
            events["EventName"].astype(str).str.upper().str.contains(occasion, regex=False)
            & (events["EventWindowStart"] <= as_of)
            & (events["EventWindowEnd"] >= as_of)
        ]
        if event_evidence is not None:
            event_evidence["event_records"] = LocalOptimizer._trace_records(
                current,
                (
                    "EventId",
                    "EventName",
                    "EventType",
                    "EventWindowStart",
                    "EventWindowEnd",
                    "ComparableEventId",
                ),
            )
        if current.empty:
            if event_evidence is not None:
                event_evidence.update({
                    "evidence_status": "missing",
                    "missing_reason": "NO_ACTIVE_EVENT_RECORD",
                })
            return None
        comparable_id = current.iloc[0].get("ComparableEventId")
        if pd.isna(comparable_id) or not str(comparable_id).strip():
            if event_evidence is not None:
                event_evidence.update({
                    "evidence_status": "missing",
                    "missing_reason": "NO_COMPARABLE_EVENT_ID",
                })
            return None
        if event_evidence is not None:
            event_evidence["comparable_event_id"] = str(comparable_id)

        orders = workbook["OrderHistory"].copy()
        rows = orders.loc[
            (orders["ProductId"].astype(str) == candidate_id)
            & (orders["EventId"].astype(str) == str(comparable_id))
        ].copy()
        rows["Quantity"] = pd.to_numeric(rows["Quantity"], errors="coerce").fillna(0)
        if event_evidence is not None:
            event_evidence.update({
                "order_filter": {
                    "ProductId": candidate_id,
                    "EventId": str(comparable_id),
                },
                "order_count": int(len(rows)),
                "order_records": LocalOptimizer._trace_records(
                    rows,
                    ("OrderId", "CustomerId", "ProductId", "OrderDate", "Quantity", "EventId"),
                ),
            })
        if source == "STORE_EVENT":
            store_rows = rows.loc[rows["CustomerId"].astype(str) == str(customer_id)]
            if store_rows.empty:
                if event_evidence is not None:
                    event_evidence.update({
                        "selected_records": [],
                        "evidence_status": "missing",
                        "missing_reason": "NO_STORE_EVENT_ORDERS",
                    })
                return None
            quantity = float(store_rows["Quantity"].sum())
            if event_evidence is not None:
                event_evidence.update({
                    "selected_records": LocalOptimizer._trace_records(
                        store_rows,
                        ("OrderId", "CustomerId", "ProductId", "OrderDate", "Quantity", "EventId"),
                    ),
                    "baseline_quantity": quantity,
                    "evidence_status": "available",
                })
            return quantity

        customers = workbook["Customer"]
        target = customers.loc[customers["CustomerId"].astype(str) == str(customer_id)]
        if target.empty:
            if event_evidence is not None:
                event_evidence.update({
                    "evidence_status": "missing",
                    "missing_reason": "NO_CUSTOMER_RECORD",
                })
            return None
        industry = str(target.iloc[0].get("Industry") or "").casefold()
        peer_ids = set(customers.loc[
            (customers["Industry"].astype(str).str.casefold() == industry)
            & (customers["CustomerId"].astype(str) != str(customer_id)),
            "CustomerId",
        ].astype(str))
        peer_rows = rows.loc[rows["CustomerId"].astype(str).isin(peer_ids)]
        if peer_rows.empty:
            if event_evidence is not None:
                event_evidence.update({
                    "peer_customer_ids": sorted(peer_ids),
                    "selected_records": [],
                    "evidence_status": "missing",
                    "missing_reason": "NO_PEER_EVENT_ORDERS",
                })
            return None
        per_store = peer_rows.groupby(peer_rows["CustomerId"].astype(str))["Quantity"].sum()
        quantity = float(per_store.mean())
        if event_evidence is not None:
            event_evidence.update({
                "peer_customer_ids": sorted(peer_ids),
                "selected_records": LocalOptimizer._trace_records(
                    peer_rows,
                    ("OrderId", "CustomerId", "ProductId", "OrderDate", "Quantity", "EventId"),
                ),
                "peer_quantity_by_store": {
                    str(key): float(value) for key, value in per_store.items()
                },
                "baseline_quantity": quantity,
                "evidence_status": "available",
            })
        return quantity

    @staticmethod
    def _current_stock(
        inventory: pd.DataFrame,
        customer_id: str,
        candidate_id: str,
        as_of: pd.Timestamp,
        evidence: dict[str, Any] | None = None,
    ) -> float | None:
        prepared = inventory.copy()
        prepared["LastUpdated"] = pd.to_datetime(prepared["LastUpdated"], errors="coerce")
        rows = prepared.loc[
            (prepared["CustomerId"].astype(str) == str(customer_id))
            & (prepared["ProductId"].astype(str) == candidate_id)
            & prepared["LastUpdated"].notna()
            & (prepared["LastUpdated"] <= as_of)
        ].sort_values("LastUpdated")
        if rows.empty:
            if evidence is not None:
                evidence.update({
                    "source": "Inventory",
                    "records": [],
                    "evidence_status": "missing",
                    "missing_reason": "NO_INVENTORY_RECORD_AS_OF_DATE",
                })
            return None
        raw_value = rows.iloc[-1].get("CurrentStock")
        value = pd.to_numeric(pd.Series([raw_value]), errors="coerce").iloc[0]
        try:
            result = float(value)
        except (TypeError, ValueError):
            result = math.nan
        if not math.isfinite(result) or result < 0:
            if evidence is not None:
                evidence.update({
                    "source": "Inventory",
                    "records": LocalOptimizer._trace_records(
                        rows.tail(1),
                        ("CustomerId", "ProductId", "CurrentStock", "LastUpdated"),
                    ),
                    "raw_current_stock": raw_value,
                    "current_stock": None,
                    "evidence_status": "missing",
                    "missing_reason": "INVALID_CURRENT_STOCK",
                })
            return None
        if evidence is not None:
            evidence.update({
                "source": "Inventory",
                "records": LocalOptimizer._trace_records(
                    rows.tail(1),
                    ("CustomerId", "ProductId", "CurrentStock", "LastUpdated"),
                ),
                "raw_current_stock": value,
                "current_stock": result,
                "evidence_status": "available",
            })
        return result

    @classmethod
    def _supply_rows(
        cls,
        supply: pd.DataFrame,
        as_of: pd.Timestamp,
    ) -> dict[str, dict[str, Any]]:
        prepared = supply.copy()
        if "LastUpdated" in prepared.columns:
            prepared["LastUpdated"] = pd.to_datetime(prepared["LastUpdated"], errors="coerce")
            prepared = prepared.loc[
                prepared["LastUpdated"].notna() & (prepared["LastUpdated"] <= as_of)
            ].sort_values("LastUpdated")
        return cls._indexed_rows(prepared, "ProductId")

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
        evidence: dict[str, Any] | None = None,
    ) -> int:
        if unit_cost <= 0:
            if evidence is not None:
                evidence.update({
                    "remaining_budget": remaining_budget,
                    "unit_cost": unit_cost,
                    "affordable_quantity": None,
                    "reason": "ZERO_UNIT_COST",
                    "output": desired_quantity,
                })
            return desired_quantity
        affordable = int(math.floor(remaining_budget / unit_cost))
        if available_stock < sales_unit:
            result = desired_quantity if desired_quantity <= affordable else 0
            if evidence is not None:
                evidence.update({
                    "remaining_budget": remaining_budget,
                    "unit_cost": unit_cost,
                    "affordable_quantity": affordable,
                    "sales_unit": sales_unit,
                    "available_stock": available_stock,
                    "tail_stock": True,
                    "output": result,
                })
            return result
        result = min(desired_quantity, int(math.floor(affordable / sales_unit) * sales_unit))
        if evidence is not None:
            evidence.update({
                "remaining_budget": remaining_budget,
                "unit_cost": unit_cost,
                "affordable_quantity": affordable,
                "affordable_sales_unit_quantity": int(math.floor(affordable / sales_unit) * sales_unit),
                "sales_unit": sales_unit,
                "available_stock": available_stock,
                "tail_stock": False,
                "output": result,
            })
        return result

    @staticmethod
    def _trace_record(
        row: dict[str, Any] | None,
        columns: tuple[str, ...],
    ) -> dict[str, Any] | None:
        if not row:
            return None
        records = LocalOptimizer._trace_records(pd.DataFrame([row]), columns)
        return records[0] if records else None

    @staticmethod
    def _trace_records(
        frame: pd.DataFrame,
        columns: tuple[str, ...],
    ) -> list[dict[str, Any]]:
        if frame is None or frame.empty:
            return []
        selected_columns = [column for column in columns if column in frame.columns]
        if not selected_columns:
            return []
        records: list[dict[str, Any]] = []
        for _, row in frame.loc[:, selected_columns].iterrows():
            item: dict[str, Any] = {}
            for column in selected_columns:
                value = row.get(column)
                if pd.isna(value):
                    item[column] = None
                elif isinstance(value, pd.Timestamp):
                    item[column] = value.isoformat()
                elif hasattr(value, "item"):
                    try:
                        item[column] = value.item()
                    except (AttributeError, ValueError):
                        item[column] = value
                else:
                    item[column] = value
            records.append(item)
        return records

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
