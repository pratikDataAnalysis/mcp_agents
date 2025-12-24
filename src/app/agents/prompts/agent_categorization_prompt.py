from langchain_core.prompts import PromptTemplate

AGENT_CATEGORIZATION_PROMPT = PromptTemplate(
    input_variables=["tool_count", "tool_info"],
    template="""
You are an expert in designing multi-agent systems. I have a collection of {tool_count} tools from MCP servers that I want to organize into logical agent groups.

Each tool has a name, description, source_server it belongs to, and may include an args_schema (tool argument schema).
Here are the available tools:
{tool_info}

IMPORTANT: I want you to analyze these tools and group them into logical specialized agents based on related functionality and purpose. 
Focus on creating broader categories that group related functionality together.
Each group should be a single agent, make sure no agent to have more than 5 tools at maximum, if it has more than 5 tools, you need to create more agents.

CRITICAL RELIABILITY REQUIREMENT:
- Tool calls can fail due to invalid argument shapes (schema/validation errors).
- When a tool call fails with a validation error, the agent MUST consult that tool's args_schema (if provided in tool_info) and fix the request arguments.
- The agent MUST NOT retry with the same invalid payload repeatedly.
- The agent should retry the corrected tool call once.

For each agent, provide:
1. A descriptive name, make sure name have prefix from their source_server (snake_case, e.g., "notion_pages", "notion_databases")
2. A clear responsibility statement (define what kind of tasks this agent can do, not more than 2 sentences)
3. A concise system message (2-3 sentences) written in SECOND-PERSON perspective (e.g., "You manage Notion pages..." NOT "I manage Notion pages...").
   - The system message MUST include a rule about using args_schema to repair tool calls when validation fails (and retry only once).
4. A list of tool names this agent should have access to.
5. Source_server it belong to.

The goal is to create specialized agents that each handle a specific domain of operations, rather than having one agent with too many tools that might get confused.

Make sure every tool is assigned to exactly one agent, and the groupings are logical based on related functionality.
""".strip(),
)
