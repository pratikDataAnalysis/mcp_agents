# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Notion-Play** is a multi-agent AI system that receives WhatsApp messages (including voice notes) via Twilio, routes them through a Supervisor Agent (LangGraph/LangChain), and executes actions via MCP servers (Notion, Zoom, etc.). The architecture is event-driven using Redis Streams, with separate processes for ingress, execution, and delivery.

### Key Features
- **Event-driven architecture** using Redis Streams
- **MCP-first design** - tools come from MCP servers, not hardcoded integrations
- **Supervisor pattern** - central Supervisor decides which agent handles each message
- **Asynchronous by default** - no blocking requests, safe under high load
- **Source-agnostic** - same pipeline works for WhatsApp, Slack, Web, etc.
- **Voice note support** - WhatsApp voice messages are transcribed via OpenAI Whisper
- **Multi-language support** - automatic language detection and translation to English for routing
- **Redis-backed memory** - user profiles and event history for continuity across conversations

## Running the Application

The application requires **4 concurrent processes** in separate terminals:

### 1. Start Redis Server
```bash
redis-server
# Verify: redis-cli ping (should return PONG)
```

### 2. Start FastAPI Ingress (Terminal 1)
```bash
./run.sh
# Starts uvicorn on port 8000 (or PORT=8001 ./run.sh)
# Receives WhatsApp webhooks and publishes to Redis Stream
```

### 3. Start Worker Service (Terminal 2)
```bash
./run_worker.sh
# Bootstrap phase: loads MCP tools, creates agents, creates supervisor (ONCE)
# Runtime phase: consumes from inbound stream, invokes supervisor, publishes to outbound stream
```

### 4. Start Dispatcher Service (Terminal 3)
```bash
./run_dispatcher.sh
# Consumes from outbound stream and delivers responses via Twilio WhatsApp API
```

### 5. Expose Webhook (Terminal 4)
```bash
cloudflared tunnel --url http://localhost:8000
# Configure Twilio webhook: https://<random>.trycloudflare.com/webhooks/whatsapp/inbound
```

## Development Commands

### Testing
```bash
# Run all tests
pytest

# Run specific test file
pytest src/tests/test_smoke.py

# Run with verbose output
pytest -v
```

### Redis Management
```bash
# Check Redis status
redis-cli ping

# Kill Redis process on port 6379
lsof -nP -iTCP:6379 -sTCP:LISTEN
kill -9 <PID>

# View stream messages
redis-cli XREAD COUNT 10 STREAMS inbound_messages 0-0
redis-cli XREAD COUNT 10 STREAMS outbound_messages 0-0

# View consumer groups
redis-cli XINFO GROUPS inbound_messages
redis-cli XINFO GROUPS outbound_messages

# View memory keys (user profiles and events)
redis-cli --scan --pattern 'memory:user:*'
redis-cli GET 'memory:user:<user_id>:profile'
redis-cli LRANGE 'memory:user:<user_id>:events' 0 -1
```

### Kill Running Processes
```bash
# Kill FastAPI server
pkill -f "uvicorn.*src.app.main"

# Kill worker
pkill -f "src.app.infra.redis.worker"

# Kill dispatcher
pkill -f "src.app.dispatchers.outbound_dispatcher"
```

## Architecture

### High-Level Flow
```
User → WhatsApp (Twilio) → FastAPI Ingress → Redis Stream (inbound_messages)
  → Worker (STT if audio → Language Detection → Supervisor → Agents → MCP Tools)
  → Redis Stream (outbound_messages) → Dispatcher → Twilio WhatsApp API → User
```

### Core Design Principles

1. **Separation of Concerns**: Ingress ≠ Execution ≠ Delivery. Each layer evolves independently.
2. **Asynchronous by Default**: No blocking requests. Redis Streams provide backpressure.
3. **Agent-First Design**: Logic lives in agents, not routes. Supervisor decides, not hardcoded rules.
4. **Source Agnostic**: WhatsApp is just one input. Same pipeline works for API, Slack, Web, etc.
5. **MCP-First Architecture**: Tools come from MCP servers. Agents consume tools; they don't manage connections.

