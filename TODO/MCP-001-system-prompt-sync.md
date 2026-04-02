---
id: MCP-001
repo: data360-mcp
title: SYSTEM_PROMPT — align with chatbot Writer/Planner rules
status: pending
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

## Acceptance criteria

- [ ] `SYSTEM_PROMPT` updated to reflect agreed structure and link/viz nudges (scoped to MCP tool use).
- [ ] README/docs that quote the resource updated if needed (`README.md`, `docs/overview.md`).
- [ ] No contradiction with existing mandatory tool-call rules in the same file.

## Dependencies

- **BE-001** (vercel-ai-chatbot) — source of truth for product wording; complete or sync in pair review.
