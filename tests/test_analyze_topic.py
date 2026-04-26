"""Tests for analyze_development_topic tool and supporting utilities."""

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from data360.api import (
    _DecompositionResult,
    _SampledQueryGroup,
    _score_indicator,
    analyze_development_topic,
)
from data360.mcp_server.sampling import has_llm_credentials
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
    database_name: str = "World Development Indicators",
    definition: str = "GDP per capita is gross domestic product divided by mid-year population",
    covers_country: bool = True,
    latest_data: str = "2023",
) -> EnrichedIndicator:
    # covers_country is dict[str, bool] | None in the model.
    cc: dict[str, bool] | None = {"__": covers_country} if covers_country is not None else None
    return EnrichedIndicator(
        idno=idno,
        database_id=database_id,
        database_name=database_name,
        name=name,
        truncated_definition=definition[:100],
        covers_country=cc,
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
    """Simulates a structured sampling result (result_type path)."""

    result: Any
    text: str | None = None
    model: str = "fake-model"


class FakeSession:
    """Minimal session stub exposing check_client_capability."""

    def __init__(self, native_sampling: bool = True):
        self._native_sampling = native_sampling

    def check_client_capability(self, capability) -> bool:  # noqa: ANN001
        return self._native_sampling


class FakeContext:
    """Fake MCP Context that simulates ctx.sample() with structured output.

    Accepts a _DecompositionResult to return as result_type output,
    or raises on demand to test the fallback path.
    """

    def __init__(
        self,
        result: _DecompositionResult | None = None,
        should_raise: bool = False,
        native_sampling: bool = True,
    ):
        self._result = result
        self._should_raise = should_raise
        self.session = FakeSession(native_sampling=native_sampling)

    async def sample(self, messages, **kwargs) -> FakeSamplingResult:
        if self._should_raise:
            raise ValueError("Client does not support sampling")
        return FakeSamplingResult(result=self._result)


# --- Unit tests for _score_indicator ---


class TestScoreIndicator:
    """Tests for indicator scoring."""

    def test_country_coverage_bonus(self):
        ind_covered = _make_indicator(covers_country=True)
        ind_uncovered = _make_indicator(covers_country=False)
        score_covered = _score_indicator(ind_covered, set())
        score_uncovered = _score_indicator(ind_uncovered, set())
        assert score_covered > score_uncovered

    def test_recency_bonus(self):
        ind_recent = _make_indicator(latest_data="2024", covers_country=False)
        ind_old = _make_indicator(latest_data="2010", covers_country=False)
        score_recent = _score_indicator(ind_recent, set())
        score_old = _score_indicator(ind_old, set())
        assert score_recent > score_old

    def test_token_overlap(self):
        ind = _make_indicator(
            name="GDP per capita",
            definition="Gross domestic product per person",
            covers_country=False,
        )
        score_match = _score_indicator(ind, {"gdp", "capita"})
        score_no_match = _score_indicator(ind, {"elephant", "banana"})
        assert score_match > score_no_match


# --- Tests for has_llm_credentials ---


class TestHasLlmCredentials:
    def test_returns_false_when_no_keys(self, monkeypatch):
        for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY",
                   "MISTRAL_API_KEY", "AWS_ACCESS_KEY_ID"):
            monkeypatch.delenv(k, raising=False)
        assert has_llm_credentials() is False

    def test_returns_true_with_openai_key(self, monkeypatch):
        monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
        assert has_llm_credentials() is True

    def test_returns_true_with_anthropic_key(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ant-test")
        assert has_llm_credentials() is True

    def test_returns_true_with_aws_key(self, monkeypatch):
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "AKIA123")
        assert has_llm_credentials() is True


# --- Integration tests for analyze_development_topic ---


