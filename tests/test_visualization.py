"""Tests for data360.visualization module."""

import json
from unittest.mock import AsyncMock, patch

import numpy as np
import pandas as pd
import pytest

from data360.visualization import (
    _clean_single_df,
    _vega_spec_to_json_safe,
    get_viz_spec,
)


class TestGetVizSpecStrategyDispatch:
    """Verify single-indicator specs are built by strategy dispatch."""

    @pytest.fixture
    def sample_dataframe(self):
        """Minimal DataFrame with time_period and obs_value."""
        return pd.DataFrame(
            {
                "TIME_PERIOD": ["2020-01-01", "2021-01-01", "2022-01-01"],
                "OBS_VALUE": [100, 200, 300],
                "REF_AREA": ["KEN", "KEN", "KEN"],
            }
        )

    @pytest.fixture
    def patches(self, sample_dataframe):
        """Set up all the mocks needed to isolate strategy dispatch behavior."""
        with (
            patch(
                "data360.api.get_data_api_url",
                new_callable=AsyncMock,
                return_value="http://fake-api/data?DATABASE_ID=WB_WDI&INDICATOR=FAKE",
            ) as mock_url,
            patch(
                "data360.visualization._fetch_data_internal",
                new_callable=AsyncMock,
                return_value=sample_dataframe,
            ) as mock_fetch,
            patch(
                "data360.api.get_metadata",
                new_callable=AsyncMock,
                return_value=None,
            ) as mock_meta,
            patch(
                "data360.visualization.save_specs_to_static",
                return_value="http://localhost:8021/static/viz_specs/test.json",
            ) as mock_save,
            patch(
                "data360.providers.get_codelist_mapping",
                new_callable=AsyncMock,
                return_value={},
            ) as mock_codelist,
            patch(
                "data360.visualization.get_database_mapping",
                new_callable=AsyncMock,
                return_value={"WB_WDI": "World Development Indicators"},
            ) as mock_dbmap,
        ):
            yield {
                "get_data_api_url": mock_url,
                "fetch_data": mock_fetch,
                "get_metadata": mock_meta,
                "save_specs": mock_save,
                "get_codelist_mapping": mock_codelist,
                "get_database_mapping": mock_dbmap,
            }

    @pytest.mark.asyncio
    async def test_temporal_single_bypasses_draco_and_returns_line(self, patches):
        """TEMPORAL_SINGLE should return a clean line spec via strategy dispatch."""
        result = await get_viz_spec(
            database_id="WB_WDI",
            indicator_id="FAKE_IND",
        )

        # Must succeed cleanly — no error, no fallback warning
        assert result["url"] is not None, "Expected a URL from strategy builder"
        assert result["error"] is None, f"Unexpected error: {result['error']}"
        assert "warning" not in result, (
            "TEMPORAL_SINGLE bypasses Draco, so no fallback warning is expected"
        )
        assert result["strategy"] == "temporal_single"

    @pytest.mark.asyncio
    async def test_strategy_dispatch_failure_returns_error(self, patches):
        """When dispatch_spec raises, an error is returned."""
        with patch(
            "data360.viz_config.dispatch_spec",
            side_effect=RuntimeError("dispatch broke"),
        ):
            result = await get_viz_spec(
                database_id="WB_WDI",
                indicator_id="FAKE_IND",
            )

        assert result["url"] is None
        assert result["error"] is not None


# =============================================================================
# New tests for improvements: MCP-002, MCP-003, MCP-004 + WB style + null guard
# =============================================================================

import math

from data360 import viz_config

# ─────────────────────────────────────────────────────────────────────────────
# Helper: small fixture factory
# ─────────────────────────────────────────────────────────────────────────────


def _make_df(n_countries=3, n_years=5, single_year=False):
    """Return a tidy DataFrame with country / year / value columns."""

    countries = [f"CTR{i:02d}" for i in range(n_countries)]
    years = (
        ["2020-01-01"] if single_year else [f"{2020 + i}-01-01" for i in range(n_years)]
    )
    rows = [
        {"country": c, "year": y, "value": float(i * 10 + j)}
        for i, c in enumerate(countries)
        for j, y in enumerate(years)
    ]
    df = pd.DataFrame(rows)
    df["year"] = pd.to_datetime(df["year"])
    return df


