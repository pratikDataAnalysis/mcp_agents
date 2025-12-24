from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from src.app.infra.tool_validation.types import ToolValidator


@dataclass(frozen=True)
class NotionPostPageValidator(ToolValidator):
    """
    Harden the most common Notion create-page mistakes that cause HTTP 400.
    Minimal normalization + clear preflight failures.
    """

    def normalize_args(self, tool_name: str, args: dict) -> tuple[dict, bool]:
        if tool_name != "notionApi_API-post-page":
            return args, False
        if not isinstance(args, dict):
            return args, False

        changed = False
        out = dict(args)

        # If children accidentally nested under properties, lift it to top-level.
        props = out.get("properties")
        if isinstance(props, dict) and "children" in props and "children" not in out:
            out["children"] = props.get("children")
            props2 = dict(props)
            props2.pop("children", None)
            out["properties"] = props2
            changed = True

        # If agent mistakenly sets properties.type="title", remove it.
        props = out.get("properties")
        if isinstance(props, dict) and props.get("type") == "title":
            props2 = dict(props)
            props2.pop("type", None)
            out["properties"] = props2
            changed = True

        return out, changed

    def pre_validate(self, tool_name: str, args: dict, *, schema_json: Optional[dict]) -> Optional[str]:
        if tool_name != "notionApi_API-post-page":
            return None

        props = args.get("properties")
        if not isinstance(props, dict):
            return json.dumps(
                {
                    "error_type": "validation_error",
                    "source": "local_semantic_validation",
                    "tool": tool_name,
                    "message": "Notion create-page requires properties to be an object (dict).",
                    "schema": schema_json,
                },
                ensure_ascii=False,
            )

        title_val = props.get("title")
        if not isinstance(title_val, dict) or "title" not in title_val:
            return json.dumps(
                {
                    "error_type": "validation_error",
                    "source": "local_semantic_validation",
                    "tool": tool_name,
                    "message": (
                        "Notion create-page title must be shaped as "
                        "{\"properties\":{\"title\":{\"title\":[...rich_text...]}}} "
                        "and children must be a top-level field."
                    ),
                    "schema": schema_json,
                },
                ensure_ascii=False,
            )

        children = args.get("children")
        if isinstance(children, list) and any(isinstance(c, str) for c in children):
            return json.dumps(
                {
                    "error_type": "validation_error",
                    "source": "local_semantic_validation",
                    "tool": tool_name,
                    "message": "Notion create-page children must be an array of block objects (not strings).",
                    "schema": schema_json,
                },
                ensure_ascii=False,
            )

        return None

