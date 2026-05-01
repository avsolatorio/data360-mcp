#!/usr/bin/env python3
"""Print LangGraph v2 stream events (tokens + tools) from the Data360 MCP agent.

Contrasts with ``parent_graph_demo.py``, which uses ``ainvoke`` only.

Requires a running MCP server and ``DATA360_MCP_URL``, ``OPENAI_API_KEY``.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys

from data360_mcp_agent import aiter_data360_mcp_agent_events, create_data360_mcp_agent
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

load_dotenv()


def _preview(obj: object, limit: int = 200) -> str:
    s = json.dumps(obj, default=str) if not isinstance(obj, str) else obj
    if len(s) > limit:
        return s[:limit] + "…"
    return s


async def main() -> None:
    if not os.getenv("DATA360_MCP_URL", "").strip():
        print("Set DATA360_MCP_URL.", file=sys.stderr)
        sys.exit(1)
    if not os.getenv("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY.", file=sys.stderr)
        sys.exit(1)

    query = os.getenv(
        "DATA360_DEMO_QUERY",
        "Population of Kenya for the last 5 years (use tools).",
    )

    agent = await create_data360_mcp_agent(llm_streaming=True)

    input_state = {"messages": [HumanMessage(content=query)]}

    print("Streaming events (v2) — event / name / metadata.langgraph_node / chunk preview:\n")
    async for ev in aiter_data360_mcp_agent_events(agent, input_state, version="v2"):
        event = ev.get("event")
        name = ev.get("name")
        meta = ev.get("metadata") or {}
        node = meta.get("langgraph_node", "")
        data = ev.get("data", {})
        chunk = data.get("chunk") if isinstance(data, dict) else None
        chunk_s = _preview(chunk) if chunk is not None else ""
        print(
            f"  {event!r}  name={name!r}  node={node!r}  "
            f"chunk={chunk_s or '—'}"
        )


if __name__ == "__main__":
    asyncio.run(main())