### Bootstrap Process (Worker Only, One-Time)

The worker service (`run_worker.sh`) performs a **one-time bootstrap** when it starts:

1. **Build LLM Model** (`bootstrap.py:build_llm_model`): Creates shared ChatOpenAI or ChatOllama instance
2. **Load Server Agent Map** (`bootstrap.py:_load_server_agent_map`): Loads per-server configuration from `server_agent_map.json` (blacklisted tools, agent definitions)
3. **Load MCP Tools** (`bootstrap.py:load_mcp_tools`):
   - Connects to MCP servers defined in `mcp_configs/mcp_servers.json`
   - Discovers tools from each server (stdio or HTTP transports)
   - Applies blacklist filtering per server
   - Wraps tools with validation (`tool_validation/wrapper.py`)
   - Tags tools with `source_server` metadata
4. **Load Local Tools** (`bootstrap.py:load_local_tools`): Loads non-MCP tools (language detection, TTS, memory)
5. **Create Agent Definitions** (`bootstrap.py:build_agent_definitions`):
   - Groups tools by `source_server`
   - Uses **LLM-based categorization** (`agent_definitions.py:create_agent_definitions_with_llm`) to organize tools into specialized agents
   - Can create multiple agents per server (e.g., "notion_reader", "notion_writer")
   - Applies policy packs per server (e.g., Notion contracts with parent page ID injection)
   - Each agent gets: name, responsibility, system_message, and list of tool names
6. **Create Agents** (`agent_creator.py:create_agents`):
   - For each agent definition, selects tools and creates a LangChain agent
   - Applies `SummarizationMiddleware` if enabled (controls token growth)
7. **Create Supervisor** (`supervisor_creator.py:create`):
   - Uses `langgraph_supervisor.create_supervisor` to create supervisor
   - Injects supervisor-level tools (datetime, memory, custom handoff tools)
   - Renders supervisor prompt with agent capabilities

After bootstrap, the worker runs indefinitely processing messages from the Redis Stream.

### Message Processing Flow (Worker Runtime)

For each message consumed from `inbound_messages`:

1. **Consume Message** from Redis Stream using consumer group
2. **Pre-Supervisor Processing** (`pre_supervisor.py:prepare_for_supervisor`):
   - If message has audio media: download from Twilio and transcribe using Whisper STT
   - Detect language and translate to English if needed (via `localAudio_detect_and_translate_to_english`)
   - Build supervisor input envelope (JSON with metadata: original_text, english_text, detected_language, inbound_has_audio)
3. **Memory Prefetch** (`worker.py:_process_message`):
   - Fetch user profile and recent events from Redis (`memory_store.py`)
   - Inject compact memory context into supervisor envelope (avoids extra LLM call)
4. **Invoke Supervisor** (`supervisor.ainvoke`):
   - Supervisor analyzes request using custom handoff tools for routing
   - Routes to appropriate agent based on intent and tool capabilities
   - Agent executes using validated MCP tools
   - Returns structured response (`SupervisorStructuredReply`) with status and actions
5. **Extract Reply** (`output_assembler.py:extract_reply_text`): Parse final user-facing response from supervisor result
6. **Generate Audio Reply** (optional, if `inbound_has_audio=true`): Synthesize TTS reply using OpenAI and serve via public URL
7. **Write Memory** (conditional): Only write to Redis if `status=success` AND grounded (tool execution succeeded via `tool_execution_tracker`)
8. **Publish to Outbound Stream**: Send reply to `outbound_messages` stream with metadata
9. **ACK Message**: Only after successful outbound publish (ensures at-least-once delivery)

### Agent Creation System

Agents are **dynamically created** during worker bootstrap using LLM-based categorization:

- **Input**: List of tools tagged with `source_server` (e.g., "notionApi", "zoom", "localAudio")
- **Process** (`agent_definitions.py:create_agent_definitions_with_llm`):
  - Prompt LLM to analyze tools (name, description, args_schema) and group them into specialized agents
  - LLM decides: agent name, responsibility description, which tools belong to which agent
  - Can split one server's tools into multiple agents (e.g., "notion_reader", "notion_writer")
  - Server-specific rules from `server_agent_map.json` guide categorization (when present)
  - Policy packs (`agents/policy_packs/*.json`) inject server-specific contracts and behavior rules
