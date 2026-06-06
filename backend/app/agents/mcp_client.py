"""
Thin MCP client — sends JSON-RPC `tools/call` requests to a FastMCP HTTP server.

FastMCP mounts its JSON-RPC handler at POST /mcp (StreamableHTTP transport).
"""

import json
import logging
import httpx

log = logging.getLogger(__name__)


def call_mcp_tool(base_url: str, tool_name: str, arguments: dict, timeout: float = 120.0):
    """
    Call a single MCP tool over HTTP (StreamableHTTP / JSON-RPC 2.0).

    Returns the first text content item from the tool result.
    Raises on HTTP error or JSON-RPC error.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": arguments},
    }
    log.debug("[mcp_client] → %s/mcp  tool=%r args=%r", base_url, tool_name, arguments)

    response = httpx.post(
        f"{base_url}/mcp",
        json=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=timeout,
    )
    response.raise_for_status()

    # FastMCP may return multipart/mixed or plain JSON depending on version;
    # grab the first JSON object that looks like a JSON-RPC response.
    body = _parse_jsonrpc_body(response)

    if "error" in body:
        raise RuntimeError(f"MCP tool error from {tool_name!r}: {body['error']}")

    result = body.get("result", {})
    content = result.get("content", [])
    if not content:
        return ""

    # Return the text of the first content block
    first = content[0]
    return first.get("text", "") if isinstance(first, dict) else str(first)


def _parse_jsonrpc_body(response: httpx.Response) -> dict:
    """Handle plain JSON or the first JSON chunk in a multipart/mixed body."""
    ct = response.headers.get("content-type", "")
    if "multipart" in ct:
        # Extract first {...} object from the body
        text = response.text
        start = text.find("{")
        end = text.rfind("}") + 1
        if start != -1 and end > start:
            return json.loads(text[start:end])
        raise ValueError(f"No JSON object found in multipart body: {text[:200]!r}")
    return response.json()
