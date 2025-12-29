from langchain_core.prompts import PromptTemplate

AGENT_CATEGORIZATION_PROMPT = PromptTemplate(
    input_variables=["tool_count", "tool_info", "max_tools_per_agent", "server_rules"],
    template="""
You are an expert in designing multi-agent systems. I have a collection of {tool_count} tools from MCP servers that I want to organize into logical agent groups.

SERVER-SPECIFIC RULES (STRICT, if provided you MUST follow them):
{server_rules}

STRICT RULES WHEN server_rules IS PROVIDED:
- Treat server_rules as the PRIMARY SOURCE OF TRUTH for agent categorization.
- If server_rules includes desired_agents:
  - You MUST create agents with EXACTLY those agent names (no renaming).
  - You MUST assign the listed tools to the specified agent (do not move them to other agents).
  - You MUST NOT omit any listed tool that exists in tool_info.
  - If a tool listed in desired_agents does NOT exist in tool_info, you MUST ignore it (you cannot invent tools) and proceed.
- If server_rules includes blacklisted_tools:
  - You MUST NOT assign any tool in blacklisted_tools to any agent.
- You MUST NOT invent tool names. Every tool you assign MUST come from tool_info.
- You MAY create additional agents ONLY for tools that are present in tool_info but not covered by desired_agents
  (or when server_rules is empty / not provided). Use ONE extra agent named "<source_server>_misc" for leftovers.

Each tool has a name, description, source_server it belongs to, and may include an args_schema (tool argument schema).
Here are the available tools:
{tool_info}

IMPORTANT: You MUST group these tools into specialized agents based on functionality and purpose.
HARD CONSTRAINTS:
- Each tool MUST be assigned to exactly ONE agent (no omissions, no duplicates).
- NO TOOL MAY BE LEFT UNASSIGNED for any reason.
- Each agent MUST have at most {max_tools_per_agent} tools. If adding a tool would exceed this limit, you MUST create another agent.

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

IMPORTANT ROUTING SUPPORT:
- Your grouping must make routing unambiguous.
- For "save/create note/page" style user requests, ensure there is an obvious "pages/notes" agent that contains the create/write tool(s) needed for page creation.
- For "search/find" style user requests, ensure there is an obvious agent that contains the search/read tool(s).
""".strip(),
)
