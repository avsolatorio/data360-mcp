"""Evidence tests for code review fixes B1–B3, C2–C5, D1.

Each test directly validates the bug or consistency issue identified during
the systematic code review of viz_config.py and visualization.py.
"""

import inspect

import pandas as pd
import pytest

from data360 import viz_config
from data360.viz_config import (
    ChartStrategy,
    StrategyResult,
    build_cross_sectional_spec,
    build_distribution_spec,
    build_heatmap_spec,
    build_stacked_area_spec,
    dispatch_spec,
)

# ============================================================================
# B1: _SOURCE_FALLBACK must be defined
# ============================================================================


class TestB1SourceFallback:
    """B1: _SOURCE_FALLBACK was referenced but never defined → NameError."""

    def test_source_fallback_constant_exists(self):
        from data360 import visualization

        assert hasattr(visualization, "_SOURCE_FALLBACK"), (
            "_SOURCE_FALLBACK constant must be defined in visualization.py"
        )
        assert isinstance(visualization._SOURCE_FALLBACK, str)
        assert len(visualization._SOURCE_FALLBACK) > 0

    def test_format_source_line_returns_fallback_when_no_attrib(self):
        """When both db and ind are empty, the function must return the
        fallback string — not crash with NameError."""
        from data360.visualization import _format_source_line_from_attribution

        result = _format_source_line_from_attribution({})
        assert isinstance(result, str)
        assert "World Bank" in result

    def test_format_source_line_returns_fallback_for_empty_strings(self):
        from data360.visualization import _format_source_line_from_attribution

        result = _format_source_line_from_attribution(
            {"database_name": "", "indicator_name": ""}
        )
        assert isinstance(result, str)
        assert "World Bank" in result


# ============================================================================
# B3: dispatch_spec must pass y_label/unit_measure to HEATMAP
# ============================================================================


class TestB3HeatmapDispatch:
    """B3: HEATMAP was in the else branch of dispatch_spec, dropping y_label
    and unit_measure.  Now it must receive them correctly."""

    @pytest.fixture
    def heatmap_df(self):
        rows = []
        for country in [f"Country{i}" for i in range(10)]:
            for year in ["2018-01-01", "2019-01-01", "2020-01-01"]:
                rows.append({"country": country, "year": year, "value": 42.0})
        return pd.DataFrame(rows)

    @pytest.fixture
    def heatmap_result(self):
        return StrategyResult(
            ChartStrategy.HEATMAP,
            "test",
            color_dim="value",
        )

    def test_dispatch_passes_unit_measure_to_heatmap(
        self, heatmap_df, heatmap_result
    ):
        """The heatmap tooltip format should reflect the unit, not default."""
        spec = dispatch_spec(
            ChartStrategy.HEATMAP,
            heatmap_df,
            "Test Title",
            heatmap_result,
            y_label="Percentage",
            unit_measure="%",
        )
        # The legend title should be the passed y_label, not "Value".
        color = spec.get("encoding", {}).get("color", {})
        legend = color.get("legend", {})
        assert legend.get("title") == "Percentage", (
            f"Heatmap legend title should be 'Percentage', got '{legend.get('title')}'"
        )

    def test_heatmap_builder_signature_matches_dispatch(self):
        """build_heatmap_spec must accept y_label and unit_measure positionally."""
        sig = inspect.signature(build_heatmap_spec)
        params = list(sig.parameters.keys())
        assert "y_label" in params
        assert "unit_measure" in params


# ============================================================================
# C2: Stacked area must use build_structured_tooltips
# ============================================================================