class TestAnalyzeDevelopmentTopic:
    """Integration tests using mocked search/get_data."""

    @pytest.mark.asyncio
    async def test_no_context_proceeds_with_raw_query(self):
        """Without ctx, proceeds with raw query."""
        indicators = [_make_indicator()]
        mock_search_response = _make_search_response(indicators)

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.metadata = {}
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(query="What are Ghana's economic challenges?")

        assert result["decomposition_method"] == "none"
        assert len(result["sub_queries"]) >= 1
        assert len(result["selected_indicators"]) == 1

    @pytest.mark.asyncio
    async def test_sampling_flat_result_uses_sampling_tier(self):
        """Sampling returns flat sub_queries -> uses sampling_client tier."""
        indicators = [_make_indicator()]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(
            result=_DecompositionResult(
                sub_queries=["GDP per capita", "inflation rate", "unemployment"],
            )
        )

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.metadata = {}
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(
                query="How is Ghana performing economically?",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "sampling_client"
        assert "GDP per capita" in result["sub_queries"]

    @pytest.mark.asyncio
    async def test_sampling_grouped_result_uses_query_groups(self):
        """Sampling returns grouped structure -> query_groups route."""
        indicators = [_make_indicator(idno="WB_WDI_1", name="Indicator 1")]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(
            result=_DecompositionResult(
                query_groups=[
                    _SampledQueryGroup(queries=["unemployment rate"], country="Morocco"),
                    _SampledQueryGroup(queries=["manufacturing output"], country="Ethiopia"),
                ]
            )
        )

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)) as mock_search,
            patch("data360.api._resolve_country_code", return_value="MAR,ETH"),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(
                query="Labor market Morocco vs manufacturing Ethiopia",
                country="Morocco, Ethiopia",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "sampling_client"
        assert result["country_code"] == "MAR,ETH"

        call_kwargs = mock_search.call_args.kwargs
        assert "query_groups" in call_kwargs
        groups = call_kwargs["query_groups"]
        assert len(groups) == 2
        assert groups[0].country == "Morocco"
        assert groups[0].queries == ["unemployment rate"]
        assert groups[1].country == "Ethiopia"
        assert groups[1].queries == ["manufacturing output"]

    @pytest.mark.asyncio
    async def test_sampling_failure_proceeds_with_raw_query(self):
        """When ctx.sample() raises, proceeds with raw query without propagating error."""
        indicators = [_make_indicator()]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(should_raise=True)

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.metadata = {}
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(
                query="economic growth and trade",
                ctx=ctx,
            )

        # Must not raise; must fall back gracefully
        assert result["decomposition_method"] == "none"
        assert len(result["sub_queries"]) >= 1

    @pytest.mark.asyncio
    async def test_sampling_empty_result_proceeds_with_raw_query(self):
        """When sampling returns empty DecompositionResult, proceeds with raw query."""
        indicators = [_make_indicator()]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(result=_DecompositionResult(sub_queries=None, query_groups=None))

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.metadata = {}
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(
                query="inflation and unemployment",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "none"
        assert len(result["sub_queries"]) >= 1

    @pytest.mark.asyncio
    async def test_database_name_present_in_response(self):
        """database_name field must be present in each selected_indicator."""
        indicators = [_make_indicator(database_name="World Development Indicators")]
        mock_search_response = _make_search_response(indicators)

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.metadata = {}
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(query="GDP growth")

        assert len(result["selected_indicators"]) == 1
        ind = result["selected_indicators"][0]
        assert "database_name" in ind
        assert ind["database_name"] == "World Development Indicators"

    @pytest.mark.asyncio
    async def test_per_indicator_country_scope_for_prefetch(self):
        """Prefetch uses per-indicator requested_country when available."""
        ind = _make_indicator()
        ind.requested_country = "KEN"  # set per-indicator scope
        mock_search_response = _make_search_response([ind])

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.metadata = {}
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data) as mock_get_data,
        ):
            await analyze_development_topic(
                query="Kenya economy",
                country="KEN",
            )

        # Verify REF_AREA was set to the per-indicator scope
        call_kwargs = mock_get_data.call_args.kwargs
        assert call_kwargs.get("disaggregation_filters", {}).get("REF_AREA") == "KEN"

    @pytest.mark.asyncio
    async def test_no_indicators_found_returns_error(self):
        """Returns error dict when no indicators are found."""
        mock_search_response = _make_search_response(indicators=[])

        with patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)):
            result = await analyze_development_topic(query="very obscure topic xyz123")

        assert "error" in result
        assert result["selected_indicators"] == []

    @pytest.mark.asyncio
    async def test_data_fetch_error_does_not_crash(self):
        """Data fetch failure results in data_error field, not exception."""
        indicators = [_make_indicator()]
        mock_search_response = _make_search_response(indicators)

        mock_data = AsyncMock()
        mock_data.return_value.data = None
        mock_data.return_value.error = "HTTP error 500"
        mock_data.return_value.metadata = None
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(query="GDP growth")

        assert len(result["selected_indicators"]) == 1
        assert result["selected_indicators"][0]["data_error"] is not None
        assert result["selected_indicators"][0]["data_snapshot"] is None

    @pytest.mark.asyncio
    async def test_max_indicators_capped_at_six(self):
        """max_indicators is respected and capped at 6."""
        indicators = [
            _make_indicator(idno=f"WB_WDI_IND_{i}", name=f"Indicator {i}")
            for i in range(10)
        ]
        mock_search_response = _make_search_response(indicators)

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.metadata = {}
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(
                query="everything about development",
                max_indicators=2,
            )

        assert len(result["selected_indicators"]) == 2

    @pytest.mark.asyncio
    async def test_multi_country_fallback_uses_cross_product(self):
        """No sampling with multi-country falls back to cross-product search."""
        indicators = [_make_indicator(idno="WB_WDI_1", name="Indicator 1")]
        mock_search_response = _make_search_response(indicators)

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)) as mock_search,
            patch("data360.api._resolve_country_code", return_value="MAR,ETH"),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(
                query="labor market and manufacturing",
                country="Morocco, Ethiopia",
            )

        assert result["decomposition_method"] == "none"
        assert result["country_code"] == "MAR,ETH"

        call_kwargs = mock_search.call_args.kwargs
        assert "query_groups" in call_kwargs
        groups = call_kwargs["query_groups"]
        assert len(groups) == 2
        assert groups[0].country == "MAR"
        assert groups[1].country == "ETH"
        # Both groups should have the same sub_queries (cross product)
        assert groups[0].queries == groups[1].queries

    @pytest.mark.asyncio
    async def test_single_country_uses_queries_param(self):
        """Single country uses queries= + required_country= (not query_groups)."""
        indicators = [_make_indicator(idno="WB_WDI_1", name="Indicator 1")]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(
            result=_DecompositionResult(sub_queries=["GDP per capita", "inflation"])
        )

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)) as mock_search,
            patch("data360.api._resolve_country_code", return_value="GHA"),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(
                query="Ghana economic status",
                country="Ghana",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "sampling_client"

        call_kwargs = mock_search.call_args.kwargs
        assert "queries" in call_kwargs
        assert call_kwargs["required_country"] == "GHA"
        assert "query_groups" not in call_kwargs

    @pytest.mark.asyncio
    async def test_non_client_sampling_uses_server_tier(self):
        """When client does not advertise native sampling, tier is sampling_server."""
        indicators = [_make_indicator()]
        mock_search_response = _make_search_response(indicators)

        ctx = FakeContext(
            result=_DecompositionResult(sub_queries=["trade", "GDP"]),
            native_sampling=False,  # client does NOT support native sampling
        )

        mock_data = AsyncMock()
        mock_data.return_value.data = []
        mock_data.return_value.error = None
        mock_data.return_value.metadata = {}
        mock_data.return_value.count = 0

        with (
            patch("data360.api.search", new=AsyncMock(return_value=mock_search_response)),
            patch("data360.api.get_data", mock_data),
        ):
            result = await analyze_development_topic(
                query="trade and GDP",
                ctx=ctx,
            )

        assert result["decomposition_method"] == "sampling_server"
