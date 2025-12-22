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

    # 1) Group tools by source_server
    grouped: Dict[str, List[Any]] = {}
    missing_source = 0
    missing_name = 0

    for wt in wrapped_tools:
        source = getattr(wt, "source_server", None)
        tool_name = getattr(wt, "name", None)

        if not source:
            missing_source += 1
            logger.warning("Tool missing source_server; skipping | tool=%s", tool_name or "?")
            continue
        if not tool_name:
            missing_name += 1
            logger.warning("Tool missing name; skipping | source_server=%s", source)
            continue

        grouped.setdefault(str(source), []).append(wt)

    logger.debug(
        "Tool grouping complete | groups=%s | missing_source=%s | missing_name=%s",
        len(grouped),
        missing_source,
        missing_name,
    )

    if not grouped:
        logger.warning("No tools had a valid source_server; returning 0 agent definitions")
        return AgentDefinitions(agents=[])

    # 2) Build one AgentDefinition per source_server
    agents: List[AgentDefinition] = []

    for source_server, items in grouped.items():
        tool_names = [getattr(i, "name") for i in items if getattr(i, "name", None)]
        agent_name = _normalize_agent_name(source_server)

        # 3) Pull config by source_server (NOT agent_name)
        cfg = agent_cfg_map.get(source_server)

        if cfg:
            responsibility = cfg.get("responsibility") or f"Handle operations for server '{source_server}'."
            system_message = cfg.get("system_message") or ""
            logger.debug("Using agent config | source_server=%s | agent_name=%s", source_server, agent_name)
        else:
            responsibility = f"Handle operations for server '{source_server}'."
            system_message = (
                f"You operate as the {source_server} agent. "
                f"You handle requests using these tools: {', '.join(tool_names)}. "
                "Use only the listed capabilities and ask for clarification if a request is outside them."
            )
            logger.warning("No config found for source_server '%s'; using defaults", source_server)

        agents.append(
            AgentDefinition(
                name=agent_name,
                responsibility=responsibility,
                system_message=system_message,
                tools=tool_names,
                source_server=source_server,
            )
        )

        logger.info(
            "AgentDefinition created | source=%s | name=%s | tools=%s",
            source_server,
            agent_name,
            len(tool_names),
        )

    logger.info("Agent definitions created successfully | agents=%s", len(agents))
    return AgentDefinitions(agents=agents)
