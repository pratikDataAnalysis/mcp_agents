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

from typing import Dict, Any

from langgraph_supervisor import create_supervisor
from langchain_core.language_models.chat_models import BaseChatModel

from src.app.logging.logger import setup_logger
from src.app.supervisor.prompts.supervisor_prompt import SUPERVISOR_PROMPT
from src.app.supervisor.tools import get_current_datetime
from src.app.supervisor.structured_response import SupervisorStructuredReply
from typing import TypedDict, List
from langchain_core.messages import BaseMessage

logger = setup_logger(__name__)

class SupervisorState(TypedDict, total=False):
    """
    Minimal state schema required for langgraph-supervisor structured output.

    Why:
    - response_format writes into state["structured_response"]
    - langgraph-supervisor requires that key to exist in the schema
    """
    messages: List[BaseMessage]
    structured_response: dict
    remaining_steps: int


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
        agents: Dict[str, Any],
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

        supervisor = create_supervisor(
            agents=agents,
            model=self.model,
            prompt=prompt,
            tools=[get_current_datetime],
            output_mode="full_history",
            response_format=SupervisorStructuredReply
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
