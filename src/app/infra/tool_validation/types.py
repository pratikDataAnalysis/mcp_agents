from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class ToolValidator(Protocol):
    """
    Tool-specific validator/normalizer.

    - normalize_args: rewrite common mistakes into canonical shapes (optional)
    - pre_validate: fail fast with structured validation_error (optional)
    """

    def normalize_args(self, tool_name: str, args: dict) -> tuple[dict, bool]: ...

    def pre_validate(self, tool_name: str, args: dict, *, schema_json: Optional[dict]) -> Optional[str]: ...


@dataclass(frozen=True)
class NoopValidator:
    def normalize_args(self, tool_name: str, args: dict) -> tuple[dict, bool]:
        return args, False

    def pre_validate(self, tool_name: str, args: dict, *, schema_json: Optional[dict]) -> Optional[str]:
        return None

