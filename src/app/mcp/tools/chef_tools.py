"""
Indian Dishes Chef tools (local, non-MCP).

Goals:
- Search 6000+ Indian dishes database by ingredients, type, cuisine
- Suggest top X dishes based on user preferences
- Get detailed recipes for specific dishes
- Provide meal recommendations with context

These tools wrap the Excel analyzer scripts with domain knowledge about the Indian dishes dataset.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from langchain_core.tools import BaseTool
from langchain.tools import tool
from langchain_core.tools.base import ToolException
from pydantic import BaseModel, Field

from src.app.config.settings import settings
from src.app.logging.logger import setup_logger
from src.app.mcp.tools.tagging import tag_tool

logger = setup_logger(__name__)

INDIAN_DISHES_SOURCE_SERVER = "indianDishes"

# Path to Excel analyzer scripts
SCRIPTS_DIR = Path(__file__).parent.parent.parent.parent.parent / ".claude/skills/excel-analyzer/scripts"

# Path to Indian dishes Excel file (configurable via settings or default location)
INDIAN_DISHES_FILE = getattr(settings, "indian_dishes_excel_path", None) or "./src/resources/IndianFoodDatasetXLS.xlsx"


def _run_excel_script(script_name: str, args: List[str]) -> str:
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

class IndianDishesSearchInput(BaseModel):
    search_term: str = Field(description="What to search for (ingredients, dish name, cuisine type, dietary preference)")
    max_results: int = Field(default=20, description="Maximum number of dishes to return")
    case_sensitive: bool = Field(default=False, description="Case-sensitive search")


@tool(name_or_callable="indianDishes_search", args_schema=IndianDishesSearchInput)
def indianDishes_search(
    search_term: str,
    max_results: int = 10,
    case_sensitive: bool = False,
) -> str:
    """
    Search the Indian dishes database for dishes matching the search term.

    Use this to find dishes by:
    - Ingredients (e.g., "paneer", "chicken", "spinach")
    - Dish names (e.g., "biryani", "curry", "dal")
    - Cuisine type (e.g., "Punjabi", "South Indian", "Bengali")
    - Dietary preference (e.g., "vegetarian", "vegan", "non-veg")

    Returns matching dishes with their details.
    """
    file_path = INDIAN_DISHES_FILE

    logger.info(
        "Searching Indian dishes | term=%s | max_results=%s | file=%s",
        search_term,
        max_results,
        file_path,
    )

    args = [file_path, search_term]

    if case_sensitive:
        args.append("--case-sensitive")

    if max_results != 50:
        args.extend(["--max-results", str(max_results)])

    try:
        output = _run_excel_script("search_excel.py", args)
        return output
    except Exception as e:
        logger.exception("Failed to search Indian dishes | term=%s", search_term)
        raise


class IndianDishesGetRecipeInput(BaseModel):
    dish_name: str = Field(description="Name of the dish to get recipe for")


@tool(name_or_callable="indianDishes_get_recipe", args_schema=IndianDishesGetRecipeInput)
def indianDishes_get_recipe(dish_name: str) -> str:
    """
    Get detailed recipe for a specific Indian dish.

    Use this when user wants:
    - Full recipe instructions
    - Ingredient list
    - Cooking steps
    - Recipe details for a specific dish

    Returns complete recipe information.
    """
    file_path = INDIAN_DISHES_FILE

    logger.info("Getting recipe for dish | name=%s | file=%s", dish_name, file_path)

    # Search for the specific dish
    args = [file_path, dish_name, "--max-results", "5"]

    try:
        output = _run_excel_script("search_excel.py", args)

        # If found, format nicely
        if "No matches found" not in output:
            return f"Recipe for '{dish_name}':\n\n{output}"
        else:
            return f"Could not find recipe for '{dish_name}'. Try searching for similar dishes using indianDishes_search."

    except Exception as e:
        logger.exception("Failed to get recipe | dish=%s", dish_name)
        raise


class IndianDishesAnalyzeDataInput(BaseModel):
    analysis_type: str = Field(
        default="summary",
        description="Type of analysis: 'summary' (overview), 'counts' (dish type counts), 'cuisines' (list cuisines)"
    )


@tool(name_or_callable="indianDishes_analyze_database", args_schema=IndianDishesAnalyzeDataInput)
def indianDishes_analyze_database(analysis_type: str = "summary") -> str:
    """
    Analyze the Indian dishes database to understand available options.

    Use this when user asks:
    - "What types of dishes do you have?"
    - "How many vegetarian dishes?"
    - "What cuisines are available?"
    - General database statistics

    Returns analysis of the database structure and contents.
    """
    file_path = INDIAN_DISHES_FILE

    logger.info("Analyzing Indian dishes database | type=%s | file=%s", analysis_type, file_path)

    try:
        if analysis_type == "summary":
            # Get comprehensive summary
            output = _run_excel_script("read_excel.py", [file_path, "--summary"])
        else:
            # Get file structure first to know sheet names
            sheets_output = _run_excel_script("read_excel.py", [file_path, "--list-sheets"])

            # Assuming first sheet contains the data, analyze it
            # (In production, you'd parse the sheet names and pick the right one)
            output = _run_excel_script(
                "analyze_data.py",
                [file_path, "--sheet", "Sheet1", "--operation", "counts"]
            )

        return output

    except Exception as e:
        logger.exception("Failed to analyze database | type=%s", analysis_type)
        raise


def get_chef_tools() -> List[BaseTool]:
    """
    Export all Indian dishes chef tools for bootstrap loading.
    """
    tools = [
        indianDishes_search,
        indianDishes_get_recipe,
        indianDishes_analyze_database,
    ]

    # Tag all tools with source_server and enable error handling
    for tool in tools:
        tag_tool(tool, source_server=INDIAN_DISHES_SOURCE_SERVER)
        tool.handle_tool_error = True

    return tools
