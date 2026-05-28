"""
Browse tool — thin wrapper that delegates to the browse MCP server (Option B).
All camofox + Ollama logic lives in job_mcp_browse_server; this module is the
entry point used by the workflow.
"""

import logging
from app.agents.nodes.job_mcp_browse_server import _do_fetch, _do_extract

log = logging.getLogger(__name__)


def browse_fetch(url: str) -> str:
    """Fetch a job page and return its accessibility-tree snapshot."""
    log.info("[browse_tool] browse_fetch → delegating to mcp:browse _do_fetch url=%r", url)
    result = _do_fetch(url)
    log.info("[browse_tool] browse_fetch ← done chars=%d", len(result))
    return result


def browse_extract(url: str, schema: dict, model_name: str = "") -> str:
    """Fetch a job page and extract structured fields via Ollama."""
    log.info("[browse_tool] browse_extract → delegating to mcp:browse _do_extract url=%r", url)
    result = _do_extract(url, schema)
    log.info("[browse_tool] browse_extract ← done chars=%d", len(result))
    return result
