"""
Supervisor factory.

Responsibilities:
- Create and compile a LangGraph Supervisor
- Inject:
  - Pre-created agents
  - Shared LLM model
  - Supervisor prompt (PromptTemplate-based)
  - Supervisor-level tools
"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence

from langgraph_supervisor import create_supervisor
from langchain_core.language_models.chat_models import BaseChatModel

from src.app.logging.logger import setup_logger
from src.app.supervisor.prompts.supervisor_prompt import SUPERVISOR_PROMPT
from src.app.supervisor.tools import get_current_datetime
from src.app.supervisor.memory_tools import memory_get_context
from src.app.supervisor.structured_response import SupervisorStructuredReply
from src.app.supervisor.handoff_tools import create_task_instructions_handoff_tool
from src.app.supervisor.state import SupervisorTaskState

logger = setup_logger(__name__)

class SupervisorCreator:
    """
    Creates and compiles a Supervisor using:
    - Pre-created agents
    - Shared LLM model
    - PromptTemplate-based system prompt
    """

    def __init__(self, model: BaseChatModel):
        """
        Args:
            model: Shared chat model instance (OpenAI, Ollama, etc.)
        """
        self.model = model

    def create(
        self,
        agents: Sequence[Any],
        agent_definitions: Any,
    ) -> Any:
        """
        Create and compile a Supervisor.

        Args:
            agents: Dict mapping agent_name -> compiled agent
            agent_definitions: AgentDefinitions object used to render prompt

        Returns:
            Compiled LangGraph Supervisor
        """
        if not agents:
            raise ValueError("SupervisorCreator.create called with no agents")

        logger.info(
            "Creating Supervisor with agents=%s",
            len(agents),
        )

        prompt = self._build_prompt(agent_definitions)

        # IMPORTANT: langgraph-supervisor treats any provided handoff tools as "custom handoffs"
        # and requires a handoff tool for EVERY sub-agent by agent.name (not by source_server).
        custom_handoff_tools: List[Any] = []
        for a in agents:
            agent_name = getattr(a, "name", None)
            if not agent_name:
                raise ValueError("All agents must have a non-empty name for custom handoff tools")
            custom_handoff_tools.append(
                create_task_instructions_handoff_tool(agent_name=str(agent_name))
            )

        supervisor = create_supervisor(
            agents=agents,
            model=self.model,
            prompt=prompt,
            tools=[get_current_datetime, memory_get_context, *custom_handoff_tools],
            output_mode="last_message",
            response_format=SupervisorStructuredReply,
            state_schema=SupervisorTaskState,
        ).compile()

        logger.info("Supervisor compiled successfully")
        return supervisor

    def _build_prompt(self, agent_definitions: Any) -> str:
        """
        Render the supervisor system prompt using agent definitions.
        """
        if not agent_definitions or not getattr(agent_definitions, "agents", None):
            raise ValueError("Agent definitions missing for supervisor prompt")

        # Include tool list so the supervisor can route based on actual capabilities
        agents_info = "\n".join(
            [
                f"- {agent.name.lower()}: {agent.responsibility} | tools={', '.join(agent.tools)}"
                for agent in agent_definitions.agents
            ]
        )
        rendered_prompt = SUPERVISOR_PROMPT.format(
            agents_info=agents_info
        )

        logger.debug("Supervisor prompt rendered | prompt=%s", rendered_prompt)
        return rendered_prompt