- **Output**: List of `AgentDefinition` objects with name, system_message, responsibility, tools list
- **Override**: Optional `server_agent_map.json` can provide per-server config (blacklisted tools, explicit agent definitions)

This approach makes adding new MCP servers trivial: just add to `mcp_servers.json` and restart worker.

### Tool Validation & Correctness

All tools are wrapped with validation to ensure correct request shapes and prevent token overflow:

**Validation Flow** (`tool_validation/wrapper.py`):
1. **Normalize Args** (tool-specific fixups, e.g., lift `children` out of `properties` for Notion)
2. **Pre-Validate** (semantic checks for common shape mistakes)
3. **Args Schema Validation** (validate against Pydantic `args_schema` when present)
4. **Execute Tool** (actual MCP server call)
5. **Normalize Errors** (convert Notion HTTP 400 validation errors to consistent format with `repeat_count`)

**Tool Output Trimming** (`tool_output_trimmer.py`):
- Truncates large tool outputs (especially Notion search results)
- Configurable via `TOOL_TRIM_NOTION_MAX_ITEMS` and `TOOL_TRIM_NOTION_MAX_CHARS`

**Agent Middleware** (`SummarizationMiddleware`):
- Automatically summarizes agent history when token count exceeds threshold
- Configurable via `AGENT_SUMMARIZATION_TRIGGER_TOKENS` and `AGENT_SUMMARIZATION_KEEP_MESSAGES`

### Memory System (Redis-Backed)

The system maintains per-user conversation memory in Redis for continuity:

**Memory Stores**:
- **User Profile** (`memory:user:<user_id>:profile`): JSON with schema, user_id, last_seen_at, detected_language, TTL=180 days
- **Recent Events** (`memory:user:<user_id>:events`): Redis LIST of recent interactions (original_text, english_text, reply_text, actions), TTL=30 days, max 15 items

**Memory Prefetch Optimization**:
- Worker fetches memory BEFORE invoking supervisor to avoid extra LLM call
- Compact memory context injected into supervisor envelope (5 recent events, truncated text)

**Deterministic Write Policy**:
- Memory writes ONLY when `status=success` AND grounded tool execution detected
- Grounding uses `tool_execution_tracker` (contextvars-based) to detect successful non-internal tool calls
- Prevents hallucinated memories and generic LLM-only replies from polluting history

**Schema Versioning**:
- Each document includes `schema` field (e.g., `user_profile_v1`, `memory_event_v1`)
- Bounded history with LPUSH + LTRIM

## Key Files & Directories

### Configuration
- `.env`: Environment variables (Twilio, OpenAI, Redis, MCP tokens)
- `mcp_configs/mcp_servers.json`: MCP server definitions (Notion, Zoom)
- `src/app/config/settings.py`: Pydantic settings with defaults and env loading
- `src/app/agents/server_agent_map.json`: Per-server agent configuration (blacklist, explicit definitions)
- `src/app/agents/policy_packs/*.json`: Server-specific policy packs (Notion contracts, behavior rules)

### Bootstrap & Execution
- `src/app/infra/redis/bootstrap.py`: Worker bootstrap pipeline (LLM, MCP tools, agents, supervisor)
- `src/app/infra/redis/worker.py`: Redis Stream consumer and message processor
- `src/app/mcp/mcp_client.py`: MCP server connection manager (stdio and HTTP transports)

### Agent System
- `src/app/agents/agent_creator.py`: Builds LangChain agents from definitions
- `src/app/agents/agent_definitions.py`: LLM-based tool categorization and agent creation
- `src/app/agents/prompts/agent_categorization_prompt.py`: Prompt for LLM categorization

### Supervisor
- `src/app/supervisor/supervisor_creator.py`: Creates and compiles LangGraph supervisor
- `src/app/supervisor/prompts/supervisor_prompt.py`: System prompt template for supervisor
- `src/app/supervisor/tools.py`: Supervisor-level tools (datetime, etc.)
- `src/app/supervisor/handoff_tools.py`: Custom handoff tools for agent routing
- `src/app/supervisor/memory_tools.py`: Memory read/write tools (usually bypassed by prefetch)
- `src/app/supervisor/state.py`: Supervisor and agent state schemas
- `src/app/supervisor/structured_response.py`: Structured response format (`SupervisorStructuredReply`)

