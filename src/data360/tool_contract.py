"""Shared versioning between MCP tool JSON contracts and `@data360/tool-types` / UI packages."""

from __future__ import annotations

import json
from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=1)
def get_tool_contract_version() -> str:
    """Return the tool contract version (semver) shipped with this server build."""
    raw = resources.files("data360").joinpath("tool_contract_version.json").read_text(
        encoding="utf-8"
    )
    data = json.loads(raw)
    version = data.get("version")
    if not isinstance(version, str) or not version.strip():
        raise ValueError("tool_contract_version.json: missing or invalid 'version'")
    return version.strip()