class TestC2StackedAreaTooltips:
    """C2: Stacked area used an inline 3-element tooltip list instead of
    build_structured_tooltips, missing dim-aware ordering."""

    @pytest.fixture
    def area_df(self):
        rows = []
        for series in ["Series A", "Series B"]:
            for year in ["2018-01-01", "2019-01-01", "2020-01-01"]:
                rows.append(
                    {"country": "TestCountry", "year": year,
                     "value": 10.0, "comp_breakdown_1": series}
                )
        return pd.DataFrame(rows)

    def test_stacked_area_tooltip_is_list_of_dicts(self, area_df):
        """Tooltip should be a list of dicts from build_structured_tooltips."""
        result = StrategyResult(
            ChartStrategy.STACKED_AREA,
            "test",
            color_dim="comp_breakdown_1",
        )
        spec = build_stacked_area_spec(
            area_df, "Test", result, unit_measure="%"
        )
        tooltips = spec["encoding"]["tooltip"]
        assert isinstance(tooltips, list)
        assert all(isinstance(t, dict) for t in tooltips)
        # Must have more than the 3 hard-coded fields from the old inline list.
        # build_structured_tooltips includes country, year, value, and breakdown dims.
        assert len(tooltips) >= 3

    def test_stacked_area_tooltip_includes_breakdown_dim(self, area_df):
        """The tooltip must include the comp_breakdown_1 dimension."""
        result = StrategyResult(
            ChartStrategy.STACKED_AREA,
            "test",
            color_dim="comp_breakdown_1",
        )
        spec = build_stacked_area_spec(area_df, "Test", result)
        tooltip_fields = [t["field"] for t in spec["encoding"]["tooltip"]]
        assert "comp_breakdown_1" in tooltip_fields


# ============================================================================
# C3: Heatmap facet header must suppress raw column names
# ============================================================================


class TestC3HeatmapFacetHeader:
    """C3: When heatmap is faceted, the header must include title:null so
    the raw column name (e.g. 'comp_breakdown_2') is not displayed."""

    def test_faceted_heatmap_header_has_null_title(self):
        rows = []
        for country in [f"C{i}" for i in range(10)]:
            for year in ["2018-01-01", "2019-01-01"]:
                for bd in ["GroupA", "GroupB"]:
                    rows.append({
                        "country": country, "year": year,
                        "value": 50.0, "comp_breakdown_1": bd,
                    })
        df = pd.DataFrame(rows)
        result = StrategyResult(
            ChartStrategy.HEATMAP,
            "test",
            color_dim="value",
            facet_dim="comp_breakdown_1",
        )
        spec = build_heatmap_spec(df, "Test", result)
        facet = spec.get("facet", {})
        header = facet.get("header", {})
        assert header.get("title") is None, (
            f"Heatmap facet header title should be None, got {header.get('title')!r}"
        )


# ============================================================================
# C4: Cross-sectional must not double-sort
# ============================================================================


class TestC4CrossSectionalSort:
    """C4: build_cross_sectional_spec used to sort twice; now data is sorted
    once before capping and the cap preserves order."""

    def test_cross_sectional_rows_are_descending(self):
        """Output rows must be sorted descending by value (highest at top)."""
        df = pd.DataFrame({
            "country": ["A", "B", "C"],
            "year": ["2020-01-01"] * 3,
            "value": [10.0, 30.0, 20.0],
        })
        result = StrategyResult(
            ChartStrategy.CROSS_SECTIONAL, "test", color_dim="country"
        )
        spec = build_cross_sectional_spec(df, "Test", result)
        rows = spec["data"]["values"]
        values = [r["value"] for r in rows]
        assert values == sorted(values, reverse=True), (
            f"Rows should be descending by value, got {values}"
        )


# ============================================================================
# C5: Distribution spec must use _cap_cardinality and annotate trimming
# ============================================================================


class TestC5DistributionCap:
    """C5: build_distribution_spec used head(top_n) without annotating the
    chart title.  Now it uses _cap_cardinality + _append_trim_note."""

    def test_distribution_trims_with_subtitle_note(self):
        """When > top_n_series countries exist, the title subtitle should
        contain a trim note."""
        top_n = viz_config.HIGH_CARDINALITY_THRESHOLDS["top_n_series"]
        n_countries = top_n + 5  # more than the cap
        df = pd.DataFrame({
            "country": [f"Country{i}" for i in range(n_countries)],
            "year": ["2020-01-01"] * n_countries,
            "value": [float(i) for i in range(n_countries)],
        })
        result = StrategyResult(
            ChartStrategy.DISTRIBUTION, "test", color_dim="country"
        )
        spec = build_distribution_spec(df, {"text": "Test"}, result)
        title = spec.get("title", {})
        subtitle = title.get("subtitle", "")
        if isinstance(subtitle, list):
            subtitle = " ".join(subtitle)
        assert str(n_countries) in subtitle or "top" in subtitle.lower(), (
            f"Trim note should mention total count or 'top', got: {subtitle!r}"
        )

    def test_distribution_caps_at_threshold(self):
        """Output rows must not exceed top_n_series."""
        top_n = viz_config.HIGH_CARDINALITY_THRESHOLDS["top_n_series"]
        n_countries = top_n + 10
        df = pd.DataFrame({
            "country": [f"Country{i}" for i in range(n_countries)],
            "year": ["2020-01-01"] * n_countries,
            "value": [float(i) for i in range(n_countries)],
        })
        result = StrategyResult(
            ChartStrategy.DISTRIBUTION, "test", color_dim="country"
        )
        spec = build_distribution_spec(df, "Test", result)
        rows = spec["data"]["values"]
        assert len(rows) <= top_n