### Runtime & Processing
- `src/app/runtime/pre_supervisor.py`: Pre-supervisor processing (audio STT, language detection, envelope construction)
- `src/app/runtime/output_assembler.py`: Extract reply text from supervisor result

### Infrastructure
- `src/app/infra/redis/client.py`: Redis connection manager
- `src/app/infra/redis/memory_store.py`: User memory persistence layer
- `src/app/infra/redis/stream_publisher.py`: Inbound stream publisher
- `src/app/infra/redis/stream_outbound_publisher.py`: Outbound stream publisher
- `src/app/infra/tool_validation/`: Tool validation and wrapping logic
  - `wrapper.py`: ValidatingTool wrapper (normalize → validate → execute → normalize errors)
  - `registry.py`: Tool-name → validator mapping
  - `validators/notion_post_page.py`: Notion-specific normalization and validation
  - `notion_http.py`: Notion HTTP 400 error normalization with repeat detection
- `src/app/infra/tool_output_trimmer.py`: Token-safe tool output truncation
- `src/app/infra/tool_execution_tracker.py`: Tracks tool executions for grounding detection
- `src/app/infra/langsmith.py`: LangSmith tracing setup
- `src/app/infra/openai_stt.py`: OpenAI STT client (urllib-based multipart upload)
- `src/app/infra/http_ssl.py`: SSL reliability using certifi (macOS/Homebrew Python fix)

### Ingress & Delivery
- `src/app/api/whatsapp_webhook.py`: FastAPI endpoint for Twilio webhooks
- `src/app/api/media.py`: Media URL serving for TTS audio files
- `src/app/dispatchers/outbound_dispatcher.py`: Outbound Redis Stream consumer
- `src/app/dispatchers/channels/twilio_whatsapp_sender.py`: Twilio API client

### Audio Processing
- `src/app/audio/twilio_stt.py`: Whisper STT integration for Twilio audio (Basic Auth download)
- `src/app/audio/media.py`: Twilio media extraction and public URL building
- `src/app/mcp/tools/language_tools.py`: Language detection, translation, TTS tools (local MCP tools)

### Local MCP Tools
- `src/app/mcp/tools/__init__.py`: Local tool aggregation (`get_local_tools()`)
- `src/app/mcp/tools/language_tools.py`: Language detection, translation (DeepL), TTS (OpenAI)
- `src/app/mcp/tools/tagging.py`: Tool tagging utilities

## Environment Variables

Required in `.env`:

```bash
# Twilio
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# OpenAI (LLM + STT/TTS)
OPENAI_API_KEY=your_openai_api_key
LLM_PROVIDER=openai
LLM_MODEL_NAME=gpt-4o-mini

# MCP Server Tokens
NOTION_MCP_ACCESS_TOKEN=your_notion_integration_token

# Redis (optional, defaults to localhost:6379)
REDIS_HOST=localhost
REDIS_PORT=6379

# Audio Reply (optional, requires public HTTPS URL for Twilio)
REPLY_WITH_AUDIO_WHEN_INBOUND_HAS_AUDIO=true
MEDIA_PUBLIC_BASE_URL=https://your-ngrok-url.com
TTS_MODEL_NAME=tts-1
TTS_VOICE=alloy
TTS_FORMAT=mp3

# STT Configuration (optional)
OPENAI_STT_FORCE_ENGLISH=true
OPENAI_TRANSCRIPTIONS_URL=https://api.openai.com/v1/audio/transcriptions
OPENAI_TRANSLATIONS_URL=https://api.openai.com/v1/audio/translations

# LangSmith Tracing (optional, highly recommended for debugging)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=notion-play

# Agent Middleware (optional, defaults shown)
AGENT_SUMMARIZATION_ENABLED=true
AGENT_SUMMARIZATION_TRIGGER_TOKENS=3000
AGENT_SUMMARIZATION_KEEP_MESSAGES=12
AGENT_SUMMARIZATION_MODEL_NAME=gpt-4o-mini

# Tool Output Trimming (optional, defaults shown)
TOOL_OUTPUT_TRIMMING_ENABLED=true
TOOL_TRIM_NOTION_MAX_ITEMS=5
TOOL_TRIM_NOTION_MAX_CHARS=4000

# Memory Configuration (optional, defaults shown)
MEMORY_CONVERSATION_TTL_SECONDS=43200  # 12 hours
MEMORY_USER_PROFILE_TTL_SECONDS=15552000  # 180 days
MEMORY_USER_EVENTS_TTL_SECONDS=2592000  # 30 days
MEMORY_USER_EVENTS_MAX_ITEMS=15

# Notion Notes Configuration (optional)
NOTES_PARENT_PAGE_ID=your_notion_page_id  # Where to create notes
```

