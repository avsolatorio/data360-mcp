"""Integration recipe text for hosts using ``data360-mcp-agent`` or custom LangGraph clients.

Published as MCP resource ``data360://agent-recipe`` so the server remains the
single catalog of: resources, named prompts, and how to compose them.
"""

from __future__ import annotations

# Keep in sync with module docstrings in prompts.py and the data360-mcp-agent README.
AGENT_RECIPE_MARKDOWN = """# Data360 MCP — host integration recipe

Use this with **LangGraph**, **LangChain**, or any client that loads MCP resources
and optional **MCP prompts** before the user message.

## 1. What to read from this server

| URI | Load | Role |
|-----|------|------|
| `data360://system-prompt` | **Required** | Search → codes → disaggregation → `get_data` → viz decision tree. |
| `data360://context` | **Recommended** | JSON: `current_date`, `current_year` (for “last N years”). |
| `data360://k360-narrative-style` | Optional | Markdown response contract for staged K360 narrative renderers. |
| `data360://agent-recipe` | Optional | This page; wire-up only (no extra tool semantics). |

**On-demand reference** (larger): `metadata-fields`, `data-schema`, `data-filters`, `search-usage`, `codelists`, `databases`.

## 2. MCP named prompts (`prompts/list` + `prompts/get`)

Call by name when the user turn matches the scenario; prepend the returned **string**
to the conversation as a **system** or **user** block (your host convention).

| Prompt | Arguments | When to use |
|--------|-----------|-------------|
| `indicator_search` | `query`, optional `country`, `required_dimensions` | Pick one indicator among many search hits. |
| `indicator_details` | `indicator_id`, `database_id`, optional `question` | Methodology / definition questions. |
| `country_data` | `query`, `country`, optional `start_year`, `end_year` | One country (or small list) + indicator theme → data + chart. |
| `gate_classifier` | _(none)_ | Decide in/out of scope for WB/Data360 **before** tool loop (mirrors gated agent). |
| `thematic_to_data` | `user_message` | Turn a broad development-economics question into economies, terms, years, peers. |
| `k360_research_compiler` | `user_question`, optional `data_question`, `tool_calls_json` | Build a stable JSON content packet from tool trace. |
| `k360_narrative` | `user_question`, `content_packet_json`, optional `raw_tool_results_json`, `include_claim_tags` | Convert packet + evidence into polished narrative markdown. |

**Typical composed turn (thematic question):**

1. (Optional) `prompts/get` → `gate_classifier` — run a small classifier; if out of scope, skip tools.
2. (Optional) `prompts/get` → `thematic_to_data` with the user text — paste result into `HumanMessage` or augment the last user turn.
3. Run the tool-using assistant with **`data360://system-prompt`** (plus `context`) as system instructions.

**Typical composed turn (country + theme):**

1. `prompts/get` → `country_data` with `query` + `country` (+ years).
2. Run the assistant with the same system stack as above.

## 3. Python: ``data360-mcp-agent`` package

- **Env:** `DATA360_MCP_URL` (e.g. `http://127.0.0.1:8000/mcp`), LLM key or inject `llm=`.
- **`create_data360_mcp_agent()`** — fetches tools + `system-prompt` and `context`, builds a LangChain agent.
- **`create_data360_gated_langgraph_node()`** — adds a **local** gate + reform step (same *intent* as `gate_classifier` + `thematic_to_data`; you can later replace those steps with `prompts/get` for a single source of truth).
- **Extra resources in the system stack:** `DATA360_AGENT_EXTRA_RESOURCES=data360://agent-recipe` (comma-separated URIs).

## 4. Composition order (recommended)

1. **System text:** `system-prompt` + `context` + any extra resource bodies + optional tool-name summary (as your client does).
2. **Optional prompt blocks:** from `prompts/get` (`country_data`, `thematic_to_data`, …).
3. **User:** current user message (optionally rewritten using `thematic_to_data` output).
4. **Assistant:** tool calls until done, then natural-language answer.

### Staged K360 flow

`Gate -> Rewriter -> Compile -> Narrative`

1. `gate_classifier` decides relevance.
2. `thematic_to_data` rewrites broad questions to data tasks.
3. Run tool loop (`system-prompt`) and collect tool trace + packet (`k360_research_compiler` optional).
4. Render final markdown with `k360_narrative` (+ optional `data360://k360-narrative-style`).

## 5. Design note

**Resources** carry always-on behavior and schemas. **MCP prompts** carry parameterized
playbooks for a *single* user turn. The **gate**/**reform** pair is playbook + policy on
the host; exposing them as prompts lets non-Python integrators reuse the same wording.
"""
