---
id: MCP-001
repo: data360-mcp
title: SYSTEM_PROMPT — align with chatbot Writer/Planner rules
status: pending
priority: medium
depends_on:
  - BE-001
blocks: []
external_ref: vercel-ai-chatbot/TODO/BE-001-writer-planner-prompts.md
---

# MCP-001 — Sync `data360://system-prompt` with chatbot prompts

## Goal

Reduce drift between MCP-only LLM clients and the Data AI Chatbot: update `SYSTEM_PROMPT` in `src/data360/mcp_server/prompts.py` so tool-loop behavior and **final answer structure / link expectations** stay consistent with `vercel-ai-chatbot` `backend/app/ai/prompts.py` after **BE-001**.

## Context

- Resource registration: `src/data360/mcp_server/resources.py` exposes `data360://system-prompt`.
- Do not duplicate entire Writer prompt if inappropriate for MCP; align **non-conflicting** bullets: section order hints, link discipline, when to call `data360_get_viz_spec`.

## Implementation hints
- **Entry point:** `src/data360/mcp_server/prompts.py` — `SYSTEM_PROMPT` string literal lines 11–56.
- **Current structure:** 4 sections — `### Non-negotiable rule` (line 15), `### Operating loop` (line 19, 5-step workflow: search → codelist → availability → get data → visualize), `### Defaults` (line 47, 20-year range hardcoded in text), `### Output behavior` (line 52).
- **Exposed via:** `src/data360/mcp_server/resources.py` line 159–162 as MCP resource `data360://system-prompt`.
- **Desired behavior:** After BE-001 finalises section order and link discipline in the chatbot Writer prompt, mirror the non-conflicting bullets here — specifically: section order hints for final answer, link discipline for API/indicator URLs, when to call `data360_get_viz_spec`. Do NOT duplicate the full Writer prompt.
- **Test file:** No tests for SYSTEM_PROMPT content. After update, manually verify that `data360://system-prompt` resource returns the updated string via MCP inspector or a quick test script.
- **Gotchas:** SYSTEM_PROMPT is a plain string — preserve existing markdown formatting exactly. The 20-year default is hardcoded in text (line 48–49), not a config variable. Sync changes in `prompts.py` to `README.md` and `docs/overview.md` if they quote the resource content.

## Acceptance criteria

- [ ] `SYSTEM_PROMPT` updated to reflect agreed structure and link/viz nudges (scoped to MCP tool use).
- [ ] README/docs that quote the resource updated if needed (`README.md`, `docs/overview.md`).
- [ ] No contradiction with existing mandatory tool-call rules in the same file.

## Dependencies

- **BE-001** (vercel-ai-chatbot) — source of truth for product wording; complete or sync in pair review.
