#!/usr/bin/env python3
"""Single-turn LangChain agent: MCP tools + server resources + create_agent."""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from typing import Any, cast

from langchain.agents import create_agent
from langchain_core.documents.base import Blob
from langchain_core.messages import HumanMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_openai import ChatOpenAI

_TOOL_DESC_PREVIEW_LEN = 240


def _connection() -> dict[str, str]:
    url = os.getenv("DATA360_MCP_URL", "").strip().rstrip("/")
    if not url:
        print(
            "Set DATA360_MCP_URL (e.g. http://127.0.0.1:8000/mcp — match your server port)",
            file=sys.stderr,
        )
        sys.exit(1)
    transport = os.getenv("DATA360_MCP_TRANSPORT", "streamable_http").strip()
    if not transport:
        transport = "streamable_http"
    return {"url": url, "transport": transport}


async def run_once(user_query: str) -> None:
    server_name = "data360"
    connections: dict[str, Any] = {server_name: _connection()}
    client = MultiServerMCPClient(cast(Any, connections))

    tools = await client.get_tools(server_name=server_name)
    if not tools:
        print("No tools returned from MCP server.", file=sys.stderr)
        sys.exit(1)

    blobs: list[Blob] = await client.get_resources(
        server_name=server_name,
        uris=["data360://system-prompt", "data360://context"],
    )
    texts: dict[str, str] = {}
    for blob in blobs:
        uri = (blob.metadata or {}).get("uri", "")
        if uri:
            texts[uri] = blob.as_string()

    system_prompt = texts.get("data360://system-prompt", "").strip()
    context = texts.get("data360://context", "").strip()
    if not system_prompt:
        print(
            "Warning: data360://system-prompt was empty; continuing with tools only.",
            file=sys.stderr,
        )

    lim = _TOOL_DESC_PREVIEW_LEN
    tool_lines = []
    for t in tools:
        desc = (t.description or "")[:lim]
        tool_lines.append(f"- `{t.name}`: {desc}")
    tool_block = "\n".join(tool_lines)

    full_system = system_prompt
    if context:
        full_system += "\n\n### Runtime Context\n" + context
    if tool_block:
        full_system += "\n\n## Registered tools (summary)\n" + tool_block

    if not os.getenv("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY.", file=sys.stderr)
        sys.exit(1)

    model = os.getenv("DATA360_AGENT_MODEL", "gpt-4.1-mini")
    llm = ChatOpenAI(model=model, temperature=0)
    agent = create_agent(llm, tools, system_prompt=full_system)

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_query)]},
        config={
            "recursion_limit": int(os.getenv("DATA360_AGENT_RECURSION_LIMIT", "50"))
        },
    )

    for msg in result["messages"]:
        role = type(msg).__name__
        content = getattr(msg, "content", "")
        print(f"[{role}]\n{content}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "query",
        nargs="?",
        default="Show population for Kenya for the last 5 years.",
        help="User question",
    )
    args = parser.parse_args()
    asyncio.run(run_once(args.query))


if __name__ == "__main__":
    main()
