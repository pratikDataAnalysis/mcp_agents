"""
Agent Definition Builder (config-driven, source_server based)

Builds AgentDefinitions from wrapped tools.
Each wrapped tool is expected to have:
- name (str)
- source_server (str)  -> which MCP server the tool came from

It then:
- Groups tools by source_server
- Creates one AgentDefinition per source_server
- Pulls responsibility + system_message from agent_config.json (keyed by source_server)
"""

from __future__ import annotations

import json
import os
import re

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from pydantic import BaseModel, Field
from src.app.config.settings import settings

from src.app.logging.logger import setup_logger 
logger = setup_logger(__name__)

class AgentDefinition(BaseModel):
    """
    Single agent definition.

    name:
      Stable agent identifier (snake_case recommended).
      Derived from source_server.
    responsibility:
      Sourced from agent_config.json (or safe default).
    system_message:
      Sourced from agent_config.json (or safe default).
    tools:
      List of tool names this agent will have access to.
    source_server:
      The MCP server name this agent maps to.
    """

    name: str = Field(description="Stable agent identifier")
    responsibility: str = Field(description="Agent responsibility")
    system_message: str = Field(description="Agent system message")
    tools: List[str] = Field(description="Tool names assigned to this agent")
    source_server: str = Field(description="Source MCP server for this agent")


class AgentDefinitions(BaseModel):
    agents: List[AgentDefinition] = Field(description="List of agent definitions")


def _normalize_agent_name(source_server: str) -> str:
    """
    Normalize agent name from MCP server name.
    Example: 'notionApi' -> 'notionapi'
    """
    return source_server.replace(" ", "_").replace("-", "_").lower()


def _load_agent_config(agent_config_path: str) -> Dict[str, Dict[str, str]]:
    """
    Load agent config JSON.

    Expected format:
    {
      "agents": {
        "notionApi": {
          "responsibility": "...",
          "system_message": "..."
        }
      }
    }

    IMPORTANT:
    - Keys under "agents" MUST match source_server values exactly.
      Example: source_server="notionApi" -> config key must be "notionApi"
    """
    path = Path(agent_config_path)

    if not path.exists():
        logger.warning("Agent config not found | path=%s (defaults will be used)", agent_config_path)
        return {}

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.exception("Failed to read agent config JSON | path=%s", agent_config_path)
        return {}

    agents = raw.get("agents")
    if not isinstance(agents, dict):
        logger.warning("Invalid agent config format: missing 'agents' object | path=%s", agent_config_path)
        return {}

    logger.debug("Agent config loaded | path=%s | agents=%s | keys=%s", agent_config_path, len(agents), list(agents.keys()))
    return agents


def create_agent_definitions_from_source(wrapped_tools: List[Any]) -> AgentDefinitions:
    """
    Build AgentDefinitions by grouping tools by their source_server.

    Input:
      wrapped_tools: List of tool wrappers/namespaces that include:
        - .name
        - .source_server

    Output:
      AgentDefinitions(agents=[...])

    Behavior:
    - One agent per source_server
    - Tools assigned to that agent are the tools from that server
    - responsibility/system_message pulled from agent_config.json using source_server key
    - If config missing for a server, safe defaults are used
    """
    logger.debug("Creating agent definitions from tool sources | tools=%s", len(wrapped_tools))

    agent_cfg_map = _load_agent_config(settings.agent_config_path)

    # 1. Group wrapped tools by server
    tools_by_server = defaultdict(list)
    for wrapped in wrapped_tools:
        tools_by_server[wrapped.source_server].append(wrapped)

    agent_defs = []
    for server_name, tools in tools_by_server.items():
        cfg = agent_cfg_map.get(server_name, {})
        if not cfg:
            logger.warning("No agent config found for server | server=%s (using defaults)", server_name)
            cfg = {
                "responsibility": f"Handle operations for server '{server_name}'.",
                "system_message": (
                    f"You operate as the {server_name} agent. "
                    f"You handle requests using these tools: {', '.join(tool_names)}. "
                    "Use only the listed capabilities and ask for clarification if a request is outside them."
                )
            }

        # 2. Render system message placeholders
        system_message = _render_placeholders(cfg.get("system_message"))

        agent_name = _normalize_agent_name(server_name)
        tool_names = [t.name for t in tools]

        agent_defs.append(
            AgentDefinition(
                name=agent_name,
                responsibility=cfg.get("responsibility"),
                system_message=system_message,
                tools=tool_names,
                source_server=server_name,
            )
        )
    
    # 3. Return AgentDefinitions (not raw list)
    return AgentDefinitions(agents=agent_defs)


_TEMPLATE_RE = re.compile(r"\{\{([A-Z0-9_]+)\}\}")

def _resolve_key_from_settings(key: str) -> str | None:
    """
    Resolve a placeholder key using settings first, then env fallback.

    We try a few variants to stay flexible:
    - settings.NOTES_PARENT_PAGE_ID
    - settings.notes_parent_page_id
    - os.getenv("NOTES_PARENT_PAGE_ID")
    """
    # 1) direct attribute (uppercase)
    if hasattr(settings, key):
        val = getattr(settings, key)
        if val:
            return str(val)

    # 2) snake_case attribute
    snake = key.lower()
    if hasattr(settings, snake):
        val = getattr(settings, snake)
        if val:
            return str(val)

    # 3) env fallback
    env_val = os.getenv(key)
    if env_val:
        return env_val

    return None


def _render_placeholders(text: str) -> str:
    """
    Render {{KEY}} placeholders using settings.py (preferred) then env.

    If a placeholder cannot be resolved, we keep it unchanged and log a warning.
    """
    if not text:
        return text

    def replacer(match: re.Match) -> str:
        key = match.group(1)
        val = _resolve_key_from_settings(key)
        if not val:
            logger.warning(
                "Prompt placeholder unresolved | key=%s",
                key,
            )
            return match.group(0)  # keep {{KEY}} as-is

        logger.info(
            "Prompt placeholder rendered | key=%s",
            key,
        )
        return val

    rendered = _TEMPLATE_RE.sub(replacer, text)

    # Helpful visibility: warn if any placeholders remain
    if _TEMPLATE_RE.search(rendered):
        logger.warning(
            "Prompt still contains unresolved placeholders after rendering"
        )

    return rendered