## Adding New MCP Servers

1. Add server definition to `mcp_configs/mcp_servers.json`:
```json
{
  "mcpServers": {
    "myServer": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@myorg/my-mcp-server"],
      "env": {
        "API_KEY": "${MY_SERVER_API_KEY}"
      }
    }
  }
}
```

2. Add API key to `.env`:
```bash
MY_SERVER_API_KEY=your_api_key_here
```

3. (Optional) Add per-server configuration to `src/app/agents/server_agent_map.json`:
```json
{
  "servers": {
    "myServer": {
      "blacklisted_tools": ["tool_to_exclude"],
      "agents": [
        {
          "name": "my_agent",
          "responsibility": "Handles specific tasks",
          "tools": ["tool1", "tool2"]
        }
      ]
    }
  }
}
```

4. Restart worker: `pkill -f src.app.infra.redis.worker && ./run_worker.sh`

The worker will automatically:
- Discover tools from the new server
- Create agent(s) for the server using LLM categorization (or explicit config)
- Make tools available to supervisor

## Adding New Input Sources

To add a new input source (e.g., REST API, Slack), follow these steps:

1. **Create Ingress Adapter** (`src/app/api/<source>_input.py`):
   - Accept input in source-specific format
   - Normalize to standard message contract (source, user_id, text, conversation_id, metadata)
   - Publish to `inbound_messages` stream via `RedisStreamPublisher`
   - Return immediately (no blocking)

2. **Register Router** in `src/app/main.py`:
```python
from src.app.api import rest_input
app.include_router(rest_input.router)
```

3. **Handle Delivery** (if needed):
   - Option A: Async polling endpoint to fetch results from outbound stream
   - Option B: Callback URL stored in metadata, dispatcher delivers to callback

**No changes needed** in worker, supervisor, agents, or MCP configuration. The execution pipeline remains identical.

## Debugging & Observability

### LangSmith Tracing

LangSmith provides end-to-end traces of supervisor decisions, agent routing, and tool calls.

**Setup** (in `.env`):
```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=your_langsmith_key
LANGCHAIN_PROJECT=notion-play
```

**Usage**:
- Traces automatically tagged with `source` (e.g., "whatsapp")
- Metadata includes: `stream_message_id`, `message_id`, `conversation_id`, `user_id`
- Thread ID set to `conversation_id` for conversation grouping
- View in LangSmith UI to debug routing, tool calls, and failures

### Logging Best Practices

The codebase uses structured logging with context:

```python
from src.app.logging.logger import setup_logger
logger = setup_logger(__name__)

logger.info("Message processed | id=%s | user=%s", msg_id, user_id)
logger.debug("Tool call | name=%s | args=%s", tool_name, sanitized_args)
logger.error("Tool failed | name=%s", tool_name, exc_info=exc)
```

Key log patterns to search for:
- `"Bootstrap complete"` - worker startup successful
- `"MCP tools loaded"` - tool discovery succeeded
- `"Agent created"` - agent instantiation
- `"Supervisor compiled successfully"` - supervisor ready
- `"Processing message"` - message consumption started
- `"Tool validation wrapper active"` - tool validation in effect
- `"Normalized Notion HTTP validation_error"` - Notion validation error caught
- `"Reply ready"` - final response extracted
- `"Outbound published"` - message sent to outbound stream

