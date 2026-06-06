"""
Thin MCP client — calls tools on a FastMCP StreamableHTTP server.
Uses the official MCP Python SDK to handle session/protocol lifecycle.
"""

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamablehttp_client

log = logging.getLogger(__name__)

_executor = ThreadPoolExecutor(max_workers=4)


async def _call_tool_async(base_url: str, tool_name: str, arguments: dict) -> str:
    async with streamablehttp_client(f"{base_url}/mcp") as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            log.debug("[mcp_client] → %s/mcp  tool=%r args=%r", base_url, tool_name, arguments)
            result = await session.call_tool(tool_name, arguments)
            if not result.content:
                return ""
            first = result.content[0]
            return first.text if hasattr(first, "text") else str(first)


def call_mcp_tool(base_url: str, tool_name: str, arguments: dict, timeout: float = 120.0) -> str:
    """
    Call a single MCP tool over StreamableHTTP (sync wrapper).
    Runs in a fresh thread to avoid conflicts with FastAPI's event loop.
    """
    def _run():
        return asyncio.run(_call_tool_async(base_url, tool_name, arguments))

    future = _executor.submit(_run)
    return future.result(timeout=timeout)
