"""
AgentCreator (agent builder only)

Responsibilities:
- Accept AgentDefinition objects (already prepared elsewhere)
- Select tools for each agent based on AgentDefinition.tools (list of tool names)
- Create agents using LangChain `create_agent`
- Return created agents as a mapping: agent_name -> agent instance

This module does NOT:
- Discover MCP tools
- Group tools into agents
- Load agent config
"""

from __future__ import annotations

from typing import Dict, List

from langchain_core.tools import BaseTool
from langchain.agents import create_agent
from src.app.config.settings import settings
from src.app.agents.agent_definitions import AgentDefinition
from src.app.supervisor.state import AgentTaskState

from src.app.logging.logger import setup_logger 
logger = setup_logger(__name__)

class AgentCreator:
    """
    Builds agents from provided agent definitions and a tool list.
    """

    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.model_name = model_name

    def create_agents(
        self,
        agent_definitions: List[AgentDefinition],
        flat_tools: List[BaseTool],
    ) -> Dict[str, object]:
        """
        Create agents for each definition.

        Args:
            agent_definitions: List of AgentDefinition, each containing:
                - name
                - system_message
                - tools (list of tool names)
            tools: Full list of available tools (BaseTool)

        Returns:
            Dict[agent_name, agent_instance]
        """
        if not agent_definitions:
            logger.warning("No agent definitions provided; returning 0 agents")
            return {}
        
        TOOL_REGISTRY = {tool.name: tool for tool in flat_tools}
        agents = []

        for agent_def in agent_definitions:
            agent_tools = []
            # Select tools based on names in agent_def.tools
            for tool_name in agent_def.tools:
                if tool_name not in TOOL_REGISTRY:
                    raise ValueError(
                        f"Agent '{agent_def.name}' references unknown tool '{tool_name}'"
                    )
                agent_tools.append(TOOL_REGISTRY[tool_name])

            try:
                agent = create_agent(
                    model=f"{settings.llm_provider}:{self.model_name}",
                    tools=agent_tools,
                    system_prompt=agent_def.system_message,
                    state_schema=AgentTaskState,
                    name=agent_def.name,
                )
                agents.append(agent)
                logger.info("Agent created | name=%s | tools=%s", agent_def.name, len(agent_tools))
                #self.print_tools(agent_def.name, agent_tools)
            except Exception:
                logger.exception("Failed to create agent | name=%s", agent_def.name)

        logger.info("Agent creation complete | agents=%s", len(agents))
        return agents

    def print_tools(self, name: str, tools: List[BaseTool]) -> None:
        """
        Print the tools in a readable format.
        """
        for tool in tools:
            logger.info("Agent=%s | Tool | name=%s | description=%s", name, tool.name, tool.description)