"""
Browse tool — calls the browse MCP server over HTTP.
"""

import json
import logging

from app.agents.mcp_client import call_mcp_tool_async
from app.core.config import settings

log = logging.getLogger(__name__)


async def browse_fetch(url: str) -> str:
    """Fetch a job page via the browse MCP server and return its snapshot."""
    log.info("[browse_tool] browse_fetch → MCP:fetch url=%r", url)
    result = await call_mcp_tool_async(settings.MCP_BROWSE_URL, "fetch", {"url": url})
    log.info("[browse_tool] browse_fetch ← done chars=%d", len(result))
    return result


async def browse_extract(url: str, schema: dict, model_name: str = "") -> str:
    """Fetch a job page and extract structured fields via the browse MCP server."""
    log.info("[browse_tool] browse_extract → MCP:extract url=%r", url)
    result = await call_mcp_tool_async(
        settings.MCP_BROWSE_URL,
        "extract",
        {"url": url, "schema": schema},
    )
    log.info("[browse_tool] browse_extract ← done chars=%d", len(result))
    return result
