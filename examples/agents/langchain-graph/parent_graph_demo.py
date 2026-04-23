#!/usr/bin/env python3
"""Minimal parent graph: START → Data360 specialist → END.

Copy this pattern into your app and add routers, other agent nodes, or tools.
"""

from __future__ import annotations

import asyncio
import os
import sys

from data360_mcp_agent.plugin import MessagesState, create_data360_langgraph_node
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

    print(f"DATA360_MCP_URL={mcp_url}")

    llm = ChatOpenAI(
        model=os.getenv("DATA360_AGENT_MODEL", "gpt-4.1-mini"),
        temperature=0,
    )

    data360_node = await create_data360_langgraph_node(llm=llm)

    graph = StateGraph(MessagesState)
    graph.add_node("data360", data360_node)
    graph.add_edge(START, "data360")
    graph.add_edge("data360", END)

    app = graph.compile()

    query = os.getenv(
        "DATA360_DEMO_QUERY",
        "Population of Kenya for the last 5 years (use tools).",
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
        print(f"[{name}] {preview[:500]}\n")


if __name__ == "__main__":
    asyncio.run(main())
