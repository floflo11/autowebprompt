"""Excel file validation for downloaded artifacts."""

import logging
from pathlib import Path

from autowebprompt.agents.base import TaskStatus

logger = logging.getLogger(__name__)


def validate_excel_file(
    file_path,
    require_model_sheet: bool = True,
    require_answers_sheet: bool = True,
) -> tuple[bool, TaskStatus, str]:
    """
    Validate a downloaded Excel file.

    Checks:
    1. File exists and has non-zero size
    2. openpyxl can open it (not corrupted)
    3. Optionally checks for sheets containing "model" and "answers"

    Args:
        file_path: Path to the Excel file
        require_model_sheet: Whether to require a sheet with "model" in its name
        require_answers_sheet: Whether to require a sheet with "answers" in its name

    Returns:
        (is_valid, status, message) tuple
    """
    file_path = Path(file_path)

    if not file_path.exists():
        return False, TaskStatus.DOWNLOAD_FAILED, f"File does not exist: {file_path}"

    if file_path.stat().st_size == 0:
        return False, TaskStatus.DOWNLOAD_FAILED, f"File is empty: {file_path}"

    try:
        import openpyxl

        wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
        sheet_names = [s.lower() for s in wb.sheetnames]
        wb.close()
    except ImportError:
        logger.warning("openpyxl not installed — skipping corruption check")
        return True, TaskStatus.SUCCESS, "openpyxl not available, skipping validation"
    except Exception as e:
        return False, TaskStatus.FILE_CORRUPTED, f"Cannot open Excel file: {e}"

    if require_model_sheet or require_answers_sheet:
        has_model = any("model" in name for name in sheet_names)
        has_answers = any("answers" in name or "answer" in name for name in sheet_names)

        if require_model_sheet and require_answers_sheet:
            if not has_model and not has_answers:
                return (
                    False, TaskStatus.MISSING_SHEETS,
                    f"Missing both 'model' and 'answers' sheets. Found: {sheet_names}",
                )
            if not has_model:
                return (
                    False, TaskStatus.MISSING_SHEETS,
                    f"Missing 'model' sheet. Found: {sheet_names}",
                )
            if not has_answers:
                return (
                    False, TaskStatus.MISSING_SHEETS,
                    f"Missing 'answers' sheet. Found: {sheet_names}",
                )
        elif require_model_sheet and not has_model:
            return (
                False, TaskStatus.MISSING_SHEETS,
                f"Missing 'model' sheet. Found: {sheet_names}",
            )
        elif require_answers_sheet and not has_answers:
            return (
                False, TaskStatus.MISSING_SHEETS,
                f"Missing 'answers' sheet. Found: {sheet_names}",
            )

    return True, TaskStatus.SUCCESS, "Valid"
