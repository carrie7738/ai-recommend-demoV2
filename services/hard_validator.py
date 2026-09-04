from __future__ import annotations

import math
from copy import deepcopy
from typing import Any

import pandas as pd


class HardValidationError(ValueError):
    """Raised when the validator itself receives unusable private inputs."""


class HardValidator:
    """Independently verify executable V2 constraints after local optimization."""

    REQUIRED_SHEETS = {"Product", "SupplyAvailability"}
    REDUCTION_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

    def repair(
        self,
        workbook: dict[str, pd.DataFrame],
        structured_intent: dict[str, Any],
        optimizer_result: dict[str, Any],
        violations: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Repair executable quantities without changing candidate rationale or AI priority."""
        repaired = deepcopy(optimizer_result)
        repairable_codes = {
            item.get("code")
            for item in violations
            if item.get("repairable_locally") is True
        }
        if not repairable_codes:
            repaired["repair_applied"] = False
            repaired["repair_actions"] = []
            return repaired

        products = self._indexed_rows(workbook["Product"], "ProductId")
        supply = self._indexed_rows(workbook["SupplyAvailability"], "ProductId")
        actions: list[dict[str, Any]] = []
        plan = repaired.get("purchase_plan", [])

        for item in plan:
            candidate_id = str(item.get("candidate_id") or "")
            if not candidate_id or candidate_id not in products or candidate_id not in supply:
                continue
            quantity = int(math.floor(self._number(item.get("final_qty"), "final_qty")))
            sales_unit_value = self._number(item.get("sales_unit"), "sales_unit")
            sales_unit = int(sales_unit_value)
            available = self._number(supply[candidate_id].get("AvailableStock", 0), "AvailableStock")
            if quantity <= 0 or sales_unit <= 0:
                continue

            if available < sales_unit:
                target = int(math.floor(available))
            else:
                capped = min(quantity, int(math.floor(available)))
                target = int(math.floor(capped / sales_unit) * sales_unit)
            if target != quantity:
                item["final_qty"] = target
                item.setdefault("constraint_adjustments", []).append("DETERMINISTIC_QTY_REPAIR")
                actions.append({
                    "candidate_id": candidate_id,
                    "type": "QUANTITY_CONSTRAINT_REPAIR",
                    "from_qty": quantity,
                    "to_qty": target,
                })

        budget = structured_intent.get("budget")
        if budget is not None:
            budget_value = self._number(budget, "budget")
            reduction_candidates = sorted(
                plan,
                key=lambda item: (
                    self.REDUCTION_ORDER.get(str(item.get("priority") or "LOW").upper(), 0),
                    str(item.get("candidate_id") or ""),
                ),
            )
            total = self._plan_total(plan, products)
            for item in reduction_candidates:
                while total > budget_value + 1e-9 and int(item.get("final_qty") or 0) > 0:
                    candidate_id = str(item.get("candidate_id") or "")
                    quantity = int(item["final_qty"])
                    sales_unit = int(self._number(item.get("sales_unit"), "sales_unit"))
                    available = self._number(
                        (supply.get(candidate_id) or {}).get("AvailableStock", 0),
                        "AvailableStock",
                    )
                    step = quantity if available < sales_unit else sales_unit
                    target = max(quantity - step, 0)
                    item["final_qty"] = target
                    item.setdefault("constraint_adjustments", []).append(
                        "DETERMINISTIC_BUDGET_REPAIR"
                    )
                    actions.append({
                        "candidate_id": candidate_id,
                        "type": "BUDGET_SHRINK",
                        "from_qty": quantity,
                        "to_qty": target,
                    })
                    total = self._plan_total(plan, products)

        unallocated = repaired.setdefault("unallocated_candidates", [])
        retained = []
        for item in plan:
            if int(item.get("final_qty") or 0) <= 0:
                unallocated.append({
                    "candidate_id": str(item.get("candidate_id") or ""),
                    "reason": "DETERMINISTIC_REPAIR_NO_EXECUTABLE_QUANTITY",
                })
                continue
            candidate_id = str(item.get("candidate_id") or "")
            unit_cost = self._unit_cost(item, products.get(candidate_id) or {})
            item["estimated_cost"] = round(int(item["final_qty"]) * unit_cost, 2)
            retained.append(item)
        repaired["purchase_plan"] = retained
        repaired["total_cost"] = round(self._plan_total(retained, products), 2)
        repaired["remaining_budget"] = (
            None if budget is None else round(max(float(budget) - repaired["total_cost"], 0.0), 2)
        )
        repaired["repair_applied"] = bool(actions)
        repaired["repair_actions"] = actions
        return repaired

    def validate(
        self,
        workbook: dict[str, pd.DataFrame],
        structured_intent: dict[str, Any],
        eligible_candidates: list[dict[str, Any]],
        ai_decision: dict[str, Any],
        optimizer_result: dict[str, Any],
        as_of_date: Any | None = None,
    ) -> dict[str, Any]:
        missing = sorted(self.REQUIRED_SHEETS - set(workbook))
        if missing:
            raise HardValidationError(f"Missing validator sheets: {', '.join(missing)}")

        candidate_ids = {
            str(item.get("candidate_id"))
            for item in eligible_candidates
            if isinstance(item, dict) and item.get("candidate_id")
        }
        products = self._indexed_rows(workbook["Product"], "ProductId")
        supply = self._supply_rows(workbook["SupplyAvailability"], as_of_date)
        plan = optimizer_result.get("purchase_plan")
        if not isinstance(plan, list):
            raise HardValidationError("optimizer_result.purchase_plan must be a list.")

        violations: list[dict[str, Any]] = []
        seen: set[str] = set()
        for item in plan:
            candidate_id = str(item.get("candidate_id") or "")
            if not candidate_id or candidate_id not in candidate_ids:
                violations.append(self._violation("INVALID_CANDIDATE", candidate_id or None))
                continue
            if candidate_id in seen:
                violations.append(self._violation("DUPLICATE_CANDIDATE", candidate_id))
            seen.add(candidate_id)

            product = products.get(candidate_id) or {}
            if not self._as_bool(product.get("IsSellable")):
                violations.append(self._violation("PRODUCT_NOT_SELLABLE", candidate_id))

            quantity = self._number(item.get("final_qty"), "final_qty")
            available = self._number(
                (supply.get(candidate_id) or {}).get("AvailableStock", 0),
                "AvailableStock",
            )
            sales_unit_value = self._number(item.get("sales_unit"), "sales_unit")
            sales_unit = int(sales_unit_value)
            if quantity <= 0:
                violations.append(self._violation("NON_POSITIVE_QTY", candidate_id))
            if quantity > available:
                violations.append(self._violation("AVAILABLE_STOCK_EXCEEDED", candidate_id))
            tail_exception = available < sales_unit and math.isclose(quantity, math.floor(available))
            if (
                sales_unit <= 0
                or not sales_unit_value.is_integer()
                or (not tail_exception and quantity % sales_unit != 0)
            ):
                violations.append(self._violation("SALES_UNIT_VIOLATION", candidate_id))

        budget = structured_intent.get("budget")
        validated_total_cost = round(self._product_plan_total(plan, products), 2)
        if budget is not None:
            budget_value = self._number(budget, "budget")
            if validated_total_cost > budget_value + 1e-9:
                violations.append(self._violation("BUDGET_EXCEEDED"))

        high_budget_conflicts = self._high_priority_budget_conflicts(
            ai_decision,
            optimizer_result,
        )
        retry_feedback = None
        if high_budget_conflicts:
            affected = high_budget_conflicts
            violations.append({
                "code": "BUDGET_CONFLICT",
                "candidate_ids": high_budget_conflicts,
                "repairable_locally": False,
                "requires_model_retry": True,
            })
            retry_feedback = {
                "type": "BUDGET_CONFLICT",
                "affected_candidates": affected,
                "reason": "The current candidate combination cannot be supported within the available budget.",
                "required_action": (
                    "Re-evaluate candidate priorities and the retained candidates while preserving "
                    "the primary procurement objective."
                ),
            }

        valid = not violations
        return {
            "status": "PASS" if valid else "FAIL",
            "valid": valid,
            "violations": violations,
            "requires_model_retry": retry_feedback is not None,
            "retry_feedback": retry_feedback,
            "validated_total_cost": validated_total_cost,
        }

    @staticmethod
    def _high_priority_budget_conflicts(
        ai_decision: dict[str, Any],
        optimizer_result: dict[str, Any],
    ) -> list[str]:
        high_ids = {
            item.get("candidate_id")
            for item in ai_decision.get("candidate_decisions", [])
            if item.get("recommended") and item.get("priority") == "HIGH"
        }
        unallocated = {
            item.get("candidate_id")
            for item in optimizer_result.get("unallocated_candidates", [])
            if item.get("reason") == "BUDGET_CONFLICT" and item.get("candidate_id") in high_ids
        }
        # A partial quantity reduction is a deterministic optimizer outcome.
        # Retry the model only when a HIGH candidate cannot be allocated at all
        # and a value trade-off between candidates is therefore required.
        return sorted(unallocated)

    @staticmethod
    def _violation(code: str, candidate_id: str | None = None) -> dict[str, Any]:
        result: dict[str, Any] = {
            "code": code,
            "repairable_locally": code in {
                "AVAILABLE_STOCK_EXCEEDED",
                "SALES_UNIT_VIOLATION",
                "BUDGET_EXCEEDED",
            },
            "requires_model_retry": False,
        }
        if candidate_id:
            result["candidate_id"] = candidate_id
        return result

    @staticmethod
    def _indexed_rows(frame: pd.DataFrame, key: str) -> dict[str, dict[str, Any]]:
        return {
            str(row[key]): row.to_dict()
            for _, row in frame.drop_duplicates(subset=[key], keep="last").iterrows()
            if pd.notna(row.get(key))
        }

    @staticmethod
    def _number(value: Any, field_name: str) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            raise HardValidationError(f"{field_name} must be numeric.") from None
        if not math.isfinite(parsed):
            raise HardValidationError(f"{field_name} must be finite.")
        return parsed

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if pd.isna(value):
            return False
        return str(value).strip().casefold() in {"true", "1", "yes", "y"}

    @classmethod
    def _plan_total(
        cls,
        plan: list[dict[str, Any]],
        products: dict[str, dict[str, Any]],
    ) -> float:
        return sum(
            int(item.get("final_qty") or 0)
            * cls._unit_cost(item, products.get(str(item.get("candidate_id") or "")) or {})
            for item in plan
        )

    @classmethod
    def _product_plan_total(
        cls,
        plan: list[dict[str, Any]],
        products: dict[str, dict[str, Any]],
    ) -> float:
        """Recompute cost from trusted product master data, independent of optimizer totals."""
        return sum(
            int(item.get("final_qty") or 0)
            * cls._number(
                (products.get(str(item.get("candidate_id") or "")) or {}).get("AvgCost", 0),
                "AvgCost",
            )
            for item in plan
        )

    @classmethod
    def _supply_rows(
        cls,
        frame: pd.DataFrame,
        as_of_date: Any | None,
    ) -> dict[str, dict[str, Any]]:
        prepared = frame.copy()
        if as_of_date is not None and "LastUpdated" in prepared.columns:
            as_of = pd.Timestamp(pd.to_datetime(as_of_date, errors="raise")).normalize()
            prepared["LastUpdated"] = pd.to_datetime(prepared["LastUpdated"], errors="coerce")
            prepared = prepared.loc[
                prepared["LastUpdated"].notna() & (prepared["LastUpdated"] <= as_of)
            ].sort_values("LastUpdated")
        return cls._indexed_rows(prepared, "ProductId")

    @staticmethod
    def _unit_cost(item: dict[str, Any], product: dict[str, Any]) -> float:
        value = item.get("unit_cost", product.get("AvgCost", 0))
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.0
        return max(parsed, 0.0) if math.isfinite(parsed) else 0.0
