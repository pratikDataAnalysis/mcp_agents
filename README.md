# Multi-Agent: WhatsApp + MCP Supervisor Agent Platform

A multi-agent AI system that receives WhatsApp messages via Twilio, routes them through a Supervisor Agent (LangGraph/LangChain), and executes actions via MCP servers (starting with Notion MCP).

## 🎯 Project Overview

This application is a **multi-agent AI system** that:
- Accepts user input from **multiple channels** (WhatsApp today, more later)
- Uses **LLMs + MCP tools** to reason and act
- Routes work via a **Supervisor** instead of hardcoded logic
- Scales independently for ingress and execution

### Key Features
- **Event-driven architecture** using Redis Streams
- **MCP-first design** - tools come from MCP servers, not hardcoded integrations
- **Supervisor pattern** - central Supervisor decides which agent handles each message
- **Asynchronous by default** - no blocking requests, safe under high load
- **Source-agnostic** - same pipeline works for WhatsApp, Slack, Web, etc.

## 🏗️ Architecture

```
User → WhatsApp (Twilio)
  ↓
FastAPI Ingress (run.sh)
  ↓
Redis Stream (inbound_messages)
  ↓
Redis Worker (run_worker.sh)
  ├─ LLM (once)
  ├─ MCP Client + Tools (once)
  ├─ Agents (once)
  └─ Supervisor (once)
  ↓
Supervisor → Agents → MCP Tools
  ↓
Redis Stream (outbound_messages)
  ↓
Outbound Dispatcher (run_dispatcher.sh)
  ↓
WhatsApp Reply (Twilio)
```

### Components

1. **Input Layer** (`run.sh`)
   - FastAPI endpoints (WhatsApp webhook)
   - Stateless, publishes to Redis Stream
   - Returns immediately (non-blocking)

2. **Execution Layer** (`run_worker.sh`)
   - Redis Stream Worker
   - Bootstraps LLM, MCP tools, agents, and supervisor once
   - Processes messages concurrently with bounded concurrency

3. **Delivery Layer** (`run_dispatcher.sh`)
   - Outbound Dispatcher
   - Consumes from outbound Redis Stream
   - Routes responses to appropriate channels (WhatsApp, etc.)

## 📋 Prerequisites

- **Python 3.8+**
- **Redis** (for message queuing)
- **Cloudflare Tunnel** (for exposing webhook locally)
- **Twilio Account** (for WhatsApp integration)
- **MCP Server Access Tokens** (e.g., Notion API token)

## 🚀 Setup

### 1. Clone and Install Dependencies

```bash
# Clone the repository
git clone <repository-url>
cd pfm

# Create virtual environment (scripts will do this automatically, but you can do it manually)
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Configure Environment Variables

Create a `.env` file in the project root with the following variables:

```bash
# Twilio Configuration
TWILIO_ACCOUNT_SID=your_account_sid
TWILIO_AUTH_TOKEN=your_auth_token
TWILIO_WHATSAPP_FROM=whatsapp:+14155238886

# MCP Server Tokens
NOTION_MCP_ACCESS_TOKEN=your_notion_integration_token

# LLM Configuration
LLM_PROVIDER=openai  # or 'ollama'
LLM_MODEL_NAME=gpt-4o-mini  # or 'llama3.1' for Ollama
OPENAI_API_KEY=your_openai_api_key  # if using OpenAI

# Redis Configuration (optional, defaults shown)
REDIS_HOST=localhost
REDIS_PORT=6379

# MCP Configuration (optional, defaults shown)
MCP_CONFIG_PATH=./mcp_configs/mcp_servers.json
```

### 3. Configure MCP Servers

Edit `mcp_configs/mcp_servers.json` to configure your MCP servers:

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

### 4. Configure Agents

Agents are created at worker bootstrap time via LLM-based tool categorization (plus policy packs).

## 🏃 Running the Application

The application consists of **4 separate processes** that must run simultaneously:

### Step 1: Start Redis Server

```bash
redis-server
```

Verify Redis is running:
```bash
redis-cli ping
# Should return: PONG
```

### Step 2: Start FastAPI Ingress (Terminal 1)

This starts the FastAPI server with Twilio webhook integration:

```bash
./run.sh
```

This script will:
- Create/activate virtual environment
- Install dependencies (only if `requirements.txt` changed)
- Load environment variables from `.env`
- Start FastAPI on port 8000

**What it does:**
- Receives WhatsApp messages via Twilio webhook
- Normalizes and publishes messages to Redis Stream (`inbound_messages`)
- Returns immediately (non-blocking)

### Step 3: Start Worker Service (Terminal 2)

This starts the Redis Stream worker that processes messages:

```bash
./run_worker.sh
```

This script will:
- Create/activate virtual environment
- Install dependencies (only if `requirements.txt` changed)
- Load environment variables from `.env`
- **Bootstrap phase (one-time):**
  - Load MCP servers from `mcp_configs/mcp_servers.json`
  - Discover tools from each MCP server
  - Group tools by `source_server` (from MCP config)
  - Create agents via LLM-based tool categorization
  - Assign tools to agents based on `source_server`
  - Create Supervisor using `src/app/supervisor/supervisor_creator.py`
- **Runtime phase:**
  - Consume messages from Redis Stream (`inbound_messages`)
  - Invoke Supervisor for each message
  - Supervisor routes to appropriate agent
  - Agent executes using MCP tools
  - Publish results to outbound Redis Stream (`outbound_messages`)

### Step 4: Start Dispatcher Service (Terminal 3)

This starts the outbound dispatcher that delivers responses:

```bash
./run_dispatcher.sh
```

This script will:
- Create/activate virtual environment
- Install dependencies (only if `requirements.txt` changed)
- Load environment variables from `.env`
- Validate Twilio credentials
- **Runtime phase:**
  - Consume messages from Redis Stream (`outbound_messages`)
  - Route messages based on source/channel
  - Deliver responses via Twilio WhatsApp API
  - Acknowledge messages only after successful delivery

### Step 5: Expose Webhook with Cloudflare Tunnel (Terminal 4)

Create a temporary public URL for Twilio webhook:

```bash
cloudflared tunnel --url http://localhost:8000
```

This will output a URL like:
```
https://random-subdomain.trycloudflare.com
```

**Configure Twilio:**
1. Go to Twilio Console → WhatsApp → Sandbox Settings
2. Set webhook URL to: `https://random-subdomain.trycloudflare.com/webhooks/whatsapp/inbound`
3. Set HTTP method to: `POST`

