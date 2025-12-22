"""
Redis Stream worker (execution runtime).

Responsibilities:
- Bootstrap ONCE (LLM, MCP tools, agent definitions, agents, supervisor)
- Consume inbound messages from Redis Stream using a consumer group
- Process messages concurrently with a controlled concurrency limit
- Invoke Supervisor for each message
- Publish execution output to outbound Redis Stream (Phase 3)
- ACK inbound messages only after successful processing + outbound publish

IMPORTANT:
- FastAPI does NOT create agents or supervisor.
- This worker process does (once at startup) and then reuses them.
"""

from __future__ import annotations

import asyncio
import json
import uuid
import time
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, List, Tuple, Optional

from src.app.config.settings import settings
from src.app.infra.redis_client import RedisClient
from src.app.infra.redis_stream_outbound_publisher import RedisStreamOutboundPublisher
from src.app.logging.logger import setup_logger
from src.app.mcp.mcp_client import MCPClient
from src.app.agents.agent_definitions import create_agent_definitions_from_source
from src.app.agents.agent_creator import AgentCreator
from src.app.runtime.output_assembler import extract_reply_text
from src.app.supervisor.supervisor_creator import SupervisorCreator


logger = setup_logger(__name__)


# ---------------------------------------------------------------------
# Bootstrap helpers (run once per worker process)
# ---------------------------------------------------------------------

def build_llm_model(model_name: str | None = None) -> Any:
    """
    Create a shared LLM model instance based on settings.

    Supported (minimal):
    - ollama (ChatOllama)
    - openai (ChatOpenAI)

    NOTE:
    - This is created ONCE per worker process and reused.
    """
    provider = (settings.llm_provider or "ollama").lower()
    resolved_model = model_name or settings.llm_model_name

    logger.info("LLM config | provider=%s | model=%s", provider, resolved_model)

    if provider == "ollama":
        try:
            from langchain_ollama import ChatOllama
        except ImportError as exc:
            raise ImportError(
                "langchain_ollama is required for llm_provider=ollama. "
                "Install with: pip install -U langchain-ollama"
            ) from exc

        return ChatOllama(model=resolved_model)

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError as exc:
            raise ImportError(
                "langchain_openai is required for llm_provider=openai. "
                "Install with: pip install -U langchain-openai"
            ) from exc

        # OPENAI_API_KEY must be in env for this provider.
        return ChatOpenAI(model=resolved_model)

    raise ValueError(f"Unsupported llm_provider={provider!r}. Use 'ollama' or 'openai'.")

async def load_mcp_tools(mcp_client: MCPClient):
    await mcp_client.connect()
    all_tools = await mcp_client.get_all_tools()

    if not all_tools:
        logger.warning("No MCP tools discovered during bootstrap")
        return [], []

    flat_tools: List[Any] = []
    tagged_tools: List[Any] = []

    for server_name, tools in all_tools.items():
        for tool in tools:
            flat_tools.append(tool)
            tagged_tools.append(
                SimpleNamespace(
                    tool=tool,
                    source_server=server_name,
                    name=getattr(tool, "name", ""),
                    description=getattr(tool, "description", ""),
                    args_schema=getattr(tool, "args_schema", None),
                )
            )

    logger.info("MCP tools loaded | servers=%s | tools=%s", len(all_tools), len(tagged_tools))
    for t in tagged_tools:
        logger.debug("Tool | server=%s | name=%s | description=%s", t.source_server, t.name, t.description)

    return flat_tools, tagged_tools

def build_agent_definitions(tagged_tools: List[Any]) -> Any:
    """
    Create agent definitions from tagged tools + agent_config.json mapping.
    """
    if not tagged_tools:
        logger.warning("No tagged tools available; agent definitions will be empty")
        return None

    agent_defs = create_agent_definitions_from_source(tagged_tools)
    logger.info("Agent definitions created | count=%s", len(agent_defs.agents) if agent_defs else 0)

    if agent_defs:
        for a in agent_defs.agents:
            logger.debug("AgentDef | name=%s | tools=%s", a.name, len(a.tools))

    return agent_defs

def build_agents(agent_defs: Any, flat_tools: List[Any]) -> Dict[str, Any]:
    """
    Create agents ONCE using AgentCreator.
    """
    if not agent_defs or not getattr(agent_defs, "agents", None):
        logger.warning("No agent definitions found; no agents will be created")
        return {}

    if not flat_tools:
        logger.warning("No MCP tools found; no agents will be created")
        return {}

    agent_model = settings.llm_model_name
    creator = AgentCreator(model_name=agent_model)
    agents = creator.create_agents(agent_defs.agents, flat_tools)

    logger.info("Agents created | count=%s", len(agents))
    return agents