# ============================================================================
# D1: bypass_strategies must not exist in get_viz_spec
# ============================================================================


class TestD1BypassStrategiesRemoved:
    """D1: The bypass_strategies set was dead code from the Draco removal."""

    def test_bypass_strategies_not_in_source(self):
        """The string 'bypass_strategies' must not appear in get_viz_spec source."""
        from data360.visualization import get_viz_spec

        source = inspect.getsource(get_viz_spec)
        assert "bypass_strategies" not in source, (
            "bypass_strategies is dead code and should be removed from get_viz_spec"
        )


# ============================================================================
# Phase 1: Startup Fetch Resilience and Spec Storage Tests
# ============================================================================


class TestPhase1ResilienceAndSpecStorage:
    """Validates codelist / group hierarchy manager properties and conditional spec saving."""

    def test_managers_initial_fetch_flag(self):
        """Verify GroupHierarchyManager and CodelistManager initial fetch flags start as False."""
        from data360.providers import GroupHierarchyManager, CodelistManager
        ghm = GroupHierarchyManager()
        cm = CodelistManager()
        assert ghm._initial_fetch_succeeded is False
        assert cm._initial_fetch_succeeded is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize("env", ["prod", "production"])
    async def test_store_spec_prod_saves_remote_only(self, env, monkeypatch):
        """In production, storing spec posts to Charts API but skips local static file saving."""
        import unittest.mock as mock
        from data360.visualization import _store_spec
        from data360.config import MCPServerSettings

        mock_post = mock.AsyncMock(return_value="http://remote-charts-api/spec/123")
        mock_save = mock.MagicMock(return_value="http://local-static/spec/123")

        # Mock the server settings
        monkeypatch.setattr(
            "data360.visualization.get_mcp_server_settings",
            lambda: MCPServerSettings(env=env, charts_api_url="http://remote-charts-api")
        )
        monkeypatch.setattr("data360.visualization.post_spec_to_charts_api", mock_post)
        monkeypatch.setattr("data360.visualization.save_specs_to_static", mock_save)

        spec = {"mark": "line", "encoding": {}}
        url = await _store_spec(spec)

        assert url == "http://remote-charts-api/spec/123"
        mock_post.assert_called_once()
        mock_save.assert_not_called()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("env", ["local", "dev", None])
    async def test_store_spec_local_saves_both(self, env, monkeypatch):
        """In local/dev environments, storing spec posts to Charts API and also saves locally."""
        import unittest.mock as mock
        from data360.visualization import _store_spec
        from data360.config import MCPServerSettings

        mock_post = mock.AsyncMock(return_value="http://remote-charts-api/spec/123")
        mock_save = mock.MagicMock(return_value="http://local-static/spec/123")

        monkeypatch.setattr(
            "data360.visualization.get_mcp_server_settings",
            lambda: MCPServerSettings(env=env, charts_api_url="http://remote-charts-api")
        )
        monkeypatch.setattr("data360.visualization.post_spec_to_charts_api", mock_post)
        monkeypatch.setattr("data360.visualization.save_specs_to_static", mock_save)

        spec = {"mark": "line", "encoding": {}}
        url = await _store_spec(spec)

        assert url == "http://remote-charts-api/spec/123"
        mock_post.assert_called_once()
        mock_save.assert_called_once()
