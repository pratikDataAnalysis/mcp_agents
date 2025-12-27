"""
Worker bootstrap (one-time per process).

Responsibilities:
- Build shared LLM instance
- Discover MCP tools
- Create agent definitions (LLM-based)
- Create agents
- Create supervisor
"""

from __future__ import annotations

from collections import defaultdict
from types import SimpleNamespace
from typing import Any, Dict, List

from src.app.agents.agent_creator import AgentCreator
from src.app.agents.agent_definitions import AgentDefinitions, create_agent_definitions_with_llm
from src.app.config.settings import settings
from src.app.infra.tool_validation import wrap_tool_with_validation
from src.app.logging.logger import setup_logger
from src.app.mcp.mcp_client import MCPClient
from src.app.supervisor.supervisor_creator import SupervisorCreator

logger = setup_logger(__name__)


def build_llm_model(model_name: str | None = None) -> Any:
    """
    Create a shared LLM model instance based on settings.

    Supported (minimal):
    - ollama (ChatOllama)
    - openai (ChatOpenAI)

    NOTE:
    - This is created ONCE per worker process and reused.
    """
    provider = (settings.llm_provider or "ollama").lower()
    resolved_model = model_name or settings.llm_model_name

    logger.info("LLM config | provider=%s | model=%s", provider, resolved_model)

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise ImportError(
                "langchain_ollama is required for llm_provider=ollama. "
                "Install with: pip install -U langchain-ollama"
            ) from exc

        return ChatOllama(model=resolved_model)

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ImportError(
                "langchain_openai is required for llm_provider=openai. "
                "Install with: pip install -U langchain-openai"
            ) from exc

        # OPENAI_API_KEY must be in env for this provider.
        return ChatOpenAI(model=resolved_model)

    raise ValueError(f"Unsupported llm_provider={provider!r}. Use 'ollama' or 'openai'.")


async def load_mcp_tools(mcp_client: MCPClient):
    await mcp_client.connect()
    all_tools = await mcp_client.get_all_tools()

    if not all_tools:
        logger.warning("No MCP tools discovered during bootstrap")
        return [], []

    flat_tools: List[Any] = []
    tagged_tools: List[Any] = []
    tools_with_schema = 0
    tools_without_schema = 0

    for server_name, tools in all_tools.items():
        for tool in tools:
            # Wrap tool so args are validated against args_schema before execution.
            wrapped_tool = wrap_tool_with_validation(tool)
            flat_tools.append(wrapped_tool)

            if getattr(tool, "args_schema", None) is not None:
                tools_with_schema += 1
            else:
                tools_without_schema += 1

            tagged_tools.append(
                SimpleNamespace(
                    tool=wrapped_tool,
                    source_server=server_name,
                    name=getattr(tool, "name", ""),
                    description=getattr(tool, "description", ""),
                    args_schema=getattr(tool, "args_schema", None),
                )
            )

    logger.info("MCP tools loaded | servers=%s | tools=%s", len(all_tools), len(tagged_tools))
    logger.info(
        "Tool schemas | with_args_schema=%s | without_args_schema=%s",
        tools_with_schema,
        tools_without_schema,
    )
    for t in tagged_tools:
        logger.debug("Tool | server=%s | name=%s | description=%s", t.source_server, t.name, t.description)

    return flat_tools, tagged_tools


def build_agent_definitions(flat_tools: List[Any], tagged_tools: List[Any], llm: Any) -> Any:
    """
    Create agent definitions using LLM-based categorization.

    Groups tools by source_server first, then uses LLM to categorize tools within each server
    into specialized agents.
    """
    if not tagged_tools:
        logger.warning("No tagged tools available; agent definitions will be empty")
        return None

    # Group tools by source_server
    tools_by_server = defaultdict(list)
    for tagged in tagged_tools:
        tools_by_server[tagged.source_server].append(tagged.name)

    # Create agent definitions for each server using LLM
    all_agent_defs = []
    for server_name, _tool_names in tools_by_server.items():
        server_tagged_tools = [tagged for tagged in tagged_tools if tagged.source_server == server_name]
        if not server_tagged_tools:
            logger.warning("No tools found for server | server=%s", server_name)
            continue

        server_agent_defs = create_agent_definitions_with_llm(server_tagged_tools, llm, tools_by_server)
        all_agent_defs.extend(server_agent_defs.agents)

    agent_defs = AgentDefinitions(agents=all_agent_defs)
    logger.info("Agent definitions created | count=%s", len(agent_defs.agents))
    for a in agent_defs.agents:
        logger.debug("AgentDef | name=%s | server=%s | tools=%s", a.name, a.source_server, len(a.tools))
    return agent_defs


def build_agents(agent_defs: Any, flat_tools: List[Any]) -> Dict[str, Any]:
    """
    Create agents ONCE using AgentCreator.
    """
    if not agent_defs or not getattr(agent_defs, "agents", None):
        logger.warning("No agent definitions found; no agents will be created")
        return {}

    if not flat_tools:
        logger.warning("No MCP tools found; no agents will be created")
        return {}

    agent_model = settings.llm_model_name
    creator = AgentCreator(model_name=agent_model)
    agents = creator.create_agents(agent_defs.agents, flat_tools)

    logger.info("Agents created | count=%s", len(agents))
    return agents


def build_supervisor(llm: Any, agents: Dict[str, Any], agent_defs: Any) -> Any:
    """
    Create supervisor ONCE using SupervisorCreator.
    """
    if not agents:
        raise ValueError("Cannot create supervisor: agents dict is empty")

    supervisor_creator = SupervisorCreator(model=llm)
    supervisor = supervisor_creator.create(
        agents=agents,
        agent_definitions=agent_defs,
    )

    logger.info("Supervisor ready")
    return supervisor


async def bootstrap_supervisor() -> Any:
    """
    Full bootstrap pipeline (run once per worker process).
    """
    logger.info("Worker bootstrap started")

    # Step 1: LLM (shared)
    llm = build_llm_model(settings.llm_model_name)

    # Step 2: MCP tools (shared)
    mcp_client = MCPClient(config_path=settings.mcp_config_path)
    flat_tools, tagged_tools = await load_mcp_tools(mcp_client)

    logger.info("Bootstrap check | tools=%s", len(tagged_tools))

    # Step 3: Agent definitions
    agent_defs = build_agent_definitions(flat_tools, tagged_tools, llm)

    # Step 4: Agents
    agents = build_agents(agent_defs, flat_tools)

    # Step 5: Supervisor
    supervisor = build_supervisor(llm, agents, agent_defs)

    logger.info(
        "Worker bootstrap complete | tools=%s | agent_defs=%s | agents=%s",
        len(tagged_tools),
        len(getattr(agent_defs, "agents", []) or []) if agent_defs else 0,
        len(agents),
    )

    return supervisor