## Common Issues

### MCP Server Connection Failures
- Ensure MCP tokens are set in `.env` and exported (run scripts handle this)
- Check `mcp_configs/mcp_servers.json` syntax is valid JSON
- For stdio servers: verify `npx` command works (`npx -y @notionhq/notion-mcp-server`)
- Check worker logs for "MCP tools discovered" messages

### Worker Bootstrap Failures
- Check `NOTION_MCP_ACCESS_TOKEN` is set (required by run_worker.sh)
- Verify Redis is running: `redis-cli ping`
- Check logs for MCP tool discovery errors
- Ensure Python 3.13 is used (scripts check this)

### Memory/Token Issues
- Enable tool output trimming: `TOOL_OUTPUT_TRIMMING_ENABLED=true`
- Lower trigger threshold: `AGENT_SUMMARIZATION_TRIGGER_TOKENS=2000`
- Reduce items returned: `TOOL_TRIM_NOTION_MAX_ITEMS=3`
- Check LangSmith traces for token usage per step

### Audio Reply Not Working
- Set `MEDIA_PUBLIC_BASE_URL` to your ngrok/cloudflared URL (must be HTTPS)
- Verify TTS settings: `TTS_MODEL_NAME=tts-1`, `TTS_VOICE=alloy`
- Check audio files are created in `./data/media/tts/`
- Ensure Twilio can fetch the URL (test in browser)

### Voice Note Transcription Failures
- Check `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` are set
- Verify `OPENAI_API_KEY` is valid
- Check worker logs for "Whisper STT" errors
- Ensure SSL/TLS certificates are valid (`certifi` package)

### Tool Validation Errors
- Check worker logs for "Tool semantic validation failed"
- Check for "Normalized Notion HTTP validation_error" with `repeat_count`
- If repeat_count > 3, review validator logic in `tool_validation/validators/`
- Add/extend validators in `tool_validation/registry.py`

### Memory Not Persisting
- Check Redis is running and accessible
- Verify `status=success` in supervisor result
- Check grounding detection: look for "Memory write skipped" logs
- Ensure tool execution tracker detects tool calls (check logs)

## Code Style & Patterns

### Async/Await
- Use `async def` and `await` for I/O operations (Redis, HTTP, LLM calls)
- Worker uses `asyncio.create_task()` for concurrent message processing
- Semaphore limits concurrency: `max_concurrency=10` (configurable)

### Type Hints
Use type hints and Pydantic models:
```python
from dataclasses import dataclass
from typing import Dict, List, Optional

@dataclass(frozen=True)
class MyContext:
    user_id: str
    text: str
    metadata: Dict[str, Any]
```

### Error Handling
- Worker: Do NOT ACK messages on failure (they stay in pending state)
- Dispatcher: Do NOT ACK messages until delivery succeeds
- Use try/except with `logger.exception()` for full traceback
- Return structured error payloads from tools (JSON string with `error_type`)

### Testing
- Keep tests in `src/tests/`
- Use pytest fixtures for common setup
- Test file naming: `test_<feature>.py`
- End-to-end tests: `load_test_whatsapp_webhook.py`

### Documentation
- **IMPORTANT**: Per repo rules, every new/updated file must be recorded in `docs/file_tracking.md`
- Add comments for non-obvious logic
- Update relevant phase docs when making architectural changes
- Keep docs in sync with code changes

## Project Evolution (Phases)

The project evolved through multiple phases:

- **Phase 1**: MCP Integration & Infrastructure (Redis Streams, MCP client, basic agents)
- **Phase 2**: Execution Runtime & Supervisor (LangGraph supervisor, agent routing)
- **Phase 3**: Output Handling & Delivery (outbound stream, dispatcher, WhatsApp replies)
- **Phase 4**: Tool Correctness & Final Reply Contract (tool validation, Notion HTTP error normalization, output assembler)
- **Phase 5**: Voice Input & Language Support (STT, language detection, translation, TTS)
- **Phase 6** (Current): Token Optimization & Long-term Memory (summarization middleware, memory prefetch, tool output trimming)

See `docs/Phase_*.md` for detailed evolution history.
