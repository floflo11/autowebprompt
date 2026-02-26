"""Tests for autowebprompt.validators.excel module."""

import sys
from unittest.mock import patch, MagicMock

import pytest

from autowebprompt.agents.base import TaskStatus
from autowebprompt.validators.excel import validate_excel_file


def _mock_openpyxl(sheetnames, side_effect=None):
    """Create a mock openpyxl module with a load_workbook that returns a workbook with given sheetnames."""
    mock_module = MagicMock()
    if side_effect:
        mock_module.load_workbook.side_effect = side_effect
    else:
        mock_wb = MagicMock()
        mock_wb.sheetnames = sheetnames
        mock_module.load_workbook.return_value = mock_wb
    return mock_module


class TestValidateExcelFile:
    """Tests for validate_excel_file()."""

    def test_file_does_not_exist(self, tmp_path):
        """Returns DOWNLOAD_FAILED when the file does not exist."""
        missing = tmp_path / "missing.xlsx"

        is_valid, status, msg = validate_excel_file(missing)

        assert is_valid is False
        assert status == TaskStatus.DOWNLOAD_FAILED
        assert "does not exist" in msg

    def test_empty_file(self, tmp_path):
        """Returns DOWNLOAD_FAILED when the file has zero bytes."""
        empty_file = tmp_path / "empty.xlsx"
        empty_file.write_bytes(b"")

        is_valid, status, msg = validate_excel_file(empty_file)

        assert is_valid is False
        assert status == TaskStatus.DOWNLOAD_FAILED
        assert "empty" in msg.lower()

    def test_corrupted_file(self, tmp_path):
        """Returns FILE_CORRUPTED when openpyxl cannot open the file."""
        bad_file = tmp_path / "corrupt.xlsx"
        bad_file.write_bytes(b"not a real xlsx file content")

        mock_openpyxl = _mock_openpyxl([], side_effect=Exception("Bad format"))
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(bad_file)

        assert is_valid is False
        assert status == TaskStatus.FILE_CORRUPTED
        assert "Cannot open" in msg

    def test_valid_file_with_both_sheets(self, tmp_path):
        """Returns SUCCESS when file has both 'model' and 'answers' sheets."""
        xlsx_file = tmp_path / "good.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["Financial Model", "Answers Sheet", "Summary"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(xlsx_file)

        assert is_valid is True
        assert status == TaskStatus.SUCCESS
        assert msg == "Valid"

    def test_missing_model_sheet(self, tmp_path):
        """Returns MISSING_SHEETS when 'model' sheet is not found."""
        xlsx_file = tmp_path / "no_model.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["Answers", "Summary"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(xlsx_file)

        assert is_valid is False
        assert status == TaskStatus.MISSING_SHEETS
        assert "model" in msg.lower()

    def test_missing_answers_sheet(self, tmp_path):
        """Returns MISSING_SHEETS when 'answers' sheet is not found."""
        xlsx_file = tmp_path / "no_answers.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["Financial Model", "Summary"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(xlsx_file)

        assert is_valid is False
        assert status == TaskStatus.MISSING_SHEETS
        assert "answers" in msg.lower()

    def test_missing_both_sheets(self, tmp_path):
        """Returns MISSING_SHEETS when both required sheets are absent."""
        xlsx_file = tmp_path / "no_both.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["Sheet1", "Data"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(xlsx_file)

        assert is_valid is False
        assert status == TaskStatus.MISSING_SHEETS
        assert "model" in msg.lower()
        assert "answers" in msg.lower()

    def test_no_sheet_requirements(self, tmp_path):
        """Returns SUCCESS when sheet requirements are disabled."""
        xlsx_file = tmp_path / "any_sheets.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["Random", "Stuff"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(
                xlsx_file,
                require_model_sheet=False,
                require_answers_sheet=False,
            )

        assert is_valid is True
        assert status == TaskStatus.SUCCESS

    def test_only_model_required_and_present(self, tmp_path):
        """Returns SUCCESS when only model is required and it exists."""
        xlsx_file = tmp_path / "model_only.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["My Model"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(
                xlsx_file,
                require_model_sheet=True,
                require_answers_sheet=False,
            )

        assert is_valid is True
        assert status == TaskStatus.SUCCESS

    def test_only_model_required_but_missing(self, tmp_path):
        """Returns MISSING_SHEETS when only model is required but absent."""
        xlsx_file = tmp_path / "no_model2.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["Answers", "Data"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(
                xlsx_file,
                require_model_sheet=True,
                require_answers_sheet=False,
            )

        assert is_valid is False
        assert status == TaskStatus.MISSING_SHEETS

    def test_only_answers_required_and_present(self, tmp_path):
        """Returns SUCCESS when only answers is required and exists."""
        xlsx_file = tmp_path / "answers_only.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["My Answers"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(
                xlsx_file,
                require_model_sheet=False,
                require_answers_sheet=True,
            )

        assert is_valid is True
        assert status == TaskStatus.SUCCESS

    def test_only_answers_required_but_missing(self, tmp_path):
        """Returns MISSING_SHEETS when only answers is required but absent."""
        xlsx_file = tmp_path / "no_answers2.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["Model", "Data"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(
                xlsx_file,
                require_model_sheet=False,
                require_answers_sheet=True,
            )

        assert is_valid is False
        assert status == TaskStatus.MISSING_SHEETS

    def test_case_insensitive_sheet_matching(self, tmp_path):
        """Sheet name matching is case-insensitive."""
        xlsx_file = tmp_path / "case.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["FINANCIAL MODEL", "ANSWERS"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(xlsx_file)

        assert is_valid is True
        assert status == TaskStatus.SUCCESS

    def test_answer_singular_matches(self, tmp_path):
        """The validator also matches 'answer' (singular) for the answers sheet."""
        xlsx_file = tmp_path / "singular.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["Model", "Answer"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(xlsx_file)

        assert is_valid is True
        assert status == TaskStatus.SUCCESS

    def test_openpyxl_not_installed(self, tmp_path):
        """Returns SUCCESS with warning when openpyxl is not installed."""
        xlsx_file = tmp_path / "no_openpyxl.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        # Remove openpyxl from sys.modules to simulate it not being installed
        saved = sys.modules.pop("openpyxl", None)
        try:
            import builtins
            original_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "openpyxl":
                    raise ImportError("No module named 'openpyxl'")
                return original_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                is_valid, status, msg = validate_excel_file(xlsx_file)

            assert is_valid is True
            assert status == TaskStatus.SUCCESS
            assert "openpyxl not available" in msg
        finally:
            if saved is not None:
                sys.modules["openpyxl"] = saved

    def test_accepts_string_path(self, tmp_path):
        """validate_excel_file accepts a string path, not just a Path object."""
        xlsx_file = tmp_path / "string_path.xlsx"
        xlsx_file.write_bytes(b"\x00" * 100)

        mock_openpyxl = _mock_openpyxl(["Model", "Answers"])
        with patch.dict(sys.modules, {"openpyxl": mock_openpyxl}):
            is_valid, status, msg = validate_excel_file(str(xlsx_file))

        assert is_valid is True