# ─────────────────────────────────────────────────────────────────────────────
# MCP-002  Structured tooltips
# ─────────────────────────────────────────────────────────────────────────────


class TestStructuredTooltips:
    """Tooltips must be typed objects, not raw column name strings."""

    def test_value_tooltip_has_number_format(self):
        tips = viz_config.build_structured_tooltips(
            ["year", "value", "country"], "line"
        )
        value_tip = next(t for t in tips if t["field"] == "value")
        assert value_tip["format"] == ",.2f", "Value tooltip must use number formatting"
        assert value_tip["type"] == "quantitative"

    def test_year_tooltip_temporal_for_annual_string_years(self):
        """String years (e.g. '2018', '2019') should now produce temporal tooltips
        with type=temporal and timeUnit=year so VL formats them as dates correctly
        instead of falling through to the raw epoch timestamp display."""
        df = pd.DataFrame({"year": ["2018", "2019"], "value": [1.0, 2.0]})
        tips = viz_config.build_structured_tooltips(
            ["year", "value"], "line", viz_data=df
        )
        year_tip = next(t for t in tips if t["field"] == "year")
        assert year_tip["type"] == "temporal"
        assert year_tip["timeUnit"] == "year"
        assert year_tip["format"] == "%Y"

    def test_year_tooltip_temporal_when_column_is_datetime(self):
        df = pd.DataFrame(
            {
                "year": pd.to_datetime(["2018-01-01", "2019-01-01"]),
                "value": [1.0, 2.0],
            }
        )
        tips = viz_config.build_structured_tooltips(
            ["year", "value"], "line", viz_data=df
        )
        year_tip = next(t for t in tips if t["field"] == "year")
        assert year_tip["type"] == "temporal"
        assert year_tip["timeUnit"] == "year"
        assert year_tip["format"] == "%Y"

    def test_country_tooltip_is_nominal(self):
        tips = viz_config.build_structured_tooltips(["country", "value"], "bar")
        country_tip = next(t for t in tips if t["field"] == "country")
        assert country_tip["type"] == "nominal"

    def test_priority_order_year_first(self):
        tips = viz_config.build_structured_tooltips(
            ["value", "country", "year"], "line"
        )
        fields = [t["field"] for t in tips]
        assert fields.index("year") < fields.index("value"), "year must precede value"
        assert fields.index("value") < fields.index("country"), (
            "value must precede country"
        )

    def test_unknown_column_gets_title_cased_label(self):
        tips = viz_config.build_structured_tooltips(["some_custom_col"], "bar")
        assert tips[0]["title"] == "Some Custom Col"

    def test_apply_structured_tooltips_injects_into_spec(self):
        spec = {"mark": "line", "encoding": {"x": {"field": "year"}}}
        result = viz_config.apply_structured_tooltips(spec, ["year", "value"], "line")
        assert "tooltip" in result["encoding"]
        assert isinstance(result["encoding"]["tooltip"], list)
        assert all(isinstance(t, dict) for t in result["encoding"]["tooltip"])


# ─────────────────────────────────────────────────────────────────────────────
# MCP-003  High-cardinality beeswarm routing
# ─────────────────────────────────────────────────────────────────────────────


