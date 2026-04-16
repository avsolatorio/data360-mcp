"""Tests for generate_viz_gallery and matched_sub_queries enrichment."""

from itertools import combinations
from unittest.mock import AsyncMock, patch

import pytest

from data360.visualization import generate_viz_gallery


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_indicator(
    indicator_id: str = "WB_WDI_NY_GDP_PCAP_KD",
    database_id: str = "WB_WDI",
    name: str = "GDP per capita",
) -> dict:
    return {
        "indicator_id": indicator_id,
        "database_id": database_id,
        "name": name,
    }


def _ok_result(url: str = "http://localhost/chart.json", strategy: str = "line") -> dict:
    return {"url": url, "error": None, "strategy": strategy}


def _err_result(msg: str = "No data") -> dict:
    return {"url": None, "error": msg}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestGenerateVizGallery:
    @pytest.mark.asyncio
    async def test_empty_indicators_returns_error(self):
        result = await generate_viz_gallery(indicators=[])
        assert result["total_charts"] == 0
        assert result["error"] is not None

    @pytest.mark.asyncio
    async def test_single_indicator_generates_one_chart(self):
        inds = [_make_indicator()]
        with (
            patch(
                "data360.visualization.get_viz_spec",
                new=AsyncMock(return_value=_ok_result()),
            ),
            patch(
                "data360.visualization.get_multi_indicator_viz_spec",
                new=AsyncMock(return_value=_ok_result()),
            ),
        ):
            result = await generate_viz_gallery(indicators=inds)

        # 1 single, 0 pairs
        assert result["total_charts"] == 1
        assert result["successful_charts"] == 1
        assert result["failed_charts"] == 0
        assert len(result["gallery"]) == 1
        assert result["gallery"][0]["chart_url"] is not None

    @pytest.mark.asyncio
    async def test_two_indicators_generates_three_charts(self):
        inds = [_make_indicator("IND_A", name="Indicator A"), _make_indicator("IND_B", name="Indicator B")]
        with (
            patch(
                "data360.visualization.get_viz_spec",
                new=AsyncMock(return_value=_ok_result()),
            ),
            patch(
                "data360.visualization.get_multi_indicator_viz_spec",
                new=AsyncMock(return_value=_ok_result(strategy="scatter")),
            ),
        ):
            result = await generate_viz_gallery(indicators=inds)

        # 2 singles + 1 pair = 3
        assert result["total_charts"] == 3
        assert result["successful_charts"] == 3
        pair_entries = [c for c in result["gallery"] if len(c["indicators"]) == 2]
        assert len(pair_entries) == 1
        assert pair_entries[0]["chart_type"] == "scatter"

    @pytest.mark.asyncio
    async def test_four_indicators_generates_ten_charts(self):
        n = 4
        inds = [_make_indicator(f"IND_{i}", name=f"Indicator {i}") for i in range(n)]

        with (
            patch(
                "data360.visualization.get_viz_spec",
                new=AsyncMock(return_value=_ok_result()),
            ),
            patch(
                "data360.visualization.get_multi_indicator_viz_spec",
                new=AsyncMock(return_value=_ok_result(strategy="layered_lines")),
            ),
        ):
            result = await generate_viz_gallery(indicators=inds)

        # n singles + C(n,2) pairs = 4 + 6 = 10
        expected = n + len(list(combinations(range(n), 2)))
        assert result["total_charts"] == expected
        assert len(result["gallery"]) == expected

    @pytest.mark.asyncio
    async def test_six_indicators_generates_twenty_one_charts(self):
        n = 6
        inds = [_make_indicator(f"IND_{i}", name=f"Indicator {i}") for i in range(n)]

        with (
            patch(
                "data360.visualization.get_viz_spec",
                new=AsyncMock(return_value=_ok_result()),
            ),
            patch(
                "data360.visualization.get_multi_indicator_viz_spec",
                new=AsyncMock(return_value=_ok_result(strategy="scatter")),
            ),
        ):
            result = await generate_viz_gallery(indicators=inds)

        # 6 singles + C(6,2)=15 pairs = 21
        assert result["total_charts"] == 21

    @pytest.mark.asyncio
    async def test_indicators_capped_at_six(self):
        inds = [_make_indicator(f"IND_{i}", name=f"Indicator {i}") for i in range(9)]

        with (
            patch(
                "data360.visualization.get_viz_spec",
                new=AsyncMock(return_value=_ok_result()),
            ),
            patch(
                "data360.visualization.get_multi_indicator_viz_spec",
                new=AsyncMock(return_value=_ok_result()),
            ),
        ):
            result = await generate_viz_gallery(indicators=inds)

        # Capped to 6: 6 + 15 = 21
        assert result["total_charts"] == 21

    @pytest.mark.asyncio
    async def test_failed_single_does_not_crash_gallery(self):
        inds = [
            _make_indicator("IND_A", name="Indicator A"),
            _make_indicator("IND_B", name="Indicator B"),
        ]

        async def _side_effect_single(*, indicator_id, **kwargs):
            if indicator_id == "IND_A":
                return _err_result("API error for IND_A")
            return _ok_result()

        with (
            patch(
                "data360.visualization.get_viz_spec",
                new=AsyncMock(side_effect=_side_effect_single),
            ),
            patch(
                "data360.visualization.get_multi_indicator_viz_spec",
                new=AsyncMock(return_value=_ok_result()),
            ),
        ):
            result = await generate_viz_gallery(indicators=inds)

        # 2 singles + 1 pair = 3; IND_A single fails, others succeed
        assert result["total_charts"] == 3
        assert result["failed_charts"] == 1
        assert result["successful_charts"] == 2
        failed_entries = [c for c in result["gallery"] if c.get("error")]
        assert len(failed_entries) == 1
        assert "IND_A" in failed_entries[0]["error"] or "Indicator A" in failed_entries[0]["indicators"]

    @pytest.mark.asyncio
    async def test_failed_pair_does_not_crash_gallery(self):
        inds = [
            _make_indicator("IND_A", name="A"),
            _make_indicator("IND_B", name="B"),
        ]

        with (
            patch(
                "data360.visualization.get_viz_spec",
                new=AsyncMock(return_value=_ok_result()),
            ),
            patch(
                "data360.visualization.get_multi_indicator_viz_spec",
                new=AsyncMock(return_value=_err_result("No overlapping data")),
            ),
        ):
            result = await generate_viz_gallery(indicators=inds)

        # pair fails (error in result), singles succeed
        assert result["total_charts"] == 3
        pair_entries = [c for c in result["gallery"] if len(c["indicators"]) == 2]
        assert pair_entries[0].get("error") == "No overlapping data"

    @pytest.mark.asyncio
    async def test_country_code_passed_to_charts(self):
        inds = [_make_indicator()]
        mock_single = AsyncMock(return_value=_ok_result())

        with patch("data360.visualization.get_viz_spec", new=mock_single):
            await generate_viz_gallery(indicators=inds, country_code="GHA")

        mock_single.assert_awaited_once()
        call_kwargs = mock_single.call_args.kwargs
        assert call_kwargs.get("country_code") == "GHA"

    @pytest.mark.asyncio
    async def test_description_includes_country(self):
        inds = [_make_indicator(name="GDP per capita")]

        with patch(
            "data360.visualization.get_viz_spec",
            new=AsyncMock(return_value=_ok_result()),
        ):
            result = await generate_viz_gallery(indicators=inds, country_code="GHA")

        desc = result["gallery"][0]["description"]
        assert "GHA" in desc
        assert "GDP per capita" in desc

    @pytest.mark.asyncio
    async def test_chart_types_filter_passed_to_single(self):
        inds = [_make_indicator()]
        mock_single = AsyncMock(return_value=_ok_result())

        with patch("data360.visualization.get_viz_spec", new=mock_single):
            await generate_viz_gallery(indicators=inds, chart_types=["bar"])

        call_kwargs = mock_single.call_args.kwargs
        assert call_kwargs.get("chart_type") == "bar"
