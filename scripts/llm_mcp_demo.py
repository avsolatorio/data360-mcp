#!/usr/bin/env python3
"""
Demo script: LLM + MCP Tool Interaction (v4)

Shows the full flow with token tracking and optimized metadata handling.
"""

import asyncio
import json
import os

from dotenv import load_dotenv

load_dotenv()

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools


class TokenTracker:
    """Track cumulative token usage across the conversation."""
    
    def __init__(self):
        self.total_input = 0
        self.total_output = 0
        self.calls = 0
    
    def add(self, response):
        """Add token usage from a response."""
        if hasattr(response, 'response_metadata'):
            usage = response.response_metadata.get('token_usage', {})
            self.total_input += usage.get('prompt_tokens', 0)
            self.total_output += usage.get('completion_tokens', 0)
            self.calls += 1
    
    def print_step(self, response):
        """Print token usage for this step."""
        if hasattr(response, 'response_metadata'):
            usage = response.response_metadata.get('token_usage', {})
            input_tokens = usage.get('prompt_tokens', 0)
            output_tokens = usage.get('completion_tokens', 0)
            print(f"        📈 Tokens: {input_tokens:,} in / {output_tokens:,} out")
    
    def print_summary(self):
        """Print cumulative token summary."""
        print()
        print("-" * 70)
        print(f"📊 TOKEN SUMMARY ({self.calls} LLM calls):")
        print(f"   Input:  {self.total_input:,} tokens")
        print(f"   Output: {self.total_output:,} tokens")
        print(f"   Total:  {self.total_input + self.total_output:,} tokens")
        print("-" * 70)


def truncate_result(result_text: str, max_items: int = 10) -> str:
    """Truncate large results to avoid context overflow, keeping most recent data."""
    try:
        parsed = json.loads(result_text)
        
        # Truncate data responses
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
        
        # Truncate search results - only keep essential fields
        if isinstance(parsed, dict) and 'value' in parsed:
            truncated_results = []
            for item in parsed['value'][:5]:  # Limit to top 5 results
                series = item.get('series_description', {})
                truncated_results.append({
                    'idno': series.get('idno'),
                    'name': series.get('name'),
                    'database_id': series.get('database_id'),
                    # Skip definition_long to save tokens - LLM can get it via get_metadata
                })
            return json.dumps({
                'results': truncated_results,
                '_total_count': parsed.get('@odata.count', len(parsed['value'])),
                '_note': 'Use get_metadata for full definitions'
            })
        
        # Truncate disaggregation - summarize dimensions
        if isinstance(parsed, dict) and any(k in parsed for k in ['TIME_PERIOD', 'REF_AREA', 'SEX']):
            summary = {}
            for key, values in parsed.items():
                if isinstance(values, list):
                    if len(values) > 10:
                        summary[key] = {
                            'count': len(values),
                            'sample': values[:5],
                            '_truncated': True
                        }
                    else:
                        summary[key] = values
                else:
                    summary[key] = values
            return json.dumps(summary)
        
        # Enhanced search results - don't truncate, we already limit to 5 in the tool
        if isinstance(parsed, dict) and 'indicators' in parsed:
            # Keep all indicators from search - tool already limits to 5
            return json.dumps(parsed)
        
        return result_text
    except:
        return result_text


# System prompt following the recommended workflow from data360://system-prompt
def get_system_prompt():
    from datetime import datetime
    current_date = datetime.now().strftime("%Y-%m-%d")
    return f"""You are a World Bank data analyst assistant using Data360 indicators.

CURRENT DATE: {current_date}

WORKFLOW:
1. Use data360_search_indicators(query) - returns top 5 with compact metadata
2. Pick the SINGLE best indicator matching user intent - do NOT search again
3. Use data360_get_disaggregation to check country/time availability
4. Use data360_get_data with appropriate filters to fetch data
5. Present the data as a clear summary

FILTER TIPS:
- REF_AREA: country codes (e.g., "BRA" for Brazil, "KEN" for Kenya, "USA" for United States)
- Use data360_find_codelist_value("REF_AREA", "Kenya") to get codes
- SEX: "F" (Female), "M" (Male), "_T" (Total)
- Use timePeriodFrom/timePeriodTo for year ranges
- DO NOT use FREQ filter - it breaks queries

When user asks for "last N years", calculate from current year ({datetime.now().year}).
Be concise in your final answer. Include the indicator name and source database."""