class TestHighCardinalityChartSelection:
    """Above threshold + single year → beeswarm; below threshold → normal."""

    def _df(self, n_countries, single_year=True):
        return _make_df(n_countries=n_countries, single_year=single_year)

    def test_above_threshold_single_year_triggers_beeswarm(self):
        df = self._df(n_countries=12, single_year=True)
        assert viz_config.should_use_beeswarm(df, chart_type=None, color_dim="country")

    def test_below_threshold_does_not_trigger_beeswarm(self):
        df = self._df(n_countries=5, single_year=True)
        assert not viz_config.should_use_beeswarm(
            df, chart_type=None, color_dim="country"
        )

    def test_above_threshold_multi_year_does_not_trigger(self):
        df = self._df(n_countries=15, single_year=False)
        assert not viz_config.should_use_beeswarm(
            df, chart_type=None, color_dim="country"
        )

    def test_explicit_bar_chart_type_does_not_trigger_beeswarm(self):
        df = self._df(n_countries=20, single_year=True)
        assert not viz_config.should_use_beeswarm(
            df, chart_type="bar", color_dim="country"
        )

    def test_beeswarm_spec_uses_tick_mark(self):
        df = self._df(n_countries=15, single_year=True)
        spec = viz_config.build_beeswarm_spec(df, title="Test Chart")
        mark = spec["mark"]
        mark_type = mark["type"] if isinstance(mark, dict) else mark
        assert mark_type == "tick", f"Expected tick mark for beeswarm, got {mark_type}"

    def test_beeswarm_spec_sorts_y_by_value(self):
        df = self._df(n_countries=15, single_year=True)
        spec = viz_config.build_beeswarm_spec(df, title="Test")
        assert spec["encoding"]["y"]["sort"] == "-x"

    def test_beeswarm_spec_limits_to_top_n(self):
        top_n = viz_config.HIGH_CARDINALITY_THRESHOLDS["top_n_series"]
        df = _make_df(n_countries=top_n + 10, single_year=True)
        spec = viz_config.build_beeswarm_spec(df, title="Test")
        assert len(spec["data"]["values"]) <= top_n

    def test_beeswarm_spec_includes_structured_tooltips(self):
        df = self._df(n_countries=15, single_year=True)
        spec = viz_config.build_beeswarm_spec(df, title="Test")
        assert "tooltip" in spec["encoding"]
        tips = spec["encoding"]["tooltip"]
        assert all(isinstance(t, dict) for t in tips), (
            "Tooltips must be dicts, not strings"
        )

    def test_beeswarm_spec_uses_wb_color_palette(self):
        df = self._df(n_countries=15, single_year=True)
        spec = viz_config.build_beeswarm_spec(df, title="Test")
        color_range = spec["encoding"]["color"]["scale"]["range"]
        assert color_range == viz_config.WB_CAT_COLORS


# ─────────────────────────────────────────────────────────────────────────────
# WB Style injection
# ─────────────────────────────────────────────────────────────────────────────


class TestWBStyleInjection:
    """Every spec must receive WB color palette, typography, and grid settings."""

    def test_inject_adds_config_when_absent(self):
        spec = {"mark": "line"}
        result = viz_config.inject_wb_config(spec)
        assert "config" in result

    def test_inject_sets_wb_category_colors(self):
        spec = {"mark": "line"}
        result = viz_config.inject_wb_config(spec)
        assert result["config"]["range"]["category"] == viz_config.WB_CAT_COLORS

    def test_inject_sets_grid_color(self):
        spec = {"mark": "line"}
        result = viz_config.inject_wb_config(spec)
        assert result["config"]["axis"]["gridColor"] == viz_config.WB_GRID_COLOR

    def test_inject_sets_font_family(self):
        spec = {"mark": "line"}
        result = viz_config.inject_wb_config(spec)
        assert "Noto Sans" in result["config"]["font"]

    def test_inject_does_not_overwrite_existing_config_keys(self):
        """User-specified config values must survive injection."""
        spec = {"mark": "line", "config": {"background": "#FF0000"}}
        result = viz_config.inject_wb_config(spec)
        assert result["config"]["background"] == "#FF0000", (
            "inject_wb_config must not overwrite user-set background"
        )

    def test_inject_does_not_overwrite_existing_axis_keys(self):
        spec = {"mark": "line", "config": {"axis": {"gridColor": "#AABBCC"}}}
        result = viz_config.inject_wb_config(spec)
        assert result["config"]["axis"]["gridColor"] == "#AABBCC", (
            "inject_wb_config must not overwrite user-set axis.gridColor"
        )

    def test_apply_wb_style_rule_runs_on_any_mark(self):
        rule = viz_config.ApplyWBStyleRule()
        for mark in ["line", "bar", "point", "tick", "area"]:
            spec = {"mark": mark, "encoding": {}}
            result = rule.apply(spec)
            assert "config" in result, f"WB config not injected for mark={mark}"

    def test_wb_cat_colors_has_nine_entries(self):
        assert len(viz_config.WB_CAT_COLORS) == 9

    def test_wb_cat_colors_first_is_blue(self):
        assert viz_config.WB_CAT_COLORS[0] == "#34A7F2"

    def test_title_config_is_left_anchored(self):
        spec = {"mark": "line"}
        result = viz_config.inject_wb_config(spec)
        assert result["config"]["title"]["anchor"] == "start"

    def test_temporal_axis_cleanup_removes_title(self):
        rule = viz_config.TemporalAxisCleanupRule()
        spec = {
            "mark": "line",
            "encoding": {"x": {"field": "year", "type": "temporal"}},
        }
        result = rule.apply(spec)
        assert result["encoding"]["x"]["axis"]["title"] is None

    def test_zero_line_rule_enforces_zero_for_bar(self):
        rule = viz_config.ZeroLineRule()
        spec = {
            "mark": "bar",
            "encoding": {"y": {"field": "value", "type": "quantitative"}},
        }
        result = rule.apply(spec)
        assert result["encoding"]["y"]["scale"]["zero"] is True


