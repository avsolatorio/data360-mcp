from __future__ import annotations

import pytest

from data360_mcp_agent import k360_graph


class _FakeGraph:
    def __init__(self, payload):
        self._payload = payload

    async def ainvoke(self, _state):
        return self._payload


@pytest.mark.asyncio
async def test_run_k360_query_returns_empty_payload_when_gate_not_relevant(monkeypatch):
    async def _fake_create(*_args, **_kwargs):
        return _FakeGraph(
            {
                "gate": {"relevant": False, "reason": "not in scope"},
                "rewrite": {"data_question": "unused"},
                "tool_calls": [{"tool_name": "data360_get_data"}],
                "content_packet": {"query_focus": "unused"},
                "narrative": "unused",
                "error": None,
            }
        )

    monkeypatch.setattr(k360_graph, "create_k360_graph", _fake_create)

    out = await k360_graph.run_k360_query("hello")
    assert out["gate"]["relevant"] is False
    assert out["tool_calls"] == []
    assert out["content_packet"] == {}
    assert out["narrative"] == ""


@pytest.mark.asyncio
async def test_run_k360_query_returns_full_envelope_for_relevant(monkeypatch):
    fake_result = {
        "gate": {"relevant": True, "confidence": 0.9},
        "rewrite": {"data_question": "GDP per capita Kenya latest", "search_hints": ["GDP per capita"]},
        "tool_calls": [
            {
                "tool_name": "data360_get_viz_spec",
                "tool_args": {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD"},
                "tool_result": {"url": "http://127.0.0.1:8000/static/viz_specs/demo_vega.json"},
            }
        ],
        "content_packet": {"query_focus": "GDP per capita Kenya latest"},
        "narrative": "**Data:** Latest GDP per capita is available.",
        "error": None,
    }

    async def _fake_create(*_args, **_kwargs):
        return _FakeGraph(fake_result)

    monkeypatch.setattr(k360_graph, "create_k360_graph", _fake_create)

    out = await k360_graph.run_k360_query("Latest GDP per capita in Kenya")
    assert out["gate"]["relevant"] is True
    assert out["rewrite"]["data_question"] == "GDP per capita Kenya latest"
    assert out["tool_calls"][0]["tool_name"] == "data360_get_viz_spec"
    assert out["content_packet"]["query_focus"] == "GDP per capita Kenya latest"
    assert out["narrative"].startswith("**Data:**")
