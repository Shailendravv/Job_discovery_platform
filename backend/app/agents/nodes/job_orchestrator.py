"""
Job Search & Browse Orchestrator
=================================
Multi-tool agent connecting to the unified `job-server` MCP which exposes:
  - search(query, max_results)   → SearXNG results with skill detection
  - fetch(url)                   → camofox accessibility-tree snapshot
  - extract(url, schema)         → camofox + Ollama structured extraction

The agent follows a strict search → fetch/extract chain so it never
stops at snippets alone.

Run with:
    python -m app.agents.nodes.job_orchestrator
"""

import asyncio
import json
import logging
import os
import sys
from contextlib import AsyncExitStack
from datetime import datetime
from typing import Any

import ollama
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

log = logging.getLogger(__name__)

MODEL_NAME = os.getenv("OLLAMA_MODEL", "llama3")
MODEL_TEMPERATURE = float(os.getenv("OLLAMA_TEMPERATURE", "0.0"))
HISTORY_DIR = os.getenv("AGENT_HISTORY_DIR", "agent_history")
MAX_TOOL_RESULT_CHARS = int(os.getenv("MAX_TOOL_RESULT_CHARS", "8000"))

os.makedirs(HISTORY_DIR, exist_ok=True)

SYSTEM_PROMPT = """You are a job search assistant with access to a unified job-server MCP that provides three tools:

  - job-server_search(query, max_results): search for jobs via SearXNG. Returns titles, URLs, snippets, and detected skills.
  - job-server_fetch(url): open a job listing URL in a real browser and return its full page content as an accessibility-tree snapshot.
  - job-server_extract(url, schema): open a job listing URL and extract specific structured fields you define via JSON Schema. Returns clean JSON.

RULES:
  1. Never describe a tool call in words — emit the actual tool_call.
  2. After receiving search results, always follow up with fetch or extract on the most relevant URL. Do not stop at snippets.
  3. For a fresh job search question, always start with job-server_search.
  4. Use extract when the user wants specific fields (title, company, salary, skills, location). Use fetch for open-ended reading.
  5. After fetch/extract, answer the user's question from the returned content and cite the URL.
"""


class JobOrchestrator:
    def __init__(self, session_id: str | None = None):
        self.session_id = session_id or datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.history_file = os.path.join(HISTORY_DIR, f"{self.session_id}.json")
        self.messages: list[dict[str, Any]] = []
        self.mcp_sessions: dict[str, ClientSession] = {}
        self.mcp_tools_by_server: dict[str, list[Any]] = {}
        self._tool_to_server: dict[str, str] = {}
        self.ollama_tools: list[dict] = []
        self._exit_stack = AsyncExitStack()

    async def connect(self, name: str, command: str, args: list[str]):
        params = StdioServerParameters(command=command, args=args)
        read, write = await self._exit_stack.enter_async_context(stdio_client(params))
        session = await self._exit_stack.enter_async_context(ClientSession(read, write))
        await session.initialize()

        tools = (await session.list_tools()).tools
        self.mcp_sessions[name] = session
        self.mcp_tools_by_server[name] = tools
        for t in tools:
            self._tool_to_server[f"{name}_{t.name}"] = name

        log.info("connected to %r; tools: %s", name, [t.name for t in tools])

    def rebuild_ollama_tools(self):
        self.ollama_tools = [
            {
                "type": "function",
                "function": {
                    "name": f"{server}_{t.name}",
                    "description": t.description or "",
                    "parameters": t.inputSchema,
                },
            }
            for server, tools in self.mcp_tools_by_server.items()
            for t in tools
        ]

    def _build_messages(self) -> list[dict[str, Any]]:
        return [{"role": "system", "content": SYSTEM_PROMPT}] + self.messages

    async def close(self):
        await self._exit_stack.aclose()

    def save_history(self):
        with open(self.history_file, "w", encoding="utf-8") as f:
            json.dump(self.messages, f, indent=2, default=str)

    async def _call_tool(self, prefixed_name: str, args: dict) -> str:
        server_name = self._tool_to_server.get(prefixed_name)
        if not server_name:
            return f"Unknown tool: {prefixed_name}"
        real_name = prefixed_name[len(server_name) + 1:]
        try:
            result = await self.mcp_sessions[server_name].call_tool(real_name, args)
            text = "".join(b.text for b in result.content if hasattr(b, "text"))
        except Exception as e:
            text = f"Tool error: {e}"

        if len(text) > MAX_TOOL_RESULT_CHARS:
            half = MAX_TOOL_RESULT_CHARS // 2 - 100
            text = text[:half] + "\n...[TRUNCATED]...\n" + text[-half:]
        return text

    async def handle_tools(self, tool_calls) -> dict:
        for tc in tool_calls:
            text = await self._call_tool(tc.function.name, tc.function.arguments or {})
            log.debug("tool result (%d chars): %.200s", len(text), text)
            self.messages.append({"role": "tool", "content": text})

        resp = ollama.chat(
            model=MODEL_NAME,
            messages=self._build_messages(),
            tools=self.ollama_tools,
            options={"temperature": MODEL_TEMPERATURE},
        )
        msg = resp["message"]

        if hasattr(msg, "tool_calls") and msg.tool_calls:
            self.messages.append({"role": "assistant", "tool_calls": msg.tool_calls})
            return await self.handle_tools(msg.tool_calls)

        content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")

        if not content.strip():
            self.messages.append({
                "role": "user",
                "content": "Based on the tool result, give the user a final answer.",
            })
            resp = ollama.chat(
                model=MODEL_NAME,
                messages=self._build_messages(),
                tools=self.ollama_tools,
                options={"temperature": MODEL_TEMPERATURE},
            )
            msg = resp["message"]
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                self.messages.append({"role": "assistant", "tool_calls": msg.tool_calls})
                return await self.handle_tools(msg.tool_calls)
            content = msg.get("content", "") if isinstance(msg, dict) else getattr(msg, "content", "")

        return {"role": "assistant", "content": content}


async def _main():
    agent = JobOrchestrator()
    try:
        # Connect to the unified job MCP server
        await agent.connect(
            "job-server",
            "python",
            ["-m", "app.agents.nodes.job_mcp_server"],
        )
        agent.rebuild_ollama_tools()

        print(f"\n--- Job Agent session: {agent.session_id} ---")
        print("Type 'quit' to exit.\n")

        while True:
            try:
                user_input = input("You: ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input or user_input.lower() in ("quit", "exit"):
                break

            agent.messages.append({"role": "user", "content": user_input})

            resp = ollama.chat(
                model=MODEL_NAME,
                messages=agent._build_messages(),
                tools=agent.ollama_tools,
                options={"temperature": MODEL_TEMPERATURE},
            )
            msg = resp["message"]

            if hasattr(msg, "tool_calls") and msg.tool_calls:
                agent.messages.append({"role": "assistant", "tool_calls": msg.tool_calls})
                final = await agent.handle_tools(msg.tool_calls)
                print(f"Assistant: {final['content']}\n")
                agent.messages.append(final)
            else:
                content = msg.get("content", "") if isinstance(msg, dict) else msg.content
                print(f"Assistant: {content}\n")
                agent.messages.append({"role": "assistant", "content": content})

            agent.save_history()
    finally:
        await agent.close()


def chat():
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    asyncio.run(_main())


if __name__ == "__main__":
    chat()