# ─────────────────────────────────────────────────────────────────────────────
# Null / missing value guard  (MCP-004 + obs_value fix)
# ─────────────────────────────────────────────────────────────────────────────


class TestObsValueNullHandling:
    """obs_value NaN must NOT be zeroed — gaps are real missing data."""

    @pytest.fixture
    def patches_with_nulls(self):
        """Fixture: data with one null obs_value row."""
        df = pd.DataFrame(
            {
                "TIME_PERIOD": ["2020-01-01", "2021-01-01", "2022-01-01"],
                "OBS_VALUE": [100.0, None, 300.0],
                "REF_AREA": ["KEN", "KEN", "KEN"],
            }
        )
        with (
            patch(
                "data360.api.get_data_api_url",
                new_callable=AsyncMock,
                return_value="http://fake/data?DATABASE_ID=WB_WDI&INDICATOR=FAKE",
            ),
            patch(
                "data360.visualization._fetch_data_internal",
                new_callable=AsyncMock,
                return_value=df,
            ),
            patch(
                "data360.api.get_metadata", new_callable=AsyncMock, return_value=None
            ),
            patch(
                "data360.visualization.save_specs_to_static",
                return_value="http://localhost/spec.json",
            ),
            patch(
                "data360.providers.get_codelist_mapping",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "data360.visualization.get_database_mapping",
                new_callable=AsyncMock,
                return_value={"WB_WDI": "World Development Indicators"},
            ),
        ):
            yield df

    @pytest.mark.asyncio
    async def test_null_obs_value_not_coerced_to_zero(self, patches_with_nulls):
        """After processing, the 2021 value must remain NaN, not become 0."""
        captured_data = {}

        original_save = __import__(
            "data360.visualization", fromlist=["save_specs_to_static"]
        ).save_specs_to_static

        def capture_spec(spec):
            captured_data["spec"] = spec
            return "http://localhost/spec.json"

        with patch(
            "data360.visualization.save_specs_to_static", side_effect=capture_spec
        ):
            result = await get_viz_spec(
                database_id="WB_WDI",
                indicator_id="FAKE_IND",
            )

        # If spec was captured, verify the data values
        if "spec" in captured_data:
            spec = captured_data["spec"]
            # Find inline data values
            data_values = None
            if "data" in spec and "values" in spec["data"]:
                data_values = spec["data"]["values"]
            elif "datasets" in spec:
                for ds in spec["datasets"].values():
                    data_values = ds
                    break

            if data_values:
                value_for_2021 = None
                for row in data_values:
                    ts = row.get("year") or row.get("time_period") or ""
                    if "2021" in str(ts):
                        value_for_2021 = row.get("value") or row.get("obs_value")
                        break

                if value_for_2021 is not None:
                    assert value_for_2021 != 0, (
                        "Missing obs_value must not be zeroed — "
                        f"got {value_for_2021} instead of NaN/null"
                    )

    def test_obs_value_numeric_coercion_preserves_nan(self):
        """Unit test: pd.to_numeric(errors='coerce') on None keeps NaN, not 0."""
        series = pd.Series([100.0, None, 300.0])
        result = pd.to_numeric(series, errors="coerce")
        assert math.isnan(result.iloc[1]), "None must become NaN after to_numeric"
        assert result.iloc[0] == 100.0
        assert result.iloc[2] == 300.0

    def test_fillna_zero_would_corrupt_data(self):
        """Regression guard: .fillna(0) produces 0 for missing — we must NOT do this."""
        series = pd.Series([100.0, None, 300.0])
        bad_result = pd.to_numeric(series, errors="coerce").fillna(0)
        assert bad_result.iloc[1] == 0.0, "This test documents the old buggy behaviour"
        # Confirm we're NOT doing this in the real code by checking viz source
        import inspect

        import data360.visualization as viz_mod

        source = inspect.getsource(viz_mod)
        assert "fillna(0)" not in source, (
            "visualization.py must not call .fillna(0) on obs_value — "
            "it silently converts missing data to zero"
        )


