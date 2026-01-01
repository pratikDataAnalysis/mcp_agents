"""
Tool validation wrapper.

Wraps LangChain BaseTool instances to:
- normalize common request mistakes (tool-specific)
- validate args against tool.args_schema (if present)
- optionally apply semantic preflight validation (tool-specific)
- normalize Notion HTTP validation errors to a stable error_type=validation_error payload
"""

from __future__ import annotations

import json
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from pydantic import BaseModel, ConfigDict, PrivateAttr, ValidationError

from src.app.infra.tool_validation.notion_http import (
    log_normalized_notion_error,
    normalize_notion_http_validation_error,
)
from src.app.infra.tool_validation.registry import get_validator
from src.app.infra.tool_execution_tracker import record_tool_result
from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)


def _is_pydantic_model(model: Any) -> bool:
    try:
        return isinstance(model, type) and issubclass(model, BaseModel)
    except Exception:
        return False


class ValidatingTool(BaseTool):
    """
    Transparent wrapper around an existing tool.

    - Keeps same name/description.
    - Validates args against args_schema when available.
    - Adds tool-specific normalization + semantic checks via registry.
    - Normalizes Notion HTTP 400 validation_error responses into a stable format.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    _inner: BaseTool = PrivateAttr()
    _logged_once: bool = PrivateAttr(default=False)

    def __init__(self, inner: BaseTool):
        super().__init__(
            name=inner.name,
            description=getattr(inner, "description", "") or "",
            args_schema=getattr(inner, "args_schema", None),
            tags=getattr(inner, "tags", None),
            metadata=getattr(inner, "metadata", None),
            handle_tool_error=getattr(inner, "handle_tool_error", False),
            handle_validation_error=getattr(inner, "handle_validation_error", False),
        )
        self._inner = inner

    def _schema_json(self) -> Optional[dict]:
        schema_model: Optional[Type[BaseModel]] = self.args_schema if _is_pydantic_model(self.args_schema) else None
        if not schema_model:
            return None
        try:
            return schema_model.model_json_schema()
        except Exception:
            return None

    def _format_schema_validation_error(self, err: ValidationError, *, args: dict) -> str:
        schema_json = self._schema_json()
        payload = {
            "error_type": "validation_error",
            "source": "local_schema_validation",
            "tool": self.name,
            "message": "Tool arguments failed schema validation. Fix args and retry once.",
            "input_args": args,
            "validation_errors": err.errors(),
            "schema": schema_json,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _validate_or_none(self, args: dict) -> Optional[str]:
        schema_model: Optional[Type[BaseModel]] = self.args_schema if _is_pydantic_model(self.args_schema) else None

        if not self._logged_once:
            logger.info(
                "Tool validation wrapper active | tool=%s | has_args_schema=%s",
                self.name,
                bool(schema_model),
            )
            self._logged_once = True

        # Semantic preflight validation (tool-specific)
        validator = get_validator(self.name)
        schema_json = self._schema_json()
        maybe_semantic_err = validator.pre_validate(self.name, args, schema_json=schema_json)
        if maybe_semantic_err is not None:
            logger.warning("Tool semantic validation failed | tool=%s", self.name)
            return maybe_semantic_err

        if not schema_model:
            logger.debug("Tool schema validation skipped (no args_schema) | tool=%s", self.name)
            return None

        logger.debug("Tool schema validation start | tool=%s", self.name)
        try:
            schema_model.model_validate(args)
        except ValidationError as e:
            logger.warning("Tool schema validation failed | tool=%s | errors=%s", self.name, e.errors())
            return self._format_schema_validation_error(e, args=args)

        logger.debug("Tool schema validation ok | tool=%s", self.name)
        return None

    def _run(self, **kwargs: Any) -> Any:
        validator = get_validator(self.name)
        norm_kwargs, changed = validator.normalize_args(self.name, kwargs)
        if changed:
            logger.warning("Tool args normalized | tool=%s", self.name)

        maybe_err = self._validate_or_none(norm_kwargs)
        if maybe_err is not None:
            return maybe_err

        result = self._inner.invoke(norm_kwargs)
        normalized = normalize_notion_http_validation_error(self.name, result)
        if normalized is not None:
            log_normalized_notion_error(self.name, normalized)
            record_tool_result(name=self.name, result=normalized)
            return normalized
        record_tool_result(name=self.name, result=result)
        return result

    async def _arun(self, **kwargs: Any) -> Any:
        validator = get_validator(self.name)
        norm_kwargs, changed = validator.normalize_args(self.name, kwargs)
        if changed:
            logger.warning("Tool args normalized | tool=%s", self.name)

        maybe_err = self._validate_or_none(norm_kwargs)
        if maybe_err is not None:
            return maybe_err

        result = await self._inner.ainvoke(norm_kwargs)
        normalized = normalize_notion_http_validation_error(self.name, result)
        if normalized is not None:
            log_normalized_notion_error(self.name, normalized)
            record_tool_result(name=self.name, result=normalized)
            return normalized
        record_tool_result(name=self.name, result=result)
        return result


def wrap_tool_with_validation(tool: BaseTool) -> BaseTool:
    return ValidatingTool(tool)

