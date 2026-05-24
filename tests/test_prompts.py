"""Prompt text regression tests."""

from pathlib import Path

PROMPTS_PATH = Path(__file__).resolve().parents[1] / "src" / "data360" / "mcp_server" / "prompts.py"


def _prompt_source() -> str:
    return PROMPTS_PATH.read_text(encoding="utf-8")


def test_system_prompt_defaults_match_last_five_year_window():
    source = _prompt_source()
    assert "last 5 years" in source
    assert "last 20 years" not in source


def test_indicator_search_prompt_does_not_use_removed_select_fields_arg():
    source = _prompt_source()
    assert "def indicator_search(" in source
    assert 'data360_search_indicators(\n       query="{query}",\n       limit=5,\n       select_fields=' not in source


def test_country_data_prompt_does_not_use_removed_select_fields_arg():
    source = _prompt_source()
    assert "def country_data(" in source
    assert 'data360_search_indicators(\n    query="{query}",\n    limit=5,\n    required_country="{country}", # Pass the list string as-is\n    select_fields=' not in source
    assert "Defaults to last 5 years" in source
