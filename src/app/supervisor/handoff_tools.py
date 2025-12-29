from __future__ import annotations

from textwrap import dedent
from typing import Annotated, Optional

from langchain.tools import tool
from langchain_core.messages import ToolMessage
from langchain_core.tools import BaseTool, InjectedToolCallId
from langgraph.prebuilt import InjectedState
from langgraph.types import Command
from langgraph_supervisor.handoff import METADATA_KEY_HANDOFF_DESTINATION


def _normalize_agent_name(agent_name: str) -> str:
    """Convert an agent name to a valid tool name format (snake_case)."""
    return agent_name.replace(" ", "_").lower()


def create_task_instructions_handoff_tool(
    *,
    agent_name: str,
    name: Optional[str] = None,
    description: Optional[str] = None,
) -> BaseTool:
    """Create a tool that transfers control to another agent with specific task instructions."""
    if name is None:
        name = f"transfer_to_{_normalize_agent_name(agent_name)}"
    if description is None:
        description = f"Ask agent '{agent_name}' for help"

    @tool(name, description=description)
    def handoff_to_agent(
        task_instructions: Annotated[
            str,
            dedent(
                """
                Specify EXACTLY what this agent should do, what data they should retrieve,
                and what output you expect back. Include any specific parameters or constraints
                that will help the agent complete the task successfully.
                """
            ).strip(),
        ],
        state: Annotated[dict, InjectedState],
        tool_call_id: Annotated[str, InjectedToolCallId],
    ):
        tool_message = ToolMessage(
            content=dedent(
                f"""
                Successfully transferred to {agent_name}.

                [INSTRUCTIONS TO FOLLOW]: {task_instructions}
                """
            ).strip(),
            name=name,
            tool_call_id=tool_call_id,
            response_metadata={METADATA_KEY_HANDOFF_DESTINATION: agent_name},
        )

        messages = state["messages"]
        return Command(
            goto=agent_name,
            graph=Command.PARENT,
            update={
                "messages": messages + [tool_message],
                "task_instructions": task_instructions,
            },
        )

    handoff_to_agent.metadata = {METADATA_KEY_HANDOFF_DESTINATION: agent_name}
    return handoff_to_agent