def build_supervisor(llm: Any, agents: Dict[str, Any], agent_defs: Any) -> Any:
    """
    Create supervisor ONCE using SupervisorCreator.
    """
    if not agents:
        raise ValueError("Cannot create supervisor: agents dict is empty")

    supervisor_creator = SupervisorCreator(model=llm)
    supervisor = supervisor_creator.create(
        agents=agents,
        agent_definitions=agent_defs,
    )

    logger.info("Supervisor ready")
    return supervisor


async def bootstrap_supervisor() -> Any:
    """
    Full bootstrap pipeline (run once per worker process).
    """
    logger.info("Worker bootstrap started")

    # Step 1: LLM (shared)
    llm = build_llm_model(settings.llm_model_name)

    # Step 2: MCP tools (shared)
    mcp_client = MCPClient(config_path=settings.mcp_config_path)
    flat_tools, tagged_tools = await load_mcp_tools(mcp_client)

    logger.info("Bootstrap check | tools=%s", len(tagged_tools))

    # Step 3: Agent definitions
    agent_defs = build_agent_definitions(tagged_tools)

    # Step 4: Agents
    agents = build_agents(agent_defs, flat_tools)

    # Step 5: Supervisor
    supervisor = build_supervisor(llm, agents, agent_defs)

    logger.info(
        "Worker bootstrap complete | tools=%s | agent_defs=%s | agents=%s",
        len(tagged_tools),
        len(getattr(agent_defs, "agents", []) or []) if agent_defs else 0,
        len(agents),
    )

    return supervisor


# ---------------------------------------------------------------------
# Redis Stream worker (runtime loop)
# ---------------------------------------------------------------------