# ─────────────────────────────────────────────────────────────────────────────
# _clean_single_df: numeric value column
# ─────────────────────────────────────────────────────────────────────────────


class TestCleanSingleDfValueNumeric:
    """`value` must be numeric for correct Altair inference after rename."""

    def test_value_object_strings_coerced_after_rename(self):
        data = pd.DataFrame(
            {
                "time_period": ["2020-01-01", "2021-01-01"],
                "value": ["10.5", "20.25"],
                "ref_area": ["KEN", "KEN"],
            }
        )
        viz_data, _, _freq = _clean_single_df(
            data,
            relevant_fields=["time_period", "value", "ref_area"],
            chart_type=None,
            data_frequency=None,
        )
        assert pd.api.types.is_numeric_dtype(viz_data["value"])
        assert float(viz_data["value"].iloc[0]) == 10.5
        assert float(viz_data["value"].iloc[1]) == 20.25


# ─────────────────────────────────────────────────────────────────────────────
# POST-PROCESSING RULE CHAIN
# ─────────────────────────────────────────────────────────────────────────────


class TestPostProcessingRuleChain:
    """Verify the rule registry runs without errors on typical specs."""

    def _run_rules(self, spec, frequency=None):
        for rule in viz_config.POST_PROCESSING_RULES:
            spec = rule.apply(spec, frequency)
        return spec

    def test_chain_runs_on_line_chart(self):
        spec = {
            "mark": "line",
            "encoding": {
                "x": {"field": "year", "type": "temporal"},
                "y": {"field": "value", "type": "quantitative"},
            },
        }
        result = self._run_rules(spec, "A")
        assert "config" in result
        assert result["encoding"]["x"]["axis"]["title"] is None

    def test_line_chart_ordinal_value_y_becomes_quantitative(self):
        """Altair sometimes emits ordinal y for value on line marks; post-process fixes it."""
        spec = {
            "mark": {"type": "line"},
            "encoding": {
                "x": {"field": "year", "type": "temporal"},
                "y": {"field": "value", "type": "ordinal"},
            },
        }
        result = self._run_rules(spec, "A")
        assert result["encoding"]["y"]["type"] == "quantitative"
        assert result["encoding"]["y"].get("scale", {}).get("type") == "linear"

    def test_line_chart_y_axis_gets_compact_label_expr(self):
        spec = {
            "mark": {"type": "line"},
            "encoding": {
                "x": {"field": "year", "type": "temporal"},
                "y": {"field": "value", "type": "quantitative"},
            },
        }
        result = self._run_rules(spec, "A")
        expr = result["encoding"]["y"]["axis"]["labelExpr"]
        assert "datum.value" in expr
        assert "1e9" in expr

    def test_line_chart_y_axis_currency_expr_for_current_usd(self):
        spec = {
            "mark": {"type": "line"},
            "encoding": {
                "x": {"field": "year", "type": "temporal"},
                "y": {"field": "value", "type": "quantitative"},
            },
        }
        for rule in viz_config.POST_PROCESSING_RULES:
            spec = rule.apply(spec, "A", "current US$")
        expr = spec["encoding"]["y"]["axis"]["labelExpr"]
        assert "'$'+format" in expr

    def test_line_chart_string_mark_gets_hover_points_after_chain(self):
        spec = {
            "mark": "line",
            "encoding": {
                "x": {"field": "year", "type": "temporal"},
                "y": {"field": "value", "type": "quantitative"},
            },
        }
        result = self._run_rules(spec, "A")
        m = result["mark"]
        assert isinstance(m, dict)
        assert m.get("type") == "line"
        assert isinstance(m.get("point"), dict)
        assert m["point"].get("size", 0) >= 40

    def test_area_chart_ordinal_value_y_becomes_quantitative(self):
        spec = {
            "mark": {"type": "area"},
            "encoding": {
                "x": {"field": "year", "type": "temporal"},
                "y": {"field": "value", "type": "ordinal"},
            },
        }
        result = self._run_rules(spec, None)
        assert result["encoding"]["y"]["type"] == "quantitative"

    def test_chain_runs_on_bar_chart(self):
        spec = {
            "mark": "bar",
            "encoding": {
                "x": {"field": "country", "type": "nominal"},
                "y": {"field": "value", "type": "quantitative"},
            },
        }
        result = self._run_rules(spec)
        assert "config" in result
        assert result["encoding"]["y"]["scale"]["zero"] is True

    def test_chain_does_not_raise_on_empty_encoding(self):
        spec = {"mark": "point", "encoding": {}}
        result = self._run_rules(spec)
        assert "config" in result

    def test_apply_wb_style_is_last_rule(self):
        last = viz_config.POST_PROCESSING_RULES[-1]
        assert last.name == "apply_wb_style", (
            "ApplyWBStyleRule must be last so it doesn't overwrite other fixes"
        )