## 📦 Dependencies

See `requirements.txt` for complete list. Key dependencies:

- **FastAPI** (0.115.5) - Web framework
- **LangChain** (1.0.2) - LLM framework
- **LangGraph** (1.0.5) - Agent orchestration
- **langgraph-supervisor** (0.0.31) - Supervisor pattern implementation
- **langchain-mcp-adapters** (0.2.1) - MCP server integration
- **Redis** (7.1.0) - Message queuing
- **Twilio** (9.3.7) - WhatsApp integration
- **Pydantic** (2.10.2) - Data validation

## 📁 Project Structure

```
pfm/
├── mcp_configs/
│   └── mcp_servers.json          # MCP server configuration
├── src/
│   └── app/
│       ├── agents/
│       │   ├── agent_creator.py  # Agent factory
│       │   └── agent_definitions.py
│       ├── api/
│       │   └── whatsapp_webhook.py # Twilio webhook handler
│       ├── config/
│       │   └── settings.py       # Application settings
│       ├── dispatchers/
│       │   ├── outbound_dispatcher.py
│       │   └── channels/
│       │       └── twilio_whatsapp_sender.py
│       ├── infra/
│       │   ├── redis_client.py
│       │   ├── redis_stream_publisher.py
│       │   ├── redis_stream_outbound_publisher.py
│       │   ├── redis_stream_worker.py
│       │   └── idempotency_store.py
│       ├── mcp/
│       │   └── mcp_client.py     # MCP client abstraction
│       ├── runtime/
│       │   └── output_assembler.py
│       ├── supervisor/
│       │   ├── supervisor_creator.py
│       │   ├── structured_response.py
│       │   ├── prompts/
│       │   │   └── supervisor_prompt.py
│       │   └── tools.py
│       └── main.py               # FastAPI app entrypoint
├── run.sh                        # FastAPI ingress runner
├── run_worker.sh                 # Worker service runner
├── run_dispatcher.sh             # Dispatcher service runner
├── requirements.txt             # Python dependencies
└── README.md                     # This file
```

## 🔍 Troubleshooting

### Redis Connection Issues
```bash
# Check if Redis is running
redis-cli ping

# Kill process using port 6379
lsof -nP -iTCP:6379 -sTCP:LISTEN
kill -9 <PID>
```

### Port Already in Use
```bash
# Check what's using port 8000
lsof -nP -iTCP:8000 -sTCP:LISTEN

# Kill FastAPI process
pkill -f "uvicorn.*src.app.main"
```

### Worker Already Running
```bash
# Kill existing worker
pkill -f "src.app.infra.redis_stream_worker"
```

### Dispatcher Already Running
```bash
# Kill existing dispatcher
pkill -f "src.app.dispatchers.outbound_dispatcher"
```

### MCP Server Issues
- Ensure MCP server tokens are set in `.env`
- Check `mcp_configs/mcp_servers.json` syntax
- Verify MCP server command is available (e.g., `npx` for Notion)

## 📚 Documentation

- `docs/project_description.md` - Project goals and architecture
- `docs/application_architecture.md` - Detailed architecture documentation
- `docs/Phase_1.md` - Phase 1 implementation details
- `docs/Phase_2.md` - Phase 2 implementation details
- `docs/phase_3.md` - Phase 3 implementation details
- `docs/Phase_4.md` - Phase 4 implementation details
- `docs/steps_to_add_agents.md` - How to add new agents
- `docs/steps_to_add_input_source.md` - How to add new input sources
- `docs/file_tracking.md` - File change log

## 🎯 Key Design Principles

1. **Separation of Concerns**
   - Ingress ≠ Execution ≠ Delivery
   - Each layer evolves independently

2. **Asynchronous by Default**
   - No blocking requests
   - Safe under high load
   - Backpressure handled by Redis

3. **Agent-First Design**
   - Logic lives in agents, not routes
   - Supervisor decides, not hardcoded rules

4. **Source Agnostic**
   - WhatsApp is just one input
   - Same pipeline works for API, Slack, Web, etc.

5. **MCP-First Architecture**
   - Tools come from MCP servers
   - Agents consume tools; they don't manage connections

## 🚧 Current Status

- ✅ Phase 1: MCP Integration & Infrastructure
- ✅ Phase 2: Execution Runtime & Supervisor
- ✅ Phase 3: Output Handling & Delivery
- ✅ Phase 4: Tool Correctness & Final Reply Contract
- 🟡 Phase 5: Structured Response (in progress)

## 📝 License

[Add your license here]

## 🤝 Contributing

[Add contributing guidelines here]

redis-cli --scan --pattern 'memory:user:*:events'
redis-cli LLEN 'memory:user:whatsapp:+918826545723:events'
redis-cli LRANGE 'memory:user:whatsapp:+918826545723:events' 0 2