async def demo_with_langchain():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ OPENAI_API_KEY not set!")
        return
    
    from langchain_openai import ChatOpenAI
    
    print("=" * 70)
    print("  DATA360 MCP + LLM DEMO (with Token Tracking)")
    print("=" * 70)
    print()
    
    tracker = TokenTracker()
    
    client = MultiServerMCPClient({
        'data360': {
            'transport': 'sse',
            'url': 'http://127.0.0.1:8021/sse',
        }
    })
    
    async with client.session('data360') as session:
        tools = await load_mcp_tools(session)
        print(f"✅ Connected to MCP server with {len(tools)} tools:")
        for t in tools:
            print(f"   - {t.name}")
        print()
        
        # Fetch resources from MCP server
        print("📚 Loading resources from MCP server...")
        try:
            # Read system prompt resource
            system_prompt_result = await session.read_resource("data360://system-prompt")
            system_prompt = system_prompt_result.contents[0].text if system_prompt_result.contents else ""
            
            # Read context resource (includes current date)
            context_result = await session.read_resource("data360://context")
            context = context_result.contents[0].text if context_result.contents else "{}"
            
            # Combine into full system message
            full_system_prompt = f"{system_prompt}\n\n### Runtime Context\n{context}"
            print(f"   ✅ Loaded system-prompt and context resources")
        except Exception as e:
            print(f"   ⚠️ Could not load resources: {e}")
            print(f"   Using fallback system prompt")
            full_system_prompt = get_system_prompt()
        print()
        
        llm = ChatOpenAI(model="gpt-4o-mini", temperature=0)
        llm_with_tools = llm.bind_tools(tools)
        
        # Initialize conversation history
        messages = [{"role": "system", "content": full_system_prompt}]
        
        print("💡 Commands:")
        print("   /clear   - Clear conversation history")
        print("   quit     - Exit the demo")
        print("-" * 70)
        
        while True:
            try:
                print()
                query = input("👤 Enter your question: ").strip()
                
                if not query:
                    continue
                    
                if query.lower() in ['quit', 'exit']:
                    print("👋 Goodbye!")
                    break
                    
                if query.lower() == '/clear':
                    messages = [{"role": "system", "content": full_system_prompt}]
                    print("🧹 Conversation history cleared.")
                    print("-" * 70)
                    continue
                
                print("-" * 70)
                
                # Add user message to history
                messages.append({"role": "user", "content": query})
                
                # Run agent loop for this turn
                for iteration in range(1, 15):  # Allow up to 15 iterations per turn
                    print(f"🤖 Step {iteration}: ", end="")
                    response = await llm_with_tools.ainvoke(messages)
                    # Print content (reasoning) if present, even if there are tool calls
                    if response.content:
                        print(f"        {response.content.strip()}")
                        print()

                    if not response.tool_calls:
                        # Handle Chain-of-Thought (intermediate steps)
                        # If it contains "Thought:", assume it's reasoning and continue
                        if "Thought:" in response.content:
                            print("🤔 Reasoning (continuing)...")
                            print()
                            messages.append(response)
                            continue

                        print("Generating response...")
                        tracker.print_step(response)
                        print()
                        print("=" * 70)
                        print("📊 ANSWER:")
                        print("=" * 70)
                        print()
                        print(response.content)
                        print()
                        print("=" * 70)
                        
                        # Add final response to history
                        messages.append(response)
                        break
                    
                    tool_name = response.tool_calls[0]['name']
                    tool_args = response.tool_calls[0]['args']
                    print(f"Calling {tool_name}")
                    tracker.print_step(response)
                    
                    # Show ALL args
                    print(f"        Args: {json.dumps(tool_args, indent=2).replace(chr(10), chr(10) + '              ')}")
                    
                    # Execute tools
                    tool_results = []
                    for tc in response.tool_calls:
                        tool = next((t for t in tools if t.name == tc['name']), None)
                        if tool:
                            try:
                                result = await tool.ainvoke(tc['args'])
                                raw_text = result[0]['text'] if result else "{}"
                            except Exception as e:
                                raw_text = json.dumps({"error": str(e)})

                            # Debug: show raw JSON if enabled
                            DEBUG = os.environ.get('DEBUG', '').lower() == 'true'
                            if DEBUG:
                                print(f"\n        📋 RAW JSON ({len(raw_text)} chars):")
                                try:
                                    raw_parsed = json.loads(raw_text)
                                    print(json.dumps(raw_parsed, indent=2)[:2000])  # Limit output
                                    if len(raw_text) > 2000:
                                        print(f"        ... (truncated, {len(raw_text)} total chars)")
                                except:
                                    print(raw_text[:500])
                                print()
                            
                            result_text = truncate_result(raw_text)
                            
                            # Log size reduction
                            reduction = (1 - len(result_text) / len(raw_text)) * 100 if raw_text else 0
                            if reduction > 5:
                                print(f"        💾 Result truncated: {len(raw_text):,} → {len(result_text):,} chars ({reduction:.0f}% saved)")
                            
                            tool_results.append({
                                "tool_call_id": tc['id'],
                                "content": result_text
                            })
                            
                            # Show result summary
                            try:
                                parsed = json.loads(result_text)
                                # Handle search results (from our enhanced search)
                                if 'indicators' in parsed:
                                    country = parsed.get('required_country')
                                    returned = len(parsed['indicators'])
                                    total = parsed.get('total_found', returned)
                                    print(f"        ✅ Returning {returned} of {total} total" + 
                                          (f" (country: {country})" if country else ""))
                                    for ind in parsed['indicators']:  # Show ALL indicators
                                        covers = ind.get('covers_country')
                                        dims = ind.get('dimensions', [])
                                        latest = ind.get('latest_data', '?')
                                        trange = ind.get('time_period_range')
                                        range_str = f" [{trange}]" if trange else ""
                                        coverage_str = f"{'✅' if covers else '❌'}" if covers is not None else "  "
                                        dims_str = f" [{','.join(dims)}]" if dims else ""
                                        print(f"           {coverage_str} {ind.get('idno')}: {ind.get('name', '')[:35]}... (→{latest}){range_str}{dims_str}")
                                elif 'results' in parsed:
                                    print(f"        ✅ Found {parsed.get('_total_count', len(parsed['results']))} indicators")
                                    for r in parsed['results'][:2]:
                                        print(f"           - {r.get('idno')}: {r.get('name', '')[:50]}")
                                elif 'data' in parsed:
                                    count = parsed.get('_original_count', len(parsed['data']))
                                    print(f"        ✅ Retrieved {count} data points")
                                    for d in parsed['data'][:3]:
                                        year = d.get('TIME_PERIOD', '?')
                                        val = d.get('OBS_VALUE', '?')
                                        print(f"           {year}: {val}")
                                elif 'TIME_PERIOD' in parsed or 'REF_AREA' in parsed or 'dimensions' in parsed:
                                    print(f"        ✅ Disaggregation loaded")
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
                
                # Print token summary after each turn
                tracker.print_summary()
            
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    try:
        asyncio.run(demo_with_langchain())
    except KeyboardInterrupt:
        pass
