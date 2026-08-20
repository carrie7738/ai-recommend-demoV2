from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd


MISSING_STORE_MESSAGE = (
    'Please include a store name or ID, for example “Cafe Store 001” or “C001”.'
)
UNKNOWN_STORE_MESSAGE = (
    'We could not find that store in the demo data. Use a full store name or ID.'
)


@dataclass(frozen=True)
class StoreResolution:
    status: str
    customer_id: str | None = None
    message: str | None = None
    candidates: tuple[str, ...] = ()

    @property
    def is_found(self) -> bool:
        return self.status == "found" and self.customer_id is not None


class StoreResolver:
    """Resolve a store mentioned in a procurement request without fuzzy matching."""

    def resolve(self, workbook: dict[str, pd.DataFrame], request: str) -> StoreResolution:
        customers = workbook.get("Customer")
        contexts = workbook.get("ConversationContext")
        if customers is None or contexts is None or customers.empty or contexts.empty:
            return StoreResolution("unknown", message=UNKNOWN_STORE_MESSAGE)

        available_customer_ids = set(contexts["CustomerId"].dropna().astype(str))
        candidates = customers.loc[customers["CustomerId"].astype(str).isin(available_customer_ids)]
        matches = self._find_matches(candidates, request)

        if len(matches) == 1:
            return StoreResolution("found", customer_id=matches[0]["customer_id"])
        if len(matches) > 1:
            labels = tuple(match["label"] for match in matches)
            return StoreResolution(
                "ambiguous",
                message=f"Multiple stores matched: {', '.join(labels)}. Please include the store ID.",
                candidates=labels,
            )
        if self._looks_like_store_reference(request):
            return StoreResolution("unknown", message=UNKNOWN_STORE_MESSAGE)
        return StoreResolution("missing", message=MISSING_STORE_MESSAGE)

    def build_store_context(self, workbook: dict[str, pd.DataFrame], customer_id: str) -> dict[str, str]:
        """Build the trusted store profile used by AI and deterministic recommendation rules."""
        customers = workbook.get("Customer")
        contexts = workbook.get("ConversationContext")
        if customers is None or contexts is None or customers.empty or contexts.empty:
            raise ValueError("Customer and conversation context data are required.")

        available_customer_ids = set(contexts["CustomerId"].dropna().astype(str))
        customer_row = customers.loc[customers["CustomerId"].astype(str) == str(customer_id)]
        if customer_row.empty or str(customer_id) not in available_customer_ids:
            raise ValueError("The selected store does not have demo data.")

        row = customer_row.iloc[0]
        return {
            "CustomerId": str(row.get("CustomerId", customer_id)),
            "StoreName": str(row.get("StoreName", "")),
            "Industry": str(row.get("Industry", "")),
            "Region": str(row.get("Region", "")),
            "StoreLevel": str(row.get("StoreLevel", "Silver") or "Silver"),
            "CustomerStage": str(row.get("CustomerStage", "Mature") or "Mature"),
        }

    @staticmethod
    def _find_matches(customers: pd.DataFrame, request: str) -> list[dict[str, str]]:
        normalized_request = StoreResolver._normalize(request)
        matches: list[dict[str, str]] = []

        for _, row in customers.iterrows():
            customer_id = str(row["CustomerId"]).strip()
            store_name = str(row["StoreName"]).strip()
            normalized_name = StoreResolver._normalize(store_name)
            id_found = bool(re.search(rf"(?<![A-Za-z0-9]){re.escape(customer_id)}(?![A-Za-z0-9])", request, re.IGNORECASE))
            name_found = bool(normalized_name) and normalized_name in normalized_request
            if id_found or name_found:
                matches.append({
                    "customer_id": customer_id,
                    "label": f"{store_name} ({customer_id})",
                })

        unique_matches = {match["customer_id"]: match for match in matches}
        return list(unique_matches.values())

    @staticmethod
    def _looks_like_store_reference(request: str) -> bool:
        return bool(re.search(r"\b(?:c\d{3,}|store|shop|market|restaurant|cafe)\b", request, re.IGNORECASE))

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"\s+", " ", value.strip()).casefold()
