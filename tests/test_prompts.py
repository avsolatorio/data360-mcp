"""Prompt text regression tests."""

import re
from pathlib import Path

from data360 import __file__ as data360_init_file

PROMPTS_PATH = Path(data360_init_file).resolve().parent / "mcp_server" / "prompts.py"


def _prompt_source() -> str:
    return PROMPTS_PATH.read_text(encoding="utf-8")


def test_system_prompt_defaults_match_last_five_year_window():
    source = _prompt_source()
    assert "last 5 years" in source
    assert "last 20 years" not in source


def test_indicator_search_prompt_does_not_use_removed_select_fields_arg():
    source = _prompt_source()
    match = re.search(
        r"def indicator_search\(.*?@mcp\.prompt\(\)",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    assert "select_fields=" not in match.group(0)


def test_country_data_prompt_does_not_use_removed_select_fields_arg():
    source = _prompt_source()
    match = re.search(
        r"def country_data\(.*?$",
        source,
        flags=re.DOTALL,
    )
    assert match is not None
    block = match.group(0)
    assert "select_fields=" not in block
    assert "Defaults to last 5 years" in block
