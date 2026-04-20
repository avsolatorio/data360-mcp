"""Tests for analyze_development_topic tool."""

import json
from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from data360.api import (
    _decompose_query,
    _score_indicator,
    analyze_development_topic,
)
from data360.models import (
    EnrichedIndicator,
    MultiQuerySearchResponse,
    QueryGroupResult,
)


# --- Helpers ---


def _make_indicator(
    idno: str = "WB_WDI_NY_GDP_PCAP_KD",
    name: str = "GDP per capita (constant 2015 US$)",
    database_id: str = "WB_WDI",
    definition: str = "GDP per capita is gross domestic product divided by mid-year population",
    covers_country: bool = True,
    latest_data: str = "2023",
) -> EnrichedIndicator:
    return EnrichedIndicator(
        idno=idno,
        database_id=database_id,
        name=name,
        truncated_definition=definition[:100],
        covers_country=covers_country,
        latest_data=latest_data,
    )


def _make_search_response(
    indicators: list[EnrichedIndicator] | None = None,
    error: str | None = None,
    query: str = "test query",
) -> MultiQuerySearchResponse:
    """Build a MultiQuerySearchResponse with by_query layout for mocking search()."""
    inds = indicators or []
    group = QueryGroupResult(query=query, indicators=inds, count=len(inds), error=error)
    return MultiQuerySearchResponse(
        results=[group],
        result_layout="by_query",
        queries=[query],
        total_candidates=len(inds),
        error=None if inds else error,
    )


@dataclass
class FakeSamplingResult:
    text: str | None
    model: str = "fake-model"


class FakeSession:
    """Minimal session stub exposing check_client_capability."""

    def __init__(self, native_sampling: bool = True):
        self._native_sampling = native_sampling

    def check_client_capability(self, capability) -> bool:  # noqa: ANN001
        return self._native_sampling


class FakeContext:
    """Fake MCP Context that simulates sampling."""

    def __init__(
        self,
        response_text: str | None = None,
        should_raise: bool = False,
        native_sampling: bool = True,
    ):
        self._response_text = response_text
        self._should_raise = should_raise
        self.session = FakeSession(native_sampling=native_sampling)

    async def sample(self, messages, **kwargs) -> FakeSamplingResult:
        if self._should_raise:
            raise ValueError("Client does not support sampling")
        return FakeSamplingResult(text=self._response_text)


# --- Unit tests for _decompose_query ---


class TestDecomposeQuery:
    """Tests for rule-based query decomposition."""

    def test_splits_on_and(self):
        result = _decompose_query("economic growth and public spending")
        assert len(result) == 2
        assert any("economic" in sq.lower() or "growth" in sq.lower() for sq in result)
        assert any("public" in sq.lower() or "spending" in sq.lower() for sq in result)

    def test_splits_on_comma(self):
        result = _decompose_query("GDP, poverty, education")
        assert len(result) == 3

    def test_splits_on_semicolon(self):
        result = _decompose_query("health outcomes; education access")
        assert len(result) == 2

    def test_removes_stopwords(self):
        result = _decompose_query("What are the main challenges facing economic growth")
        # Should have cleaned fragments, not contain stopwords as standalone terms
        for sq in result:
            words = sq.lower().split()
            # At least the meaningful words should remain
            assert not all(w in {"what", "are", "the", "main"} for w in words)

    def test_falls_back_to_original_on_single_topic(self):
        result = _decompose_query("GDP per capita")
        assert len(result) == 1
        assert "GDP" in result[0]

    def test_handles_empty_fragments(self):
        result = _decompose_query("and or and")
        # All fragments are stopwords, should fall back to original
        assert len(result) >= 1

    def test_deduplicates(self):
        result = _decompose_query("growth and growth and growth")
        # All fragments are the same word, should deduplicate to 1
        assert len(result) == 1

    def test_caps_at_five(self):
        result = _decompose_query("a, b, c, d, e, f, g, h")
        assert len(result) <= 5


# --- Unit tests for _score_indicator ---


class TestScoreIndicator:
    """Tests for indicator scoring function."""

    def test_country_coverage_bonus(self):
        ind_covered = _make_indicator(covers_country=True)
        ind_not_covered = _make_indicator(covers_country=False)
        tokens = {"gdp", "growth"}

        score_covered = _score_indicator(ind_covered, tokens)
        score_not = _score_indicator(ind_not_covered, tokens)

        assert score_covered > score_not

    def test_recency_bonus(self):
        ind_recent = _make_indicator(latest_data="2025")
        ind_old = _make_indicator(latest_data="2005")
        tokens = {"gdp"}

        score_recent = _score_indicator(ind_recent, tokens)
        score_old = _score_indicator(ind_old, tokens)

        assert score_recent > score_old

    def test_token_overlap(self):
        ind = _make_indicator(
            name="GDP per capita growth",
            definition="Economic growth rate",
        )
        high_overlap_tokens = {"gdp", "growth", "economic"}
        no_overlap_tokens = {"education", "literacy", "enrollment"}

        score_high = _score_indicator(ind, high_overlap_tokens)
        score_none = _score_indicator(ind, no_overlap_tokens)

        assert score_high > score_none


