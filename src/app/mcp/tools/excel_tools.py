"""
Excel analysis tools (local, non-MCP).

Goals:
- Read and summarize Excel files (.xlsx, .xls)
- Search for text across all sheets
- Analyze data (totals, averages, statistics)
- Support data extraction and filtering

These tools wrap the scripts in .claude/skills/excel-analyzer/scripts/
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from langchain_core.tools import BaseTool
from langchain.tools import tool
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from src.app.logging.logger import setup_logger
from src.app.mcp.tools.tagging import tag_tool

logger = setup_logger(__name__)

EXCEL_SOURCE_SERVER = "excelAnalysis"

# Path to Excel analyzer scripts
SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent.parent / ".claude/skills/excel-analyzer/scripts"


def _run_script(script_name: str, args: List[str]) -> str:
    """
    Run an Excel analyzer script and return output.

    Args:
        script_name: Name of the script (e.g., 'read_excel.py')
        args: Command-line arguments

    Returns:
        Script output as string

    Raises:
        ToolException: If script execution fails
    """
    script_path = SCRIPTS_DIR / script_name

    if not script_path.exists():
        raise ToolException(f"Excel script not found: {script_path}")

    cmd = [sys.executable, str(script_path)] + args

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout or "Unknown error"
            raise ToolException(f"Excel script failed: {error_msg}")

        return result.stdout

    except subprocess.TimeoutExpired:
        raise ToolException("Excel script timed out (60s limit)")
    except Exception as e:
        raise ToolException(f"Failed to run Excel script: {str(e)}")


# -----------------------------
# Public tools (loaded into agents)
# -----------------------------

class ExcelReadFileInput(BaseModel):
    file_path: str = Field(description="Path to Excel file (.xlsx or .xls)")
    sheet_name: Optional[str] = Field(default=None, description="Specific sheet name to read (default: all sheets)")
    mode: str = Field(default="summary", description="Read mode: 'summary' (comprehensive overview), 'list-sheets' (just sheet names), or 'sheet' (specific sheet)")


@tool(name_or_callable="excelAnalysis_read_file", args_schema=ExcelReadFileInput)
def excelAnalysis_read_file(file_path: str, sheet_name: Optional[str] = None, mode: str = "summary") -> str:
    """
    Read and summarize an Excel file. Returns file structure, data types, and sample data.

    Use this when user asks to:
    - Read/open an Excel file
    - Summarize spreadsheet contents
    - List available sheets
    - View Excel file structure
    """
    args = [file_path]

    if mode == "summary":
        args.append("--summary")
    elif mode == "list-sheets":
        args.append("--list-sheets")
    elif mode == "sheet" and sheet_name:
        args.extend(["--sheet", sheet_name])
    else:
        # Default: summary
        args.append("--summary")

    logger.info("Reading Excel file | path=%s | mode=%s | sheet=%s", file_path, mode, sheet_name)

    try:
        output = _run_script("read_excel.py", args)
        return output
    except Exception as e:
        logger.exception("Failed to read Excel file | path=%s", file_path)
        raise


class ExcelSearchContentInput(BaseModel):
    file_path: str = Field(description="Path to Excel file (.xlsx or .xls)")
    search_term: str = Field(description="Text to search for across all sheets")
    case_sensitive: bool = Field(default=False, description="Whether search should be case-sensitive")
    max_results: int = Field(default=50, description="Maximum number of results to return")


@tool(name_or_callable="excelAnalysis_search_content", args_schema=ExcelSearchContentInput)
def excelAnalysis_search_content(
    file_path: str,
    search_term: str,
    case_sensitive: bool = False,
    max_results: int = 50,
) -> str:
    """
    Search for text across all sheets in an Excel file. Returns cell locations and values.

    Use this when user asks to:
    - Find/search for specific text in Excel
    - Locate data across multiple sheets
    - Search for keywords or values
    """
    args = [file_path, search_term]

    if case_sensitive:
        args.append("--case-sensitive")

    if max_results != 50:
        args.extend(["--max-results", str(max_results)])

    logger.info(
        "Searching Excel file | path=%s | term=%s | case_sensitive=%s | max_results=%s",
        file_path,
        search_term,
        case_sensitive,
        max_results,
    )

    try:
        output = _run_script("search_excel.py", args)
        return output
    except Exception as e:
        logger.exception("Failed to search Excel file | path=%s | term=%s", file_path, search_term)
        raise


class ExcelAnalyzeDataInput(BaseModel):
    file_path: str = Field(description="Path to Excel file (.xlsx or .xls)")
    sheet_name: str = Field(description="Sheet name to analyze")
    operation: str = Field(
        default="summary",
        description="Analysis operation: 'totals' (column sums), 'averages' (column means), 'summary' (comprehensive stats), 'counts' (value distributions), 'correlations' (numeric correlations)",
    )


@tool(name_or_callable="excelAnalysis_analyze_data", args_schema=ExcelAnalyzeDataInput)
def excelAnalysis_analyze_data(file_path: str, sheet_name: str, operation: str = "summary") -> str:
    """
    Analyze Excel data with various statistical operations. Returns calculations and insights.

    Use this when user asks to:
    - Calculate totals/sums in Excel
    - Find averages or statistics
    - Analyze data patterns
    - Get value counts or correlations
    - Generate data summary
    """
    valid_operations = ["totals", "averages", "summary", "counts", "correlations"]
    if operation not in valid_operations:
        raise ToolException(
            f"Invalid operation: {operation}. Must be one of: {', '.join(valid_operations)}"
        )

    args = [file_path, "--sheet", sheet_name, "--operation", operation]

    logger.info(
        "Analyzing Excel data | path=%s | sheet=%s | operation=%s",
        file_path,
        sheet_name,
        operation,
    )

    try:
        output = _run_script("analyze_data.py", args)
        return output
    except Exception as e:
        logger.exception(
            "Failed to analyze Excel file | path=%s | sheet=%s | operation=%s",
            file_path,
            sheet_name,
            operation,
        )
        raise


# Tag tools at definition time so source_server lives with the tool itself
excelAnalysis_read_file = tag_tool(
    excelAnalysis_read_file,
    source_server=EXCEL_SOURCE_SERVER,
)
excelAnalysis_search_content = tag_tool(
    excelAnalysis_search_content,
    source_server=EXCEL_SOURCE_SERVER,
)
excelAnalysis_analyze_data = tag_tool(
    excelAnalysis_analyze_data,
    source_server=EXCEL_SOURCE_SERVER,
)

# Tool error handling: do not crash the whole supervisor run if Excel tools fail
excelAnalysis_read_file.handle_tool_error = True
excelAnalysis_search_content.handle_tool_error = True
excelAnalysis_analyze_data.handle_tool_error = True


def get_excel_tools() -> List[BaseTool]:
    """
    Export all local Excel tools for bootstrap loading.
    """
    return [
        excelAnalysis_read_file,
        excelAnalysis_search_content,
        excelAnalysis_analyze_data,
    ]
