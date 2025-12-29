"""
Shared state schema for supervisor + agents.

We use a single state schema so custom handoff tools can carry structured
task instructions to the target agent via graph state.
"""

from __future__ import annotations

from typing import NotRequired, Optional

from langchain.agents import AgentState
from langgraph.prebuilt.chat_agent_executor import AgentStateWithStructuredResponse

class AgentTaskState(AgentState[dict], total=False):
    """State schema for sub-agents created via `langchain.agents.create_agent`."""

    task_instructions: NotRequired[Optional[str]]


class SupervisorTaskState(AgentStateWithStructuredResponse):
    """
    State schema for the supervisor created via `langgraph_supervisor.create_supervisor`.

    NOTE:
    langgraph-supervisor uses LangGraph's prebuilt create_react_agent internally, which
    requires `remaining_steps` in the state schema. AgentStateWithStructuredResponse includes it.
    """

    task_instructions: Optional[str]