def _parse_iso_ts(ts: Optional[str]) -> Optional[datetime]:
    """Best-effort parse ISO timestamp to aware UTC datetime."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts)
        # If timestamp is naive, assume UTC
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


class RedisStreamWorker:
    """
    Consumes messages from Redis Streams and invokes Supervisor concurrently.
    Produces outbound messages to an outbound Redis Stream.
    """

    def __init__(
        self,
        redis_client: RedisClient,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        supervisor: Any,
        max_concurrency: int = 10,
    ) -> None:
        self.redis_client = redis_client
        self.stream_name = stream_name
        self.group_name = group_name
        self.consumer_name = consumer_name
        self.supervisor = supervisor
        self.semaphore = asyncio.Semaphore(max_concurrency)

    async def start(self) -> None:
        """
        Start the worker consume loop (runs forever).
        """
        client = await self.redis_client.get_client()
        await self._ensure_consumer_group(client)

        logger.info(
            "Redis worker started | stream=%s | group=%s | consumer=%s | max_concurrency=%s",
            self.stream_name,
            self.group_name,
            self.consumer_name,
            self.semaphore._value,  # ok for debug
        )

        while True:
            try:
                await self._consume_once(client)
            except Exception as exc:
                logger.error("Worker loop error", exc_info=exc)
                await asyncio.sleep(1)

    async def _ensure_consumer_group(self, client) -> None:
        """
        Ensure consumer group exists.
        """
        try:
            await client.xgroup_create(
                name=self.stream_name,
                groupname=self.group_name,
                id="0-0",
                mkstream=True,
            )
            logger.info(
                "Redis consumer group created | stream=%s | group=%s",
                self.stream_name,
                self.group_name,
            )
        except Exception as exc:
            if "BUSYGROUP" in str(exc):
                logger.debug(
                    "Redis consumer group already exists | stream=%s | group=%s",
                    self.stream_name,
                    self.group_name,
                )
            else:
                raise

    async def _consume_once(self, client) -> None:
        """
        Read a small batch and schedule concurrent processing tasks.
        """
        response = await client.xreadgroup(
            groupname=self.group_name,
            consumername=self.consumer_name,
            streams={self.stream_name: ">"},
            count=10,
            block=5000,  # ms
        )

        if not response:
            return

        for _, messages in response:
            for message_id, payload in messages:
                asyncio.create_task(self._process_with_limit(client, message_id, payload))

    async def _process_with_limit(self, client, message_id: str, payload: Dict[str, str]) -> None:
        """
        Apply concurrency limit and then process the message.
        """
        async with self.semaphore:
            await self._process_message(client, message_id, payload)

    async def _process_message(self, client, message_id: str, payload: Dict[str, str]) -> None:
        """
        Invoke Supervisor for a single message, publish outbound output, ACK on success.

        ACK rule (Phase 3):
        - ACK inbound only after outbound publish succeeds.
        """
        t_total_start = time.perf_counter()

        text = (payload.get("text") or "").strip()
        source = payload.get("source", "unknown")
        user_id = payload.get("user_id", "unknown")

        # Measure ingress-to-worker lag if inbound timestamp exists
        ingress_ts = _parse_iso_ts(payload.get("timestamp"))
        if ingress_ts:
            lag_s = (datetime.now(timezone.utc) - ingress_ts).total_seconds()
            logger.info("Inbound lag | id=%s | lag_s=%.3f", message_id, lag_s)

        if not text:
            logger.warning("Empty text message | id=%s | payload=%s", message_id, payload)
            await client.xack(self.stream_name, self.group_name, message_id)
            return

        logger.info(
            "Processing message | id=%s | source=%s | user_id=%s | text=%s",
            message_id, source, user_id, text
        )

        try:
            message = {
                "source": source,
                "creation_time": datetime.now(timezone.utc).isoformat(),
                "user_id": user_id,
                "text": text,
                "metadata": payload.get("metadata"),
            }
            logger.debug("Invoking supervisor message | id=%s", message)
            # --- Supervisor invocation timing ---
            t_sup_start = time.perf_counter()
            result = await self.supervisor.ainvoke(
                {"messages": [{"role": "user", "content": message["text"]}]}
            )
            t_sup_end = time.perf_counter()

            logger.info(
                "Supervisor done | id=%s | supervisor_ainvoke_s=%.3f",
                message_id,
                (t_sup_end - t_sup_start),
            )

            logger.info("Supervisor result | id=%s | result=%s", message_id, result)

            # --- Output extraction timing ---
            t_extract_start = time.perf_counter()
            reply_text = extract_reply_text(result) or "Done."
            t_extract_end = time.perf_counter()

            # Prepare outbound payload
            correlation_id = payload.get("message_id") or message_id
            conversation_id = payload.get("conversation_id") or correlation_id

            out_payload: Dict[str, str] = {
                "out_id": str(uuid.uuid4()),
                "correlation_id": correlation_id,
                "conversation_id": conversation_id,
                "source": source,
                "user_id": user_id,
                "reply_text": reply_text,
                "status": "success",
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

            inbound_meta = payload.get("metadata")
            if inbound_meta:
                try:
                    json.loads(inbound_meta)
                    out_payload["metadata"] = inbound_meta
                except Exception:
                    out_payload["metadata"] = json.dumps({"raw": inbound_meta})

            # --- Outbound publish timing ---
            outbound_publisher = RedisStreamOutboundPublisher(
                redis_client=self.redis_client,
                stream_name=settings.redis_stream_outbound,
            )

            t_pub_start = time.perf_counter()
            outbound_stream_id = await outbound_publisher.publish_output(out_payload)
            t_pub_end = time.perf_counter()

            logger.info(
                "Outbound published | outbound_stream_id=%s | correlation_id=%s | user_id=%s | publish_outbound_s=%.3f",
                outbound_stream_id,
                correlation_id,
                user_id,
                (t_pub_end - t_pub_start),
            )

            # --- ACK timing ---
            t_ack_start = time.perf_counter()
            await client.xack(self.stream_name, self.group_name, message_id)
            t_ack_end = time.perf_counter()

            t_total_end = time.perf_counter()

            logger.info(
                "Message acknowledged | id=%s | timings: supervisor=%.3f s | extract_reply=%.3f s | publish=%.3f s | ack=%.3f s | total=%.3f s",
                message_id,
                (t_sup_end - t_sup_start),
                (t_extract_end - t_extract_start),
                (t_pub_end - t_pub_start),
                (t_ack_end - t_ack_start),
                (t_total_end - t_total_start),
            )

        except Exception as exc:
            logger.error("Failed to process message | id=%s", message_id, exc_info=exc)
            # DO NOT ACK on failure.
            # Message stays pending for retry / later handling.


# ---------------------------------------------------------------------
# Worker runner (script)
# ---------------------------------------------------------------------

async def run_worker() -> None:
    """
    Script entrypoint for running this worker process.
    Creates Supervisor once, then consumes messages forever.
    """
    supervisor = await bootstrap_supervisor()

    redis_client = RedisClient()
    worker = RedisStreamWorker(
        redis_client=redis_client,
        stream_name=settings.redis_stream_inbound,
        group_name=settings.redis_consumer_group,
        consumer_name=settings.redis_consumer_name,
        supervisor=supervisor,
        max_concurrency=getattr(settings, "worker_max_concurrency", 10),
    )

    await worker.start()


if __name__ == "__main__":
    asyncio.run(run_worker())
