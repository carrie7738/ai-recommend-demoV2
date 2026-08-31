from __future__ import annotations

from typing import Any

import pandas as pd


class EventNormalizer:
    """Map a normalized occasion to one configured demo event and its existing window."""

    @staticmethod
    def normalize(
        workbook: dict[str, pd.DataFrame],
        occasion: str,
        reference_date: Any,
    ) -> dict[str, Any] | None:
        code = str(occasion or "NONE").strip().upper()
        events = workbook.get("EventConfig")
        if code in {"", "NONE"} or events is None or events.empty:
            return None

        prepared = events.copy()
        prepared["EventWindowStart"] = pd.to_datetime(
            prepared["EventWindowStart"], errors="coerce"
        )
        prepared["EventWindowEnd"] = pd.to_datetime(
            prepared["EventWindowEnd"], errors="coerce"
        )
        rows = prepared.loc[
            prepared["EventName"].astype(str).str.upper().str.contains(code, regex=False)
            & prepared["EventWindowStart"].notna()
            & prepared["EventWindowEnd"].notna()
        ].copy()
        if rows.empty:
            return None

        comparable = rows.loc[
            rows["ComparableEventId"].notna()
            & rows["ComparableEventId"].astype(str).str.strip().ne("")
        ] if "ComparableEventId" in rows.columns else rows.iloc[0:0]
        if not comparable.empty:
            rows = comparable

        reference = pd.to_datetime(reference_date, errors="coerce")
        if pd.notna(reference):
            active = rows.loc[
                (rows["EventWindowStart"] <= reference)
                & (rows["EventWindowEnd"] >= reference)
            ]
            if not active.empty:
                rows = active
            else:
                rows["distance"] = (rows["EventWindowStart"] - reference).abs()
                rows = rows.sort_values(
                    ["distance", "EventWindowStart"], ascending=[True, False]
                )
        else:
            rows = rows.sort_values("EventWindowStart", ascending=False)

        row = rows.iloc[0]
        return {
            "event_id": str(row.get("EventId") or ""),
            "event_name": str(row.get("EventName") or ""),
            "event_type": str(row.get("EventType") or ""),
            "event_window_start": pd.Timestamp(row["EventWindowStart"]).normalize(),
            "event_window_end": pd.Timestamp(row["EventWindowEnd"]).normalize(),
            "comparable_event_id": (
                str(row.get("ComparableEventId"))
                if pd.notna(row.get("ComparableEventId"))
                else None
            ),
        }
