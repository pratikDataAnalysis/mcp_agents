"""
MCP Client Manager

This module provides a single, client-side interface to:
- Load MCP server definitions from one JSON config file
- Support BOTH MCP transport styles:
  1) Remote "streamable_http/http" servers (configured via `url`)
  2) Local "stdio" servers (configured via `command` + optional `args`)
- Support per-server environment variables (`env`) for stdio servers (ex: Notion MCP via npx)
- Expand environment variables in config values (ex: tokens in headers/env)
- Initialize a MultiServerMCPClient for all configured servers
- Discover tools exposed by each MCP server
- Cache tool discovery results to avoid repeated calls

Why this file exists:
- Agents (Supervisor / Memory / others) should not care about MCP config formats,
  auth headers, transports, env injection, or how tool discovery works.
- This keeps MCP integration in one place and makes adding new MCP servers trivial.

Config format (recommended):
{
  "mcpServers": {
    "notionApi": {
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@notionhq/notion-mcp-server"],
      "env": {
        "OPENAPI_MCP_HEADERS": "{\"Authorization\": \"Bearer ${NOTION_MCP_ACCESS_TOKEN}\", \"Notion-Version\": \"2022-06-28\"}"
      }
    },
    "remoteExample": {
      "transport": "streamable_http",
      "url": "https://example.com/mcp",
      "headers": {
        "Authorization": "Bearer ${REMOTE_TOKEN}"
      }
    }
  }
}

Transport inference if missing:
- `command` present -> defaults to "stdio"
- `url` present -> defaults to "streamable_http"
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from src.app.logging.logger import setup_logger

logger = setup_logger(__name__)

try:
    # Installed via: pip install langchain-mcp-adapters
    from langchain_mcp_adapters.client import MultiServerMCPClient
except ImportError as e:  # pragma: no cover
    raise ImportError(
        "Missing dependency: langchain-mcp-adapters. Add it to requirements.txt and install."
    ) from e


# Matches ${ENV_VAR_NAME}
_ENV_PATTERN = re.compile(r"\$\{([^}]+)\}")


def _expand_env_vars(value: str) -> str:
    """
    Replace ${VAR_NAME} with environment variable values.

    Example:
        "Bearer ${NOTION_MCP_ACCESS_TOKEN}" -> "Bearer <actual-token>"
        "{\"Authorization\":\"Bearer ${TOKEN}\"}" -> "{\"Authorization\":\"Bearer <token>\"}"

    Raises:
        ValueError: if a referenced environment variable is not set.
    """

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        env_value = os.getenv(var_name)
        if env_value is None:
            raise ValueError(f"Environment variable '{var_name}' is not set")
        return env_value

    return _ENV_PATTERN.sub(replacer, value)


def _expand_env_in_dict(raw: Dict[str, object], *, context: str) -> Dict[str, str]:
    """
    Expand ${ENV_VAR} placeholders for all string values in a dict and coerce values to strings.

    Args:
        raw: dict of key -> value
        context: used for clearer error messages

    Returns:
        dict of key -> expanded string value
    """
    if not isinstance(raw, dict):
        raise ValueError(f"Invalid MCP config for '{context}': must be an object.")

    out: Dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(v, str):
            out[str(k)] = _expand_env_vars(v)
        else:
            out[str(k)] = str(v)
    return out


@dataclass
class MCPServerConfig:
    """
    Typed representation of a single MCP server configuration.

    Only one of the following should be used:
    - Remote server: `url` (streamable_http/http)
    - Local server: `command` (+ optional `args`) (stdio)

    Fields:
    - headers: typically for remote auth
    - env: environment variables passed to stdio-launched MCP servers
    """
    name: str
    transport: str
    url: Optional[str]
    command: Optional[str]
    args: List[str]
    headers: Dict[str, str]
    env: Dict[str, str]


class MCPClient:
    """
    Client-side manager for multiple MCP servers.

    Typical usage:
        mcp = MCPClient(config_path="./mcp_configs/mcp_servers.json")
        await mcp.connect()
        tools = await mcp.get_tools("notionApi")

    Behavior:
    - `load_config()` reads, validates, and normalizes MCP server definitions.
    - `connect()` initializes MultiServerMCPClient with all servers.
    - `get_tools(server_name)` performs MCP tool discovery via adapter, with caching.
    """

    def __init__(self, config_path: str):
        self.config_path = config_path

        self._servers: Dict[str, MCPServerConfig] = {}
        self._client: Optional[MultiServerMCPClient] = None

        # Cache discovered tools per server_name
        self._tools_cache: Dict[str, List[Any]] = {}

    def load_config(self) -> Dict[str, MCPServerConfig]:
        """
        Load and validate MCP server config from JSON.

        What this does:
        - Validates file exists
        - Validates top-level "mcpServers" object
        - Infers transport if missing:
            * command present -> "stdio"
            * url present -> "streamable_http"
        - Expands environment vars in:
            * headers values (remote auth)
            * env values (stdio server injection, ex: Notion OPENAPI_MCP_HEADERS)
        - Normalizes args to a list[str]

        Returns:
            Dict[str, MCPServerConfig]: registry of configured MCP servers
        """
        logger.info(f"Loading external MCP servers from config: {self.config_path}")

        if not os.path.exists(self.config_path):
            raise FileNotFoundError(f"MCP config file not found: {self.config_path}")

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        servers_raw = raw.get("mcpServers")
        if not isinstance(servers_raw, dict) or not servers_raw:
            raise ValueError("Invalid MCP config: 'mcpServers' must be a non-empty object.")

        servers: Dict[str, MCPServerConfig] = {}

        for name, cfg in servers_raw.items():
            if not isinstance(cfg, dict):
                raise ValueError(f"Invalid MCP config for '{name}': must be an object.")

            url = cfg.get("url")
            command = cfg.get("command")
            args = cfg.get("args", []) or []

            # args normalization
            if isinstance(args, str):
                args = [args]
            if not isinstance(args, list):
                raise ValueError(f"Invalid MCP config for '{name}': 'args' must be a list of strings.")
            args = [str(a) for a in args]

            # Transport inference if missing
            transport = cfg.get("transport")
            if not transport:
                if command:
                    transport = "stdio"
                elif url:
                    transport = "streamable_http"
                else:
                    raise ValueError(
                        f"Invalid MCP config for '{name}': provide either 'url' (remote) or 'command' (stdio)."
                    )

            transport = str(transport)

            # Sanity checks per transport style
            if transport == "stdio":
                if not command:
                    raise ValueError(f"Invalid MCP config for '{name}': transport 'stdio' requires 'command'.")
            else:
                if not url:
                    raise ValueError(
                        f"Invalid MCP config for '{name}': transport '{transport}' requires 'url'."
                    )

            # Expand headers/env (secrets stay in .env, not JSON)
            raw_headers = cfg.get("headers", {}) or {}
            headers = _expand_env_in_dict(raw_headers, context=f"{name}.headers")

            raw_env = cfg.get("env", {}) or {}
            env = _expand_env_in_dict(raw_env, context=f"{name}.env")

            servers[name] = MCPServerConfig(
                name=name,
                transport=transport,
                url=str(url) if url else None,
                command=str(command) if command else None,
                args=args,
                headers=headers,
                env=env,
            )

        self._servers = servers
        logger.info(f"External MCP servers loaded: {list(self._servers.keys())}")

        # Helpful debug logs (do not print secret values)
        for s in self._servers.values():
            safe_headers = list(s.headers.keys())
            safe_env = list(s.env.keys())

            if s.transport == "stdio":
                logger.debug(
                    f"MCP server '{s.name}' | transport=stdio | command={s.command!r} | args_count={len(s.args)} "
                    f"| env_keys={safe_env} | headers={safe_headers}"
                )
            else:
                logger.debug(
                    f"MCP server '{s.name}' | transport={s.transport} | url={s.url!r} "
                    f"| headers={safe_headers} | env_keys={safe_env}"
                )

        return servers

    async def connect(self) -> None:
        """
        Initialize the underlying MultiServerMCPClient.

        Must be called before `get_tools()`.

        What this does:
        - Loads config if not already loaded
        - Builds connection map for all servers in the adapter format
        - Initializes MultiServerMCPClient
        - Clears tool cache (fresh discovery per process boot)
        """
        if not self._servers:
            self.load_config()

        conn_map: Dict[str, Dict[str, Any]] = {}

        for name, server in self._servers.items():
            conn: Dict[str, Any] = {"transport": server.transport}

            # Remote servers
            if server.url:
                conn["url"] = server.url

            # stdio servers
            if server.command:
                conn["command"] = server.command
            if server.args:
                conn["args"] = server.args

            # Headers typically apply to HTTP transports
            if server.headers:
                conn["headers"] = server.headers

            # Env is primarily for stdio servers (ex: Notion MCP via npx)
            if server.env:
                conn["env"] = server.env

            conn_map[name] = conn

        # Some adapter versions support tool_name_prefix; some don't.
        # Try modern signature first; fall back gracefully.
        try:
            self._client = MultiServerMCPClient(
                conn_map,
                tool_name_prefix=True,  # avoids collisions across MCP servers
            )
            logger.debug("MCP client initialized (tool_name_prefix enabled).")
        except TypeError:
            logger.warning(
                "MultiServerMCPClient does not support tool_name_prefix in this version. "
                "Continuing without tool name prefixing."
            )
            self._client = MultiServerMCPClient(conn_map)
            logger.info("MCP client initialized (tool_name_prefix disabled).")

        self._tools_cache.clear()
        logger.debug("MCP client connected and tool cache cleared.")

    async def get_tools(self, server_name: str) -> List[Any]:
        """
        Discover and return tools for a specific MCP server.

        Caching:
        - First call triggers MCP discovery (list_tools) via adapter
        - Subsequent calls return cached tools (per server_name)

        Args:
            server_name: The key from config, e.g. "notionApi"

        Returns:
            List[Any]: LangChain tool objects returned by the MCP adapter
        """
        if server_name in self._tools_cache:
            logger.info(f"Returning cached tools for MCP server: {server_name}")
            return self._tools_cache[server_name]

        if not self._client:
            raise RuntimeError("MCPClient not connected. Call await connect() first.")

        if server_name not in self._servers:
            raise KeyError(
                f"Unknown MCP server '{server_name}'. Available servers: {list(self._servers.keys())}"
            )

        logger.debug(f"Discovering tools from MCP server: {server_name}")

        try:
            tools = await self._client.get_tools(server_name=server_name)
        except Exception:
            # Log full trace for AnyIO/MCP exceptions (401/403, connection errors, etc.)
            logger.exception(f"Failed to discover tools from MCP server: {server_name}")
            raise

        self._tools_cache[server_name] = tools

        logger.debug(f"Discovered {len(tools)} tools from '{server_name}'.")
        for tool in tools:
            logger.debug(f"[{server_name}] tool={tool.name}")

        return tools

    async def get_all_tools(self) -> Dict[str, List[Any]]:
        """
        Discover tools from all configured MCP servers.

        Returns:
            Dict[str, List[Any]]: mapping of server_name -> tools list

        Notes:
        - If one server fails, it is better to continue and return what succeeded.
          This function is resilient by default and logs per-server errors.
        """
        if not self._client:
            raise RuntimeError("MCPClient not connected. Call await connect() first.")

        all_tools: Dict[str, List[Any]] = {}
        for name in self._servers.keys():
            try:
                all_tools[name] = await self.get_tools(name)
            except Exception as e:
                logger.warning(f"Tool discovery failed for server '{name}': {e}")
                all_tools[name] = []

        return all_tools
