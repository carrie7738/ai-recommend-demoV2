from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


class V2PolicyError(ValueError):
    """Raised when required V2 evaluation parameters are absent or invalid."""


@dataclass(frozen=True)
class V2FeaturePolicy:
    purchase_frequency_window_days: int
    purchase_frequency_high_threshold: int
    purchase_frequency_low_threshold: int
    stockout_high_risk_coverage_days: float
    stockout_low_risk_coverage_days: float
    discovery_history_lookback_months: int
    discovery_peer_ratio_threshold: float
    recent_store_baseline_days: int
    event_baseline_fallback_order: tuple[str, ...]

    REQUIRED_PARAMETERS = {
        "purchase_frequency_window_days",
        "purchase_frequency_high_threshold",
        "purchase_frequency_low_threshold",
        "stockout_high_risk_coverage_days",
        "stockout_low_risk_coverage_days",
        "discovery_history_lookback_months",
        "discovery_peer_ratio_threshold",
        "recent_store_baseline_days",
        "event_baseline_fallback_order",
    }

    @classmethod
    def from_workbook(cls, workbook: dict[str, pd.DataFrame]) -> "V2FeaturePolicy":
        table = workbook.get("V2FeaturePolicy")
        if table is None or table.empty:
            raise V2PolicyError("V2FeaturePolicy sheet is required.")
        required_columns = {"ParameterName", "ParameterValue"}
        if not required_columns.issubset(table.columns):
            raise V2PolicyError("V2FeaturePolicy must contain ParameterName and ParameterValue.")

        values = {
            str(row["ParameterName"]).strip(): row["ParameterValue"]
            for _, row in table.iterrows()
            if pd.notna(row["ParameterName"])
        }
        missing = sorted(cls.REQUIRED_PARAMETERS - set(values))
        if missing:
            raise V2PolicyError(f"Missing V2 feature parameters: {', '.join(missing)}")

        policy = cls(
            purchase_frequency_window_days=cls._positive_int(values["purchase_frequency_window_days"]),
            purchase_frequency_high_threshold=cls._positive_int(values["purchase_frequency_high_threshold"]),
            purchase_frequency_low_threshold=cls._non_negative_int(values["purchase_frequency_low_threshold"]),
            stockout_high_risk_coverage_days=cls._non_negative_float(values["stockout_high_risk_coverage_days"]),
            stockout_low_risk_coverage_days=cls._non_negative_float(values["stockout_low_risk_coverage_days"]),
            discovery_history_lookback_months=cls._positive_int(values["discovery_history_lookback_months"]),
            discovery_peer_ratio_threshold=cls._ratio(values["discovery_peer_ratio_threshold"]),
            recent_store_baseline_days=cls._positive_int(values["recent_store_baseline_days"]),
            event_baseline_fallback_order=tuple(
                part.strip().upper()
                for part in str(values["event_baseline_fallback_order"]).split("|")
                if part.strip()
            ),
        )
        policy._validate_relationships()
        return policy

    def _validate_relationships(self) -> None:
        if self.purchase_frequency_low_threshold >= self.purchase_frequency_high_threshold:
            raise V2PolicyError("Purchase frequency LOW threshold must be below HIGH threshold.")
        if self.stockout_high_risk_coverage_days >= self.stockout_low_risk_coverage_days:
            raise V2PolicyError("Stockout HIGH coverage threshold must be below LOW threshold.")
        expected_fallback = ("STORE_EVENT", "PEER_EVENT", "RECENT_STORE")
        if self.event_baseline_fallback_order != expected_fallback:
            raise V2PolicyError(
                "Event baseline fallback must be STORE_EVENT|PEER_EVENT|RECENT_STORE for V2."
            )

    @staticmethod
    def _positive_int(value: Any) -> int:
        parsed = int(float(value))
        if parsed <= 0:
            raise V2PolicyError(f"Expected a positive integer, got {value!r}.")
        return parsed

    @staticmethod
    def _non_negative_int(value: Any) -> int:
        parsed = int(float(value))
        if parsed < 0:
            raise V2PolicyError(f"Expected a non-negative integer, got {value!r}.")
        return parsed

    @staticmethod
    def _non_negative_float(value: Any) -> float:
        parsed = float(value)
        if parsed < 0:
            raise V2PolicyError(f"Expected a non-negative number, got {value!r}.")
        return parsed

    @staticmethod
    def _ratio(value: Any) -> float:
        parsed = float(value)
        if not 0 <= parsed <= 1:
            raise V2PolicyError(f"Expected a ratio from 0 to 1, got {value!r}.")
        return parsed