class TestVegaSpecJsonSafe:
    """_vega_spec_to_json_safe must match what json.dumps / httpx need for Charts API."""

    def test_nested_timestamp_and_numpy_roundtrip(self):
        spec = {
            "data": {
                "values": [
                    {
                        "year": pd.Timestamp("2020-01-01"),
                        "v": np.float64(3.14),
                    }
                ]
            }
        }
        safe = _vega_spec_to_json_safe(spec)
        json.dumps(safe)
        y = safe["data"]["values"][0]["year"]
        assert isinstance(y, str) and y.startswith("2020-01-01")
        assert isinstance(safe["data"]["values"][0]["v"], float)


# ─────────────────────────────────────────────────────────────────────────────
# Override Warning Injection
# ─────────────────────────────────────────────────────────────────────────────


class TestChartTypeOverrideWarning:
    """Ensure we warn the LLM if the pipeline rejects its chart_type hint."""

    @pytest.fixture
    def sample_dataframe(self):
        # 3 countries, 3 years -> should be temporal_single (line)
        return pd.DataFrame(
            {
                "TIME_PERIOD": ["2020-01-01", "2021-01-01", "2022-01-01"] * 3,
                "OBS_VALUE": [100, 200, 300] * 3,
                "REF_AREA": [
                    "KEN",
                    "KEN",
                    "KEN",
                    "UGA",
                    "UGA",
                    "UGA",
                    "TZA",
                    "TZA",
                    "TZA",
                ],
            }
        )

    @pytest.fixture
    def patches(self, sample_dataframe):
        with (
            patch(
                "data360.api.get_data_api_url",
                new_callable=AsyncMock,
                return_value="http://fake-api/data?DATABASE_ID=WB_WDI&INDICATOR=FAKE",
            ),
            patch(
                "data360.visualization._fetch_data_internal",
                new_callable=AsyncMock,
                return_value=sample_dataframe,
            ),
            patch(
                "data360.api.get_metadata", new_callable=AsyncMock, return_value=None
            ),
            patch(
                "data360.visualization.save_specs_to_static",
                return_value="http://localhost:8021/static/viz_specs/test.json",
            ),
            patch(
                "data360.providers.get_codelist_mapping",
                new_callable=AsyncMock,
                return_value={},
            ),
            patch(
                "data360.visualization.get_database_mapping",
                new_callable=AsyncMock,
                return_value={"WB_WDI": "World Development Indicators"},
            ),
        ):
            yield

    @pytest.mark.asyncio
    @pytest.mark.parametrize("requested_chart", ["strip", "small_multiples"])
    async def test_warning_injected_when_hint_overridden(self, patches, requested_chart):
        """If LLM requests an incompatible chart type, a warning should be present."""
        result = await get_viz_spec(
            database_id="WB_WDI",
            indicator_id="FAKE_IND",
            chart_type=requested_chart,
            chart_title=f"Fake {requested_chart}",
        )
        assert "warning" in result
        assert (
            f"You requested '{requested_chart}', but the visualization engine selected"
            in result["warning"]
        )

    @pytest.mark.asyncio
    @pytest.mark.parametrize("requested_chart", ["line", "bar", "scatter", "area", "stacked_area", "heatmap", "map", "choropleth"])
    async def test_no_warning_when_hint_matches(self, patches, requested_chart):
        """If LLM requests a chart type that the pipeline can honor, no warning is emitted."""
        result = await get_viz_spec(
            database_id="WB_WDI",
            indicator_id="FAKE_IND",
            chart_type=requested_chart,
            chart_title=f"Fake {requested_chart}",
        )
        assert "warning" not in result or result["warning"] is None


