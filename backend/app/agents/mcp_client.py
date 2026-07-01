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

# Connection errors to suppress gracefully during cleanup on Windows
_CONNECTION_ERRORS = (
    ConnectionResetError,
    ConnectionAbortedError,
    ConnectionError,
    OSError,
    asyncio.CancelledError,
)


async def _call_tool_async(base_url: str, tool_name: str, arguments: dict) -> str:
    """
    Call an MCP tool over StreamableHTTP.

    Wraps the session lifecycle in a try/except to gracefully handle
    Windows ``ConnectionResetError`` (WinError 10054) that fires when
    the remote end closes the socket before the proactor transport
    finishes cleanup.  This is a noisy-but-harmless asyncio issue on
    Windows; we suppress the traceback and log it at debug level.
    """
    result_content = ""
    try:
        async with streamablehttp_client(f"{base_url}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                log.debug("[mcp_client] \u2192 %s/mcp  tool=%r args=%r", base_url, tool_name, arguments)
                result = await session.call_tool(tool_name, arguments)
                if result.content:
                    first = result.content[0]
                    result_content = first.text if hasattr(first, "text") else str(first)
    except _CONNECTION_ERRORS as exc:
        # Windows proactor transport raises ConnectionResetError during
        # session teardown when the server closed the connection first.
        # This is expected behaviour — no action needed.
        log.debug(
            "[mcp_client] connection closed during session lifecycle "
            "(expected on Windows): %s: %s",
            type(exc).__name__,
            exc,
        )

    return result_content


def call_mcp_tool(base_url: str, tool_name: str, arguments: dict, timeout: float = 120.0) -> str:
    """
    Call a single MCP tool over StreamableHTTP (sync wrapper).
    Runs in a fresh thread to avoid conflicts with FastAPI's event loop.
    """
    def _run():
        return asyncio.run(_call_tool_async(base_url, tool_name, arguments))

    future = _executor.submit(_run)
    return future.result(timeout=timeout)


def call_mcp_tool_async(base_url: str, tool_name: str, arguments: dict):
    """
    Public async wrapper for MCP tool calls.
    """
    return _call_tool_async(base_url, tool_name, arguments)
