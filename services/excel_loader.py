from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import streamlit as st


logger = logging.getLogger(__name__)


class ExcelLoaderError(Exception):
    """Raised when the demo workbook cannot be loaded safely."""


class ExcelLoader:
    def __init__(self, workbook_path: str | Path) -> None:
        self.workbook_path = Path(workbook_path)

    def _validate_workbook(self) -> None:
        if not self.workbook_path.exists():
            raise ExcelLoaderError(f"Workbook not found at {self.workbook_path}")
        if self.workbook_path.suffix.lower() != ".xlsx":
            raise ExcelLoaderError("Workbook must be an .xlsx file.")

    @st.cache_data(show_spinner=False)
    def load_sheet(_self, sheet_name: str) -> pd.DataFrame:
        _self._validate_workbook()
        try:
            dataframe = pd.read_excel(
                _self.workbook_path,
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

    @st.cache_data(show_spinner=False)
    def list_sheet_names(_self) -> list[str]:
        _self._validate_workbook()
        try:
            workbook = pd.ExcelFile(_self.workbook_path, engine="openpyxl")
        except ImportError as exc:
            raise ExcelLoaderError(
                "Openpyxl is required to inspect the Excel workbook. Install dependencies first."
            ) from exc
        except Exception as exc:  # pragma: no cover - defensive loader guard
            logger.exception("Unexpected error while listing sheets.")
            raise ExcelLoaderError("Failed to inspect workbook sheets.") from exc

        return workbook.sheet_names

    @st.cache_data(show_spinner=False)
    def load_workbook(_self) -> dict[str, pd.DataFrame]:
        sheet_names = _self.list_sheet_names()
        return {sheet_name: _self.load_sheet(sheet_name) for sheet_name in sheet_names}
