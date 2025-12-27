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
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from src.app.config.settings import settings

from src.app.logging.logger import setup_logger 
from src.app.agents.prompts.agent_categorization_prompt import AGENT_CATEGORIZATION_PROMPT

logger = setup_logger(__name__)

_POLICY_PACKS_CACHE: Optional[List[Dict[str, Any]]] = None


def _load_policy_packs() -> List[Dict[str, Any]]:
    """
    Load policy pack JSON files once per process.

    Policy packs live in: src/app/agents/policy_packs/*.json
    and are used to inject stable, scalable rules/context into LLM-generated agents
    based on source_server matching.
    """
    global _POLICY_PACKS_CACHE
    if _POLICY_PACKS_CACHE is not None:
        return _POLICY_PACKS_CACHE

    packs_dir = Path(__file__).parent / "policy_packs"
    packs: List[Dict[str, Any]] = []

    if not packs_dir.exists():
        logger.warning("Policy packs dir not found | path=%s", str(packs_dir))
        _POLICY_PACKS_CACHE = []
        return _POLICY_PACKS_CACHE

    for p in sorted(packs_dir.glob("*.json")):
        try:
            packs.append(json.loads(p.read_text(encoding="utf-8")))
        except Exception:
            logger.exception("Failed to load policy pack | path=%s", str(p))

    logger.info("Policy packs loaded | count=%s | path=%s", len(packs), str(packs_dir))
    _POLICY_PACKS_CACHE = packs
    return _POLICY_PACKS_CACHE


def _pack_matches_source_server(pack: Dict[str, Any], source_server: str) -> bool:
    match = pack.get("match") or {}
    servers = match.get("source_servers") or []
    if not isinstance(servers, list):
        return False
    return ("*" in servers) or (source_server in servers)


def _apply_policy_packs(agent: "AgentDefinition") -> List[str]:
    """
    Apply matching policy packs to a single AgentDefinition.
    Returns list of applied pack IDs (for logging).
    """
    applied: List[str] = []
    packs = _load_policy_packs()

    base_msg = agent.system_message or ""
    prepend_chunks: List[str] = []
    append_chunks: List[str] = []

    for pack in packs:
        if not _pack_matches_source_server(pack, agent.source_server):
            continue
        pack_id = str(pack.get("id") or "unknown")
        inject = pack.get("inject") or {}

        pre = inject.get("prepend_system_message")
        if isinstance(pre, str) and pre.strip():
            prepend_chunks.append(pre.strip())

        app = inject.get("append_system_message")
        if isinstance(app, list):
            for line in app:
                if isinstance(line, str) and line.strip():
                    append_chunks.append(line.rstrip())

        applied.append(pack_id)

    # Merge: prepend + original + append
    merged = "\n\n".join([c for c in prepend_chunks if c] + [base_msg.strip()] + [("\n".join(append_chunks)).strip() if append_chunks else ""])
    agent.system_message = _render_placeholders(merged.strip())

    return applied

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

    DEPRECATED: this function is deprecated and will be removed in the future.
    Use create_agent_definitions_with_llm instead.
    thiss is only used when LLM fails to categorize tools and act as a fallback.
    Using this mean updating agent_config.json to have all the tools and their source_server.

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
    logger.info("Creating agent definitions with LLM failed, falling back to source-based grouping")
    logger.info("Creating agent definitions from tool sources | tools=%s", len(wrapped_tools))

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


def create_agent_definitions_with_llm(tagged_tools: List[Any], llm: Any, tools_by_server: Dict[str, List[str]]) -> AgentDefinitions:
    """
    Use LLM to categorize tools from a single source_server into specialized agents.
    
    Input:
      tagged_tools: List of tagged tool objects (with .name, .description, .source_server attributes)
      llm: BaseChatModel instance (ChatOllama, ChatOpenAI, etc.)
      tools_by_server: Dict mapping server names to lists of tool names (for context)
      source_server: The MCP server name these tools belong to
    
    Output:
      AgentDefinitions(agents=[...]) with specialized agents
    
    Behavior:
    - Groups tools by functionality using LLM
    - Creates 3-5 specialized agents per server
    - Each agent gets responsibility and system_message from LLM
    - Falls back to create_agent_definitions_from_source if LLM fails


    NOTE: this function is only used when LLM fails to categorize tools and act as a fallback.
    ** Using this free us from updating agent_config.json to have all the tools and their source_server. **
    """
    logger.info("Creating agent definitions with LLM | tools=%s | max_tools_per_agent=%s", len(tagged_tools), settings.max_tools_per_agent)
    
    if not tagged_tools:
        logger.warning("No tools provided for LLM categorization")
        return AgentDefinitions(agents=[])
    
    # Extract tool information from tagged_tools (they already have name and description)
    tool_info = []
    for tagged in tagged_tools:
        schema_obj = getattr(tagged, "args_schema", None)
        schema_json = None
        # args_schema is typically a Pydantic model class; convert to JSON schema for LLM consumption.
        try:
            if isinstance(schema_obj, type) and issubclass(schema_obj, BaseModel):
                schema_json = schema_obj.model_json_schema()
        except Exception:
            schema_json = None

        tool_info.append({
            "name": tagged.name,
            "description": tagged.description or "",
            "source_server": tagged.source_server or "",
            "args_schema": schema_json,
        })
    
    # Format tool info as JSON string for the prompt
    tool_info_str = json.dumps(tool_info, indent=2)
    
    # Use LangChain PromptTemplate
    prompt = AGENT_CATEGORIZATION_PROMPT.format(
        tool_count=len(tool_info),
        tool_info=tool_info_str,
        max_tools_per_agent=settings.max_tools_per_agent,
    )
    
    try:
        # Use structured output to get AgentDefinitions
        structured_llm = llm.with_structured_output(AgentDefinitions)
        response = structured_llm.invoke(prompt)
        
        # Normalize agent names/source_server, then apply policy packs (stable rules/context) per source_server.
        for agent in response.agents:
            agent.name = _normalize_agent_name(agent.name)
            agent.source_server = agent.source_server or ""
            applied = _apply_policy_packs(agent)
            logger.info(
                "Policy packs applied | agent=%s | source_server=%s | packs=%s",
                agent.name,
                agent.source_server,
                applied,
            )
        
        # Verify all tools are assigned
        assigned_tools = set()
        for agent in response.agents:
            assigned_tools.update(agent.tools)
        
        all_tool_names = {t.name for t in tagged_tools}
        missing_tools = all_tool_names - assigned_tools
        
        if missing_tools:
            logger.warning("LLM did not assign all tools | missing=%s", missing_tools)
            # Add missing tools to the first agent
            if response.agents:
                response.agents[0].tools.extend(list(missing_tools))
        
        logger.info("LLM categorization successful | agents=%s", len(response.agents))
        return response
        
    except Exception as e:
        logger.exception("LLM categorization failed, falling back to source-based grouping | error=%s", str(e))
        # Fallback: tagged_tools already have the right structure, just use them directly
        # NOTE: this fallback is not used as Plan B
        return create_agent_definitions_from_source(tagged_tools)


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
