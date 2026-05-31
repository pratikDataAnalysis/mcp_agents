# CLAUDE.md — mcp_agents

## Project Overview

**MCP-Multi-Agents-System** is a multi-agent AI system that receives WhatsApp messages via Twilio, routes them through a LangGraph Supervisor, executes actions via MCP servers (Notion, Zoom, etc.), and replies back over WhatsApp. Redis Streams serve as the async message bus between three independent processes.

---

## Architecture

Three separate processes communicate via Redis Streams:

```
User → WhatsApp (Twilio)
  ↓
[Process 1] FastAPI Ingress          (run.sh)
  → Receives webhook, publishes to Redis Stream: inbound_messages
  ↓
[Process 2] Redis Worker             (run_worker.sh)
  → Bootstraps LLM + MCP tools + agents + supervisor (once)
  → Consumes inbound_messages, invokes supervisor
  → Publishes to Redis Stream: outbound_messages
  ↓
[Process 3] Outbound Dispatcher      (run_dispatcher.sh)
  → Consumes outbound_messages, delivers via Twilio WhatsApp API
  ↓
WhatsApp Reply
```

---

## Project Structure

```
mcp_configs/
  mcp_servers.json              # MCP server definitions (Notion, Zoom, etc.)
src/
  app/
    agents/
      agent_creator.py          # Builds LangChain agents from definitions
      agent_definitions.py      # LLM-based agent categorization + policy packs
      policy_packs/             # JSON rules injected into agent system prompts
      prompts/                  # LLM prompt for agent categorization
      server_agent_map.json     # Per-server tool blacklists / overrides
    api/
      whatsapp_webhook.py       # Twilio webhook handler (POST /webhooks/whatsapp)
      media.py                  # Media attachment handling
    audio/
      twilio_stt.py             # Twilio speech-to-text
      media.py                  # Audio file management
    config/
      settings.py               # Pydantic Settings (all env-based)
    contracts/
      output_envelope.py        # Output message schema
    dispatchers/
      outbound_dispatcher.py    # Delivery worker: Redis → Twilio
      channels/
        twilio_whatsapp_sender.py
    infra/
      redis/
        bootstrap.py            # One-time worker bootstrap (LLM, MCP, agents, supervisor)
        client.py               # Async Redis wrapper
        worker.py               # Main execution worker
        stream_publisher.py     # Publishes to inbound stream
        stream_outbound_publisher.py
        memory_store.py         # User/conversation memory (Redis JSON)
        idempotency_store.py    # Deduplication for outbound sends
      tool_execution_tracker.py # Tracks tool calls to inform memory writes
      tool_output_trimmer.py    # Truncates large tool outputs (prevents context explosion)
      tool_validation/          # Wraps tools with args_schema enforcement
      langsmith.py              # LangSmith observability setup
      openai_stt.py             # OpenAI speech-to-text
    inputs/
      whatsapp/inbound.py       # WhatsApp message parsing
    mcp/
      mcp_client.py             # MCP client: tool discovery, stdio + HTTP transports
      tools/
        language_tools.py       # STT, TTS, translation
        tagging.py              # Tool metadata helpers
    runtime/
      pre_supervisor.py         # Media/STT + language detection + envelope building
      output_assembler.py       # Extracts final reply text from supervisor result
    services/
      twilio_service.py         # Twilio SDK wrapper
    supervisor/
      supervisor_creator.py     # Supervisor factory (LangGraph)
      state.py                  # LangGraph state schemas
      structured_response.py    # Supervisor output format
      handoff_tools.py          # Agent handoff tool builders
      memory_tools.py           # Memory access tools
      tools.py                  # Supervisor-level tools (datetime, etc.)
      prompts/supervisor_prompt.py
    main.py                     # FastAPI app entrypoint
  tests/
    test_smoke.py
    test.py
    create_note_test.py
    load_test_whatsapp_webhook.py
run.sh                          # Start FastAPI ingress
run_worker.sh                   # Start Redis worker
run_dispatcher.sh               # Start outbound dispatcher
requirements.txt
```

---

