"""Ensure MCP tool contract versions stay aligned across Python, JSON, and @data360/tool-types."""

import json
import re
from pathlib import Path

import pytest

from data360.tool_contract import get_tool_contract_version

REPO_ROOT = Path(__file__).resolve().parents[1]

_TS_VERSION_PATTERN = re.compile(
    r'export const TOOL_CONTRACT_VERSION = "([^"]+)" as const',
)


def _version_from_json(path: Path) -> str:
    data = json.loads(path.read_text(encoding="utf-8"))
    v = data.get("version")
    assert isinstance(v, str) and v.strip()
    return v.strip()


@pytest.fixture
def contract_json_paths() -> list[Path]:
    return [
        REPO_ROOT / "contracts" / "tool-contract-version.json",
        REPO_ROOT / "src" / "data360" / "tool_contract_version.json",
        REPO_ROOT / "packages" / "tool-types" / "schemas" / "tool-contract-version.json",
    ]


def test_tool_contract_json_files_are_identical(contract_json_paths: list[Path]) -> None:
    contents = [p.read_text(encoding="utf-8") for p in contract_json_paths]
    assert len(set(contents)) == 1, "All tool-contract-version.json copies must be byte-identical"


def test_python_matches_json(contract_json_paths: list[Path]) -> None:
    versions = {_version_from_json(p) for p in contract_json_paths}
    assert len(versions) == 1
    expected = versions.pop()
    assert get_tool_contract_version() == expected


def test_typescript_version_literal_matches_json(contract_json_paths: list[Path]) -> None:
    ts_path = REPO_ROOT / "packages" / "tool-types" / "src" / "version.ts"
    text = ts_path.read_text(encoding="utf-8")
    match = _TS_VERSION_PATTERN.search(text)
    assert match is not None, "TOOL_CONTRACT_VERSION literal missing in version.ts"
    ts_ver = match.group(1)
    expected = _version_from_json(contract_json_paths[0])
    assert ts_ver == expected
