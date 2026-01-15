#!/usr/bin/env python3
"""
Demo script: LLM + MCP Tool Interaction (v3)

Shows the full flow with better output formatting.
"""

import asyncio
import json
import os

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools


def truncate_result(result_text: str, max_items: int = 20) -> str:
    """Truncate large results to avoid context overflow, keeping most recent data."""
    try:
        parsed = json.loads(result_text)
        if isinstance(parsed, dict) and 'data' in parsed:
            original_count = len(parsed.get('data', []))
            # Sort by TIME_PERIOD descending to get most recent first
            sorted_data = sorted(
                parsed['data'], 
                key=lambda x: str(x.get('TIME_PERIOD', '0')), 
                reverse=True
            )
            parsed['data'] = sorted_data[:max_items]
            parsed['_truncated'] = True
            parsed['_original_count'] = original_count
            parsed['_note'] = 'Showing most recent data first'
            return json.dumps(parsed)
        if isinstance(parsed, dict) and 'indicators' in parsed:
            parsed['indicators'] = parsed['indicators'][:3]
            return json.dumps(parsed)
        return result_text
    except:
        return result_text


async def demo_with_langchain():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not set!")
        return
    
    from langchain_openai import ChatOpenAI
    
    print("=" * 70)
    print("  DATA360 MCP + LLM DEMO")
    print("=" * 70)
    print()
    
    client = MultiServerMCPClient({
        'data360': {
            'transport': 'streamable_http',
            'url': 'http://127.0.0.1:8021/mcp',
        }
    })
    
    async with client.session('data360') as session:
        tools = await load_mcp_tools(session)
        print(f"✅ Connected to MCP server with {len(tools)} tools")
        print()
        
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        llm_with_tools = llm.bind_tools(tools)
        
        system_prompt = """You are a World Bank data analyst assistant.

WORKFLOW:
1. Use data360_search_and_validate to find the best indicator
2. Pick the TOP indicator that has has_country=true
3. Call data360_get_data ONCE for that indicator with appropriate filters
4. Present the data as a clear summary with the indicator name and source

FILTER TIPS:
- Use REF_AREA for country codes (e.g., "BRA" for Brazil, "KEN" for Kenya)
- For female data: SEX="F", male: SEX="M", total: SEX="_T"
- Always explain what the data shows"""

        # Get query from user
        print("-" * 70)
        query = input("👤 Enter your question: ").strip()
        if not query:
            query = "What is the unemployment rate in Brazil?"
            print(f"   Using default: {query}")
        print("-" * 70)
        print()
        
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": query}
        ]
        
        for iteration in range(1, 10):  # Allow up to 6 iterations
            print(f"🤖 Step {iteration}: ", end="")
            response = await llm_with_tools.ainvoke(messages)
            
            if not response.tool_calls:
                print("Generating response...")
                print()
                print("=" * 70)
                print("📊 ANSWER:")
                print("=" * 70)
                print()
                print(response.content)
                break
            
            tool_name = response.tool_calls[0]['name']
            tool_args = response.tool_calls[0]['args']
            print(f"Calling {tool_name}")
            
            # Show key args
            if 'query' in tool_args:
                print(f"        Query: '{tool_args['query']}'")
            if 'required_country' in tool_args:
                print(f"        Country: {tool_args['required_country']}")
            if 'indicator_id' in tool_args:
                print(f"        Indicator: {tool_args['indicator_id']}")
            
            # Execute tools
            tool_results = []
            for tc in response.tool_calls:
                tool = next((t for t in tools if t.name == tc['name']), None)
                if tool:
                    result = await tool.ainvoke(tc['args'])
                    result_text = truncate_result(result[0]['text'] if result else "{}")
                    tool_results.append({
                        "tool_call_id": tc['id'],
                        "content": result_text
                    })
                    
                    # Show result summary
                    try:
                        parsed = json.loads(result_text)
                        if 'indicators' in parsed and parsed['indicators']:
                            best = parsed['indicators'][0]
                            print(f"        ✅ Best match: {best['indicator_id']}")
                            print(f"           Has country: {'✅' if best.get('has_country') else '❌'}")
                        elif 'data' in parsed:
                            count = parsed.get('_original_count', len(parsed['data']))
                            print(f"        ✅ Retrieved {count} data points")
                            # Show sample
                            for d in parsed['data'][:3]:
                                year = d.get('TIME_PERIOD', '?')
                                val = d.get('OBS_VALUE', '?')
                                print(f"           {year}: {val}")
                    except:
                        pass
            
            messages.append(response)
            for tr in tool_results:
                messages.append({
                    "role": "tool",
                    "tool_call_id": tr["tool_call_id"],
                    "content": tr["content"]
                })
            print()


if __name__ == "__main__":
    asyncio.run(demo_with_langchain())