## Running the Project

Requires Python 3.13+, Redis, and a `.env` file (see Configuration below).

**Terminal 1 — Redis**
```bash
redis-server
```

**Terminal 2 — FastAPI Ingress**
```bash
./run.sh
# Starts uvicorn on port 8000
```

**Terminal 3 — Redis Worker**
```bash
./run_worker.sh
# Bootstrap phase (~30-60s): initializes LLM, discovers MCP tools, creates agents + supervisor
# Then continuously consumes inbound_messages stream
```

**Terminal 4 — Outbound Dispatcher**
```bash
./run_dispatcher.sh
# Continuously consumes outbound_messages, sends via Twilio
```

**Terminal 5 — Expose Webhook (local dev)**
```bash
cloudflared tunnel --url http://localhost:8000
# Point Twilio webhook to: https://<subdomain>.trycloudflare.com/webhooks/whatsapp
```

---

## Configuration

All config is environment-based via Pydantic Settings (`src/app/config/settings.py`). Create a `.env` file:

```bash
# Twilio
TWILIO_ACCOUNT_SID=
TWILIO_AUTH_TOKEN=
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# MCP
NOTION_MCP_ACCESS_TOKEN=

# LLM
LLM_PROVIDER=openai           # or 'ollama'
LLM_MODEL_NAME=gpt-4o-mini
OPENAI_API_KEY=

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379

# Audio (for TTS reply delivery)
MEDIA_PUBLIC_BASE_URL=https://your-ngrok-url

# Optional
MCP_CONFIG_PATH=./mcp_configs/mcp_servers.json
LANGCHAIN_API_KEY=            # LangSmith tracing
```

### MCP Server Config (`mcp_configs/mcp_servers.json`)

```json
{
  "mcpServers": {
    "notionApi": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@notionhq/notion-mcp-server"],
      "env": {
        "OPENAPI_MCP_HEADERS": "{\"Authorization\": \"Bearer ${NOTION_MCP_ACCESS_TOKEN}\", \"Notion-Version\": \"2022-06-28\"}"
      }
    }
  }
}
```

`${ENV_VAR}` references in the config are expanded from the environment at runtime.

---

## Key Design Decisions

- **Separation of concerns**: Ingress, execution, and delivery are independent processes that scale separately.
- **ACK-only-on-success**: Redis Stream messages are only acknowledged after successful downstream publish/send — no silent failures.
- **Deterministic memory writes**: The worker (not the LLM) decides when to write memory — only on grounded tool success.
- **Tool output trimming**: Large MCP responses (e.g., Notion search) are truncated before reaching the agent loop to prevent context explosion.
- **Agent definitions via LLM**: Agents are not hardcoded — they are created at bootstrap time by asking an LLM to categorize MCP tools, then injecting policy packs for domain-specific rules.
- **Pre-fetched memory context**: Memory is read before supervisor invocation and injected into the envelope, avoiding extra LLM round-trips.

---

## Adding a New MCP Server

1. Add the server definition to `mcp_configs/mcp_servers.json`.
2. Add any required env vars to `.env` and `src/app/config/settings.py`.
3. Optionally add a policy pack in `src/app/agents/policy_packs/` to inject server-specific rules.
4. Optionally add an entry in `src/app/agents/server_agent_map.json` to blacklist specific tools.
5. Restart the worker — agents are auto-created from discovered tools.

---

## Dependencies

| Package | Role |
|---|---|
| FastAPI + Uvicorn | HTTP server & webhook |
| LangChain + LangGraph | Agent orchestration & supervisor |
| langgraph-supervisor | Supervisor pattern |
| langchain-mcp-adapters | MCP → LangChain tool bridge |
| langchain-openai / langchain-ollama | LLM providers |
| Redis (redis-py) | Message streams + memory store |
| Twilio | WhatsApp send/receive |
| Pydantic / Pydantic Settings | Data validation + env config |
| LangSmith | LLM observability & tracing |

---

## Tests

```bash
pytest src/tests/test_smoke.py
```

Load test: `src/tests/load_test_whatsapp_webhook.py`
