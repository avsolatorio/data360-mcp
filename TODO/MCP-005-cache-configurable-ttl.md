---
id: MCP-005
repo: data360-mcp
title: cache — make TTL configurable via MCP_CACHE_TTL env var
status: pending
depends_on: []
blocks: []
source: pr-review
file_ref: src/data360/mcp_server/cache.py
line_ref: 23
---

# MCP-005 — Configurable cache TTL via `MCP_CACHE_TTL` environment variable

## Goal

Replace the hardcoded 300-second TTL in the cache module with a value read from the `MCP_CACHE_TTL` environment variable, keeping 300 as the default.

## Context

- PR review flagged a hardcoded `300` (seconds) in `src/data360/mcp_server/cache.py` line 23.
- The file `src/data360/mcp_server/cache.py` does not currently exist in the repo; the cache logic may live elsewhere (e.g. `src/data360/config.py`). Locate the hardcoded value before patching.
- Making the TTL configurable allows operators to tune cache aggressiveness in different deployment environments without code changes.

## Acceptance criteria

- [ ] Cache TTL is read from `os.environ.get("MCP_CACHE_TTL", 300)` (or equivalent via `src/data360/config.py` if that module centralises env vars).
- [ ] Value is cast to `int` with a clear `ValueError` or fallback if the env var is set to a non-integer.
- [ ] Default behaviour (TTL = 300 s) is unchanged when the env var is unset.
- [ ] `MCP_CACHE_TTL` documented in `README.md` (or equivalent config docs) under environment variables.
- [ ] Unit test added verifying TTL is picked up from the environment variable.

## Implementation hints

- **Entry point:** The file `src/data360/mcp_server/cache.py` (line 23 per the PR review) does not yet exist in the repo. The likely location for the hardcoded TTL is wherever a TTL-based caching layer is added. The existing settings system in `src/data360/config.py` uses `pydantic-settings` with `env_prefix="MCP_"` (`MCPServerSettings` class, line ~10). The cleanest approach is to add a `cache_ttl: int = Field(default=300, ...)` field to `MCPServerSettings` — with `env_prefix="MCP_"` already in place, it will automatically read `MCP_CACHE_TTL` from the environment.
- **Current behavior:** TTL is hardcoded to `300` (seconds) in the cache module (or will be when that module is created).
- **Desired behavior:** TTL is read from `MCP_CACHE_TTL` env var via `MCPServerSettings.cache_ttl`, defaulting to `300`. Cache module imports `get_mcp_server_settings()` and uses `settings.cache_ttl`.
- **Test file:** No dedicated cache test file exists yet. Create `tests/test_cache.py`. Test that `MCPServerSettings(MCP_CACHE_TTL=600).cache_ttl == 600` and that the default is `300` when env var is unset.
- **Prior art:** `src/data360/config.py` `MCPServerSettings` — all other MCP tunables (port, log_level, charts_api_url) follow exactly this pattern. Add `cache_ttl` here to stay consistent.
- **Gotchas:** `get_mcp_server_settings()` is decorated with `@ft.cache` (functools LRU cache), meaning it returns the same instance after first call. In tests, ensure settings are created fresh with `MCPServerSettings(...)` directly rather than calling the cached factory, or use `monkeypatch.setenv` before the factory is first called.

## Dependencies

- None.
