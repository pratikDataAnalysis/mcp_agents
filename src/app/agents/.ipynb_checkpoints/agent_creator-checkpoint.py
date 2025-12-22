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

import logging
from typing import Dict, List

from langchain_core.tools import BaseTool
from langchain.agents import create_agent
from src.app.config.settings import settings
from src.app.agents.agent_definitions import AgentDefinition

logger = logging.getLogger(__name__)


class AgentCreator:
    """
    Builds agents from provided agent definitions and a tool list.
    """

    def __init__(self, model_name: str = "gpt-4o-mini"):
        self.model_name = model_name

    def create_agents(
        self,
        agent_definitions: List[AgentDefinition],
        tools: List[BaseTool],
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

        if not tools:
            logger.warning("No tools provided; returning 0 agents")
            return {}

        tool_map: Dict[str, BaseTool] = {t.name: t for t in tools}
        agents: Dict[str, object] = {}

        logger.info(
            "Creating agents | defs=%s | available_tools=%s | model=%s",
            len(agent_definitions),
            len(tools),
            self.model_name,
        )

        for agent_def in agent_definitions:
            # Select tools for this agent
            selected_tools: List[BaseTool] = []
            for tool_name in agent_def.tools:
                tool = tool_map.get(tool_name)
                if tool:
                    selected_tools.append(tool)
                else:
                    logger.warning(
                        "Tool not found for agent | agent=%s | tool=%s",
                        agent_def.name,
                        tool_name,
                    )

            logger.info(
                "Building agent | name=%s | tools=%s",
                agent_def.name,
                len(selected_tools),
            )

            try:
                agent = create_agent(
                    model=f"{settings.llm_provider}:{self.model_name}",
                    tools=selected_tools,
                    system_prompt=agent_def.system_message,
                    name=agent_def.name,
                )
                agents[agent_def.name] = agent
                logger.info("Agent created | name=%s", agent_def.name)
            except Exception:
                logger.exception("Failed to create agent | name=%s", agent_def.name)

        logger.info("Agent creation complete | agents=%s", len(agents))
        return agents