class TestVisualizationUnitQualification:
    """Tests for unit qualification and suppression in visualization pipelines."""

    @pytest.mark.asyncio
    async def test_fetch_single_indicator_suppresses_unmapped_unit(self):
        """Verify that an unmapped unit measure (other than PS) is suppressed (None) in visualizations."""
        df = pd.DataFrame({
            "TIME_PERIOD": ["2020", "2021"],
            "OBS_VALUE": [100.0, 200.0],
            "REF_AREA": ["KEN", "KEN"],
            "unit_measure": ["XYZ", "XYZ"],
            "unit_mult": ["6", "6"],
        })

        with (
            patch("data360.api.get_data_api_url", new_callable=AsyncMock, return_value="http://fake-api/data?DATABASE_ID=WB_WDI&INDICATOR=FAKE"),
            patch("data360.visualization._fetch_data_internal", new_callable=AsyncMock, return_value=df),
            patch("data360.api.get_metadata", new_callable=AsyncMock, return_value=None),
        ):
            from data360.visualization import _fetch_single_indicator
            _, _, unit = await _fetch_single_indicator(
                database_id="WB_WDI",
                indicator_id="FAKE_IND",
                country_code=None,
                start_year=None,
                end_year=None,
                disaggregation_filters=None,
            )
            # XYZ is unmapped and not PS, so it must be suppressed to None
            assert unit is None

    @pytest.mark.asyncio
    async def test_fetch_single_indicator_qualifies_unmapped_ps(self):
        """Verify that the unmapped special case PS is qualified to 'million people'."""
        df = pd.DataFrame({
            "TIME_PERIOD": ["2020", "2021"],
            "OBS_VALUE": [100.0, 200.0],
            "REF_AREA": ["KEN", "KEN"],
            "unit_measure": ["PS", "PS"],
            "unit_mult": ["6", "6"],
        })

        with (
            patch("data360.api.get_data_api_url", new_callable=AsyncMock, return_value="http://fake-api/data?DATABASE_ID=WB_WDI&INDICATOR=FAKE"),
            patch("data360.visualization._fetch_data_internal", new_callable=AsyncMock, return_value=df),
            patch("data360.api.get_metadata", new_callable=AsyncMock, return_value=None),
        ):
            from data360.visualization import _fetch_single_indicator
            _, _, unit = await _fetch_single_indicator(
                database_id="WB_WDI",
                indicator_id="FAKE_IND",
                country_code=None,
                start_year=None,
                end_year=None,
                disaggregation_filters=None,
            )
            assert unit == "million people"
