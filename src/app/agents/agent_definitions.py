"""
Agent Definition Builder (config-driven, source_server based)

Builds AgentDefinitions from wrapped tools.
Each wrapped tool is expected to have:
- name (str)
- source_server (str)  -> which MCP server the tool came from

It then:
- Groups tools by source_server
- Creates AgentDefinitions for use by the supervisor runtime.

Note:
- Agent definitions are now generated via LLM-based tool categorization plus policy packs.
"""

from __future__ import annotations

import json
import os
import re

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
      Responsibility text for the agent.
    system_message:
      System message for the agent.
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


def _tool_info_for_prompt(tagged_tools: List[Any]) -> List[Dict[str, Any]]:
    """
    Convert tagged tools into prompt-ready dicts, including args_schema JSON when available.
    """
    tool_info: List[Dict[str, Any]] = []
    for tagged in tagged_tools:
        schema_obj = getattr(tagged, "args_schema", None)
        schema_json = None
        try:
            if isinstance(schema_obj, type) and issubclass(schema_obj, BaseModel):
                schema_json = schema_obj.model_json_schema()
        except Exception:
            schema_json = None

        tool_info.append(
            {
                "name": tagged.name,
                "description": tagged.description or "",
                "source_server": tagged.source_server or "",
                "args_schema": schema_json,
            }
        )
    return tool_info


def _server_rules_for_prompt(source_server: str, server_cfg: Optional[Dict[str, Any]]) -> str:
    """
    Build a server-scoped rules payload for the LLM prompt.

    Keep this concise and deterministic. If server_cfg is missing, return empty string.
    """
    if not isinstance(server_cfg, dict) or not server_cfg:
        return ""

    desired_agents = server_cfg.get("agents")

    rules_payload = {
        "source_server": source_server,
        "desired_agents": desired_agents,
    }
    return json.dumps(rules_payload, indent=2)


def _invoke_llm_for_agent_defs(llm: Any, prompt: str) -> AgentDefinitions:
    """
    Invoke the LLM using structured output and return AgentDefinitions.
    """
    structured_llm = llm.with_structured_output(AgentDefinitions)
    return structured_llm.invoke(prompt)


def _apply_postprocessing(
    *,
    response: AgentDefinitions,
    source_server: str,
    tagged_tools: List[Any],
) -> AgentDefinitions:
    """
    Normalize output, apply policy packs, and ensure tool coverage.
    """
    # Normalize agent names/source_server, then apply policy packs.
    for agent in response.agents:
        agent.name = _normalize_agent_name(agent.name)
        agent.source_server = agent.source_server or source_server or ""
        applied = _apply_policy_packs(agent)
        logger.debug(
            "Policy packs applied | agent=%s | source_server=%s | packs=%s",
            agent.name,
            agent.source_server,
            applied,
        )

    # Verify all tools are assigned
    assigned_tools: set[str] = set()
    for agent in response.agents:
        assigned_tools.update(agent.tools)

    all_tool_names = {t.name for t in tagged_tools}
    missing_tools = all_tool_names - assigned_tools
    if missing_tools:
        logger.warning("LLM did not assign all tools | source_server=%s | missing=%s", source_server, missing_tools)
        if response.agents:
            response.agents[0].tools.extend(list(missing_tools))

    return response


def create_agent_definitions_with_llm(
    tagged_tools: List[Any],
    llm: Any,
    source_server: str,
    server_cfg: Optional[Dict[str, Any]] = None,
) -> AgentDefinitions:
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
    - If LLM categorization fails, falls back to a single agent containing all tools for the server.
    """
    logger.info(
        "Creating agent definitions with LLM for source_server=%s | with tools=%s | max_tools_per_agent=%s | has_server_cfg=%s",
        source_server,
        len(tagged_tools),
        settings.max_tools_per_agent,
        bool(server_cfg),
    )
    
    if not tagged_tools:
        logger.warning("No tools provided for LLM categorization for source_server=%s", source_server)
        return AgentDefinitions(agents=[])
    
    tool_info = _tool_info_for_prompt(tagged_tools)
    tool_info_str = json.dumps(tool_info, indent=2)
    
    server_rules = _server_rules_for_prompt(source_server, server_cfg)

    prompt = AGENT_CATEGORIZATION_PROMPT.format(
        tool_count=len(tool_info),
        tool_info=tool_info_str,
        max_tools_per_agent=settings.max_tools_per_agent,
        server_rules=server_rules,
    )
    
    try:
        response = _invoke_llm_for_agent_defs(llm, prompt)
        response = _apply_postprocessing(response=response, source_server=source_server, tagged_tools=tagged_tools)
        logger.debug("LLM categorization successful | agents=%s", len(response.agents))
        return response
        
    except Exception as e:
        logger.exception("LLM categorization failed, falling back to source-based grouping | error=%s", str(e))
        return AgentDefinitions(agents=[])

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

        logger.debug(
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
