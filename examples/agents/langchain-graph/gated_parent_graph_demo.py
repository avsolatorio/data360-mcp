#!/usr/bin/env python3
"""Parent graph with a **gated** Data360 node (relevance + optional reformulation).

Compare with ``parent_graph_demo.py`` (always invokes the MCP agent).

Environment:
- ``DATA360_DEMO_USE_GATED=0`` — use the non-gated node (default **1** = gated).
- ``DATA360_GATE_SKIP_MODE`` — ``silent`` (default) or ``refusal`` when out of scope.
- ``DATA360_DEMO_QUERY`` — user message (try a thematic dev-econ question or chit-chat).
"""

from __future__ import annotations

import asyncio
import os
import sys

from data360_mcp_agent.plugin import (
    MessagesState,
    create_data360_gated_langgraph_node,
    create_data360_langgraph_node,
)
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph

load_dotenv()


async def main() -> None:
    mcp_url = os.getenv("DATA360_MCP_URL", "").strip()
    if not mcp_url:
        print("Set DATA360_MCP_URL.", file=sys.stderr)
        sys.exit(1)
    if not os.getenv("OPENAI_API_KEY"):
        print("Set OPENAI_API_KEY.", file=sys.stderr)
        sys.exit(1)

    use_gated = os.getenv("DATA360_DEMO_USE_GATED", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )
    print(f"DATA360_MCP_URL={mcp_url}")
    print(f"gated={use_gated} DATA360_GATE_SKIP_MODE={os.getenv('DATA360_GATE_SKIP_MODE', '')!r}")

    llm = ChatOpenAI(
        model=os.getenv("DATA360_AGENT_MODEL", "gpt-4.1-mini"),
        temperature=0,
    )

    if use_gated:
        data360_node = await create_data360_gated_langgraph_node(
            llm=llm,
            skip_mode="silent",
            apply_skip_mode_from_env=True,
            enable_reformulation=True,
        )
    else:
        data360_node = await create_data360_langgraph_node(llm=llm)

    graph = StateGraph(MessagesState)
    graph.add_node("data360", data360_node)
    graph.add_edge(START, "data360")
    graph.add_edge("data360", END)

    app = graph.compile()

    query = os.getenv(
        "DATA360_DEMO_QUERY",
        "What are the main challenges facing Ghana's economic growth and public spending?",
    )
    result = await app.ainvoke(
        {
            "messages": [HumanMessage(content=query)],
        }
    )

    for msg in result.get("messages") or []:
        name = type(msg).__name__
        content = getattr(msg, "content", "")
        preview = content if isinstance(content, str) else repr(content)
        print(f"[{name}] {preview[:800]}\n")


if __name__ == "__main__":
    asyncio.run(main())
