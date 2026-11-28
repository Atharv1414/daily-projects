"""Connects the agent to the MCP server, over stdio (real use) or in memory (tests)."""

from __future__ import annotations

import json
import os
import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import date
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.memory import create_connected_server_and_client_session

from ..server import create_server
from ..store import CaseStore


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool


@dataclass(frozen=True)
class ToolOutcome:
    text: str
    is_error: bool

    def json(self) -> Any:
        try:
            return json.loads(self.text)
        except json.JSONDecodeError:
            return self.text


class MCPGateway:
    """The agent's only door to the casework system."""

    def __init__(self, session: ClientSession) -> None:
        self.session = session
        self.server_instructions = ""

    async def initialise(self) -> None:
        result = await self.session.initialize()
        self.server_instructions = result.instructions or ""

    async def list_tools(self) -> list[ToolSpec]:
        listed = await self.session.list_tools()
        return [
            ToolSpec(
                name=t.name,
                description=t.description or "",
                input_schema=t.inputSchema,
                read_only=bool(t.annotations and t.annotations.readOnlyHint),
            )
            for t in listed.tools
        ]

    async def call(self, name: str, args: dict[str, Any]) -> ToolOutcome:
        result = await self.session.call_tool(name, args)
        parts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
        if result.structuredContent is not None and not result.isError:
            data = result.structuredContent
            # FastMCP wraps non-object returns as {"result": ...}
            text = json.dumps(data.get("result", data) if len(data) == 1 else data)
        else:
            text = "\n".join(parts)
        return ToolOutcome(text=text, is_error=bool(result.isError))


@asynccontextmanager
async def stdio_gateway(env: dict[str, str] | None = None) -> AsyncIterator[MCPGateway]:
    """Starts the server as a subprocess, exactly as an MCP host such as Claude Desktop would."""
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "planning_casework_mcp.server"],
        env={**os.environ, **(env or {})},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        gateway = MCPGateway(session)
        await gateway.initialise()
        yield gateway


@asynccontextmanager
async def memory_gateway(store: CaseStore, today: date) -> AsyncIterator[MCPGateway]:
    """Same protocol, no subprocess: the server runs in this process over memory streams."""
    server = create_server(store, today)
    async with create_connected_server_and_client_session(server) as session:
        gateway = MCPGateway(session)
        # create_connected_server_and_client_session has already initialised the session.
        gateway.server_instructions = server.instructions or ""
        yield gateway
