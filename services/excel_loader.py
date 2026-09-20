from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import streamlit as st


logger = logging.getLogger(__name__)


class ExcelLoaderError(Exception):
    """Raised when the demo workbook cannot be loaded safely."""


def _load_sheet_cached(
    workbook_path: str,
    mtime_ns: int,
    size: int,
    sheet_name: str,
) -> pd.DataFrame:
    """Load one sheet; file identity arguments intentionally participate in the cache key."""
    del mtime_ns, size
    try:
        dataframe = pd.read_excel(
            workbook_path,
            sheet_name=sheet_name,
            engine="openpyxl",
        )
    except ValueError as exc:
        logger.warning("Requested sheet does not exist: %s", sheet_name)
        raise ExcelLoaderError(f"Sheet '{sheet_name}' was not found in the workbook.") from exc
    except ImportError as exc:
        raise ExcelLoaderError(
            "Openpyxl is required to read the Excel workbook. Install dependencies first."
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive loader guard
        logger.exception("Unexpected error while loading sheet %s", sheet_name)
        raise ExcelLoaderError(f"Failed to load sheet '{sheet_name}'.") from exc

    logger.info("Loaded sheet '%s' with %s rows.", sheet_name, len(dataframe))
    return dataframe


_load_sheet_cached = st.cache_data(show_spinner=False)(_load_sheet_cached)


def _list_sheet_names_cached(
    workbook_path: str,
    mtime_ns: int,
    size: int,
) -> list[str]:
    """List sheets; file identity arguments intentionally participate in the cache key."""
    del mtime_ns, size
    try:
        with pd.ExcelFile(workbook_path, engine="openpyxl") as workbook:
            return workbook.sheet_names
    except ImportError as exc:
        raise ExcelLoaderError(
            "Openpyxl is required to inspect the Excel workbook. Install dependencies first."
        ) from exc
    except Exception as exc:  # pragma: no cover - defensive loader guard
        logger.exception("Unexpected error while listing sheets.")
        raise ExcelLoaderError("Failed to inspect workbook sheets.") from exc


_list_sheet_names_cached = st.cache_data(show_spinner=False)(_list_sheet_names_cached)


def _load_workbook_cached(
    workbook_path: str,
    mtime_ns: int,
    size: int,
) -> dict[str, pd.DataFrame]:
    """Load every sheet using the same file identity as the parent cache entry."""
    sheet_names = _list_sheet_names_cached(workbook_path, mtime_ns, size)
    return {
        sheet_name: _load_sheet_cached(workbook_path, mtime_ns, size, sheet_name)
        for sheet_name in sheet_names
    }


_load_workbook_cached = st.cache_data(show_spinner=False)(_load_workbook_cached)


class ExcelLoader:
    def __init__(self, workbook_path: str | Path) -> None:
        self.workbook_path = Path(workbook_path)

    def _validate_workbook(self) -> None:
        if not self.workbook_path.exists():
            raise ExcelLoaderError(f"Workbook not found at {self.workbook_path}")
        if self.workbook_path.suffix.lower() != ".xlsx":
            raise ExcelLoaderError("Workbook must be an .xlsx file.")

    def _cache_key(self) -> tuple[str, int, int]:
        """Return a canonical, current identity for this workbook before cache lookup."""
        self._validate_workbook()
        try:
            resolved_path = self.workbook_path.expanduser().resolve(strict=True)
            stat = resolved_path.stat()
        except FileNotFoundError as exc:
            raise ExcelLoaderError(f"Workbook not found at {self.workbook_path}") from exc
        return str(resolved_path), stat.st_mtime_ns, stat.st_size

    def load_sheet(self, sheet_name: str) -> pd.DataFrame:
        workbook_path, mtime_ns, size = self._cache_key()
        return _load_sheet_cached(workbook_path, mtime_ns, size, sheet_name)

    def list_sheet_names(self) -> list[str]:
        workbook_path, mtime_ns, size = self._cache_key()
        return _list_sheet_names_cached(workbook_path, mtime_ns, size)

    def load_workbook(self) -> dict[str, pd.DataFrame]:
        workbook_path, mtime_ns, size = self._cache_key()
        return _load_workbook_cached(workbook_path, mtime_ns, size)
