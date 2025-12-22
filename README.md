# MCP WhatsApp Supervisor Agents

This repo scaffolds an agent system that connects:
- WhatsApp (Twilio) → FastAPI webhook
- Supervisor Agent (LangGraph/LangChain) → routes work to specialist agents
- MCP Servers (starting with Notion MCP) → provides tools to agents

## Quickstart (local)
1. Create venv + install deps
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Set env

```bash
cp .env.example .env
# fill values
```

3. Run API
```bash
uvicorn src.app.main:app --reload --port 8000
```

4. Expose webhook to Twilio (example)
```bash
ngrok http 8000
```

## Docs
- `src/docs/project_description.md` — project goals + architecture
- `src/docs/file_tracking.md` — every file change is recorded here


Kill what’s using port 6379 (Redis)
lsof -nP -iTCP:6379 -sTCP:LISTEN
kill -9 <PID>

Kill what’s using port 11434 (Ollama)
lsof -nP -iTCP:11434 -sTCP:LISTEN
kill -9 <PID>

Start Redis
redis-server

Start Ollama
ollama serve

cloudflared tunnel --url http://localhost:8000