# --- Integration tests for analyze_development_topic ---


class TestAnalyzeDevelopmentTopic:
    """Tests for the main analyze_development_topic function."""

    @pytest.mark.asyncio
    async def test_happy_path_with_sampling(self):
        """Sampling succeeds and returns LLM-generated sub-queries."""
        indicators = [
            _make_indicator(
                idno="WB_WDI_NY_GDP_PCAP_KD",
                name="GDP per capita",
            ),
            _make_indicator(
                idno="WB_WDI_SP_DYN_LE00_IN",
                name="Life expectancy at birth",
            ),
        ]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(
            response_text=json.dumps(["GDP per capita", "life expectancy"])
        )

        mock_data_response = AsyncMock()
        mock_data_response.return_value.data = [
            {"OBS_VALUE": 1500, "TIME_PERIOD": "2023", "REF_AREA": "GHA"}
        ]
        mock_data_response.return_value.error = None
        mock_data_response.return_value.metadata = {"name": "GDP per capita"}
        mock_data_response.return_value.count = 1

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)) as mock_search,
            patch("data360.api.get_data", mock_data_response),
            patch("data360.api._resolve_country_code", return_value="GHA"),
        ):
            result = await analyze_development_topic(
                query="What makes a country great?",
                country="Ghana",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "sampling_client"
        assert len(result["sub_queries"]) == 2
        assert result["country_code"] == "GHA"
        assert len(result["selected_indicators"]) > 0
        assert "error" not in result or result.get("error") is None

    @pytest.mark.asyncio
    async def test_sampling_fallback(self):
        """When sampling raises, falls back to rule-based decomposition."""
        indicators = [
            _make_indicator(
                idno="WB_WDI_NY_GDP_PCAP_KD",
                name="GDP per capita",
            ),
        ]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(should_raise=True)

        mock_data_response = AsyncMock()
        mock_data_response.return_value.data = []
        mock_data_response.return_value.error = None
        mock_data_response.return_value.metadata = {}
        mock_data_response.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data_response),
        ):
            result = await analyze_development_topic(
                query="economic growth and public spending",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "rule_based"
        assert len(result["sub_queries"]) >= 2
        # Should not crash — graceful fallback
        assert "error" not in result or result.get("error") is None

    @pytest.mark.asyncio
    async def test_no_ctx_uses_rule_based(self):
        """When ctx is None (no MCP context), uses rule-based decomposition."""
        indicators = [
            _make_indicator(idno="WB_WDI_NY_GDP_PCAP_KD", name="GDP per capita"),
        ]
        mock_search_response = _make_search_response(indicators)

        mock_data_response = AsyncMock()
        mock_data_response.return_value.data = []
        mock_data_response.return_value.error = None
        mock_data_response.return_value.metadata = {}
        mock_data_response.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data_response),
        ):
            result = await analyze_development_topic(
                query="economic growth and education",
                ctx=None,
            )

        assert result["decomposition_method"] == "rule_based"
        assert len(result["sub_queries"]) >= 2

    @pytest.mark.asyncio
    async def test_empty_search_results(self):
        """When all searches return no indicators, returns error."""
        empty_response = _make_search_response(indicators=[])

        with patch("data360.api.search", new=AsyncMock(return_value=empty_response)):
            result = await analyze_development_topic(
                query="nonexistent topic xyzzy",
            )

        assert result["selected_indicators"] == []
        assert result["error"] is not None
        assert "No matching" in result["error"]

    @pytest.mark.asyncio
    async def test_data_fetch_failure(self):
        """Data fetch failures are reported per-indicator, do not crash the tool."""
        indicators = [
            _make_indicator(idno="WB_WDI_NY_GDP_PCAP_KD", name="GDP per capita"),
        ]
        mock_search_response = _make_search_response(indicators)

        mock_data_response = AsyncMock()
        mock_data_response.return_value.data = None
        mock_data_response.return_value.error = "HTTP error 500: Internal Server Error"
        mock_data_response.return_value.metadata = None
        mock_data_response.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data_response),
        ):
            result = await analyze_development_topic(
                query="GDP growth",
            )

        # Should have an indicator entry but with data_error set
        assert len(result["selected_indicators"]) == 1
        assert result["selected_indicators"][0]["data_error"] is not None
        assert result["selected_indicators"][0]["data_snapshot"] is None

    @pytest.mark.asyncio
    async def test_max_indicators_capped(self):
        """max_indicators is respected and capped at 6."""
        indicators = [
            _make_indicator(idno=f"WB_WDI_IND_{i}", name=f"Indicator {i}")
            for i in range(10)
        ]
        mock_search_response = _make_search_response(indicators)

        mock_data_response = AsyncMock()
        mock_data_response.return_value.data = []
        mock_data_response.return_value.error = None
        mock_data_response.return_value.metadata = {}
        mock_data_response.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data_response),
        ):
            result = await analyze_development_topic(
                query="everything about development",
                max_indicators=2,
            )

        assert len(result["selected_indicators"]) == 2

    @pytest.mark.asyncio
    async def test_sampling_returns_invalid_json(self):
        """When sampling returns non-JSON, gracefully falls back to rule-based."""
        indicators = [
            _make_indicator(idno="WB_WDI_NY_GDP_PCAP_KD", name="GDP per capita"),
        ]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(response_text="This is not JSON at all")

        mock_data_response = AsyncMock()
        mock_data_response.return_value.data = []
        mock_data_response.return_value.error = None
        mock_data_response.return_value.metadata = {}
        mock_data_response.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data_response),
        ):
            result = await analyze_development_topic(
                query="economic growth and trade",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "rule_based"
        assert len(result["sub_queries"]) >= 2

    @pytest.mark.asyncio
    async def test_multi_country_sampling_returns_grouped(self):
        """Sampling returns grouped structure for multi-country question."""
        indicators = [
            _make_indicator(idno="WB_WDI_1", name="Indicator 1")
        ]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(
            response_text=json.dumps([
                {"queries": ["unemployment"], "country": "Morocco"},
                {"queries": ["manufacturing"], "country": "Ethiopia"}
            ])
        )
        mock_data_response = AsyncMock()
        mock_data_response.return_value.data = []
        mock_data_response.return_value.error = None
        mock_data_response.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)) as mock_search,
            patch("data360.api._resolve_country_code", return_value="MAR,ETH"),
            patch("data360.api.get_data", mock_data_response),
        ):
            result = await analyze_development_topic(
                query="Labor market Morocco vs manufacturing Ethiopia",
                country="Morocco, Ethiopia",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "sampling_client"
        assert result["country_code"] == "MAR,ETH"

        # Verify search was called with query_groups properly scoped per country
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert "query_groups" in call_kwargs

        groups = call_kwargs["query_groups"]
        assert len(groups) == 2
        assert groups[0].country == "Morocco"
        assert groups[0].queries == ["unemployment"]
        assert groups[1].country == "Ethiopia"
        assert groups[1].queries == ["manufacturing"]

    @pytest.mark.asyncio
    async def test_multi_country_fallback_uses_cross_product(self):
        """No sampling or invalid sampling with multi-country falls back to cross-product search."""
        indicators = [
            _make_indicator(idno="WB_WDI_1", name="Indicator 1")
        ]
        mock_search_response = _make_search_response(indicators)

        mock_data_response = AsyncMock()
        mock_data_response.return_value.data = []
        mock_data_response.return_value.error = None
        mock_data_response.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)) as mock_search,
            patch("data360.api._resolve_country_code", return_value="MAR,ETH"),
            patch("data360.api.get_data", mock_data_response),
        ):
            result = await analyze_development_topic(
                # Use query that rule_based will split cleanly
                query="labor market and manufacturing",
                country="Morocco, Ethiopia",
            )

        assert result["decomposition_method"] == "rule_based"
        assert result["country_code"] == "MAR,ETH"

        # Verify search was called with query_groups configured for cross product
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert "query_groups" in call_kwargs

        groups = call_kwargs["query_groups"]
        assert len(groups) == 2
        # MAR and ETH each get the SAME sub_queries (cross product)
        assert groups[0].country == "MAR"
        assert len(groups[0].queries) >= 2
        assert groups[1].country == "ETH"
        assert len(groups[1].queries) >= 2
        assert groups[0].queries == groups[1].queries

    @pytest.mark.asyncio
    async def test_single_country_preserves_existing_behavior(self):
        """Single country should still use `queries` param instead of `query_groups`."""
        indicators = [
            _make_indicator(idno="WB_WDI_1", name="Indicator 1")
        ]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(
            response_text=json.dumps(["GDP per capita", "inflation"])
        )

        mock_data_response = AsyncMock()
        mock_data_response.return_value.data = []
        mock_data_response.return_value.error = None
        mock_data_response.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)) as mock_search,
            patch("data360.api._resolve_country_code", return_value="GHA"),
            patch("data360.api.get_data", mock_data_response),
        ):
            result = await analyze_development_topic(
                query="Ghana economic status",
                country="Ghana",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "sampling_client"

        # Verify search was called with queries and required_country
        mock_search.assert_called_once()
        call_kwargs = mock_search.call_args.kwargs
        assert "queries" in call_kwargs
        assert call_kwargs["required_country"] == "GHA"
        assert "query_groups" not in call_kwargs
