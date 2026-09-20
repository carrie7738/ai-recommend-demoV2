from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

import pandas as pd
import streamlit as st

from services.excel_loader import ExcelLoader, ExcelLoaderError


class ExcelLoaderCacheRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        st.cache_data.clear()
        self.tempdir = tempfile.TemporaryDirectory()
        self.directory = Path(self.tempdir.name)

    def tearDown(self) -> None:
        st.cache_data.clear()
        self.tempdir.cleanup()

    @staticmethod
    def _write_workbook(path: Path, sheets: dict[str, dict[str, list]]) -> None:
        with pd.ExcelWriter(path, engine="openpyxl") as writer:
            for sheet_name, columns in sheets.items():
                pd.DataFrame(columns).to_excel(writer, sheet_name=sheet_name, index=False)

    def test_cache_key_includes_workbook_path_for_all_entry_points(self) -> None:
        first_path = self.directory / "first.xlsx"
        second_path = self.directory / "second.xlsx"
        self._write_workbook(
            first_path,
            {"Products": {"ProductId": ["FIRST"], "Price": [1]}},
        )
        self._write_workbook(
            second_path,
            {"Products": {"ProductId": ["SECOND"], "Price": [2]}},
        )

        first_loader = ExcelLoader(first_path)
        second_loader = ExcelLoader(second_path)

        first_sheet = first_loader.load_sheet("Products")
        second_sheet = second_loader.load_sheet("Products")
        self.assertEqual(second_sheet.iloc[0]["ProductId"], "SECOND")

        self.assertEqual(first_loader.list_sheet_names(), ["Products"])
        self.assertEqual(second_loader.list_sheet_names(), ["Products"])

        first_workbook = first_loader.load_workbook()
        second_workbook = second_loader.load_workbook()
        self.assertEqual(first_workbook["Products"].iloc[0]["ProductId"], "FIRST")
        self.assertEqual(second_workbook["Products"].iloc[0]["ProductId"], "SECOND")

    def test_same_path_updates_invalidate_all_entry_points(self) -> None:
        workbook_path = self.directory / "mutable.xlsx"
        self._write_workbook(
            workbook_path,
            {"OldSheet": {"ProductId": ["OLD"], "Price": [1]}},
        )
        loader = ExcelLoader(workbook_path)

        old_sheet = loader.load_sheet("OldSheet")
        old_names = loader.list_sheet_names()
        old_workbook = loader.load_workbook()

        before = workbook_path.stat()
        self._write_workbook(
            workbook_path,
            {
                "NewSheet": {
                    "ProductId": ["NEW", "NEW-2"],
                    "Price": [2, 3],
                }
            },
        )
        after = workbook_path.stat()
        if after.st_mtime_ns <= before.st_mtime_ns:
            os.utime(
                workbook_path,
                ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000),
            )

        self.assertEqual(old_sheet.iloc[0]["ProductId"], "OLD")
        self.assertEqual(old_names, ["OldSheet"])
        self.assertIn("OldSheet", old_workbook)

        self.assertEqual(loader.list_sheet_names(), ["NewSheet"])
        new_sheet = loader.load_sheet("NewSheet")
        self.assertEqual(new_sheet["ProductId"].tolist(), ["NEW", "NEW-2"])
        new_workbook = loader.load_workbook()
        self.assertEqual(new_workbook["NewSheet"]["Price"].tolist(), [2, 3])

    def test_deleted_workbook_is_not_served_from_any_cache(self) -> None:
        workbook_path = self.directory / "deleted.xlsx"
        self._write_workbook(
            workbook_path,
            {"Products": {"ProductId": ["P1"], "Price": [1]}},
        )
        loader = ExcelLoader(workbook_path)

        loader.load_sheet("Products")
        loader.list_sheet_names()
        loader.load_workbook()
        workbook_path.unlink()

        with self.assertRaisesRegex(ExcelLoaderError, "Workbook not found"):
            loader.load_sheet("Products")
        with self.assertRaisesRegex(ExcelLoaderError, "Workbook not found"):
            loader.list_sheet_names()
        with self.assertRaisesRegex(ExcelLoaderError, "Workbook not found"):
            loader.load_workbook()


if __name__ == "__main__":
    unittest.main()
