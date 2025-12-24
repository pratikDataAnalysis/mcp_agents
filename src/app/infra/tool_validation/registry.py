from __future__ import annotations

from src.app.infra.tool_validation.types import NoopValidator, ToolValidator
from src.app.infra.tool_validation.validators.notion_post_page import NotionPostPageValidator


_VALIDATOR_REGISTRY: dict[str, ToolValidator] = {
    "notionApi_API-post-page": NotionPostPageValidator(),
}


def get_validator(tool_name: str) -> ToolValidator:
    return _VALIDATOR_REGISTRY.get(tool_name, NoopValidator())

