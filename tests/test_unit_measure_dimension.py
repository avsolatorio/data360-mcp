"""
Tests for unit_measure as a first-class discriminating dimension.

Verifies that:
- _clean_single_df includes unit_measure when 2+ non-trivial distinct values exist.
- _clean_single_df drops unit_measure when single-valued or all-trivial.
- select_strategy counts unit_measure in breakdown_counts correctly.
- _extract_dimension_summary surfaces non-trivial dimensions only.
"""

from __future__ import annotations

import pandas as pd

from data360 import viz_config
from data360.visualization import (
    _build_data_summary,
    _clean_single_df,
    _extract_dimension_summary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_df(unit_measure_vals: list[str | None], extra: dict | None = None) -> pd.DataFrame:
    """Build a minimal raw DataFrame with the given unit_measure column values."""
    n = len(unit_measure_vals)
    data = {
        "time_period": ["2020-01-01"] * n,
        "obs_value": [1.0] * n,
        "ref_area": ["GEO"] * n,
        "unit_measure": unit_measure_vals,
    }
    if extra:
        data.update(extra)
    return pd.DataFrame(data)


# ---------------------------------------------------------------------------
# _clean_single_df — unit_measure column inclusion logic
# ---------------------------------------------------------------------------


class TestCleanSingleDfUnitMeasure:
    def test_unit_measure_kept_when_multi_valued(self):
        """Two meaningful unit values → unit_measure included in output."""
        df = _make_df(["Persons", "Percentage", "Persons", "Percentage"])
        viz_data, relevant_cols, _ = _clean_single_df(df, None, None, None)

        assert "unit_measure" in viz_data.columns, (
            "unit_measure should be kept when 2+ distinct non-trivial values exist"
        )
        assert "unit_measure" in relevant_cols

    def test_unit_measure_dropped_when_single_valued(self):
        """All rows have the same unit → unit_measure not added."""
        df = _make_df(["Persons", "Persons", "Persons"])
        viz_data, relevant_cols, _ = _clean_single_df(df, None, None, None)

        assert "unit_measure" not in viz_data.columns

    def test_unit_measure_dropped_when_unitless_sentinel(self):
        """'U' = Unitless sentinel → dropped as non-discriminating."""
        df = _make_df(["U", "U", "U"])
        viz_data, _, _freq = _clean_single_df(df, None, None, None)

        assert "unit_measure" not in viz_data.columns

    def test_unit_measure_dropped_when_empty_string_only(self):
        """Empty-string unit → treated as trivial, not included."""
        df = _make_df(["", "", ""])
        viz_data, _, _freq = _clean_single_df(df, None, None, None)

        assert "unit_measure" not in viz_data.columns

    def test_unit_measure_dropped_when_column_absent(self):
        """No unit_measure column in source → no crash, column not added."""
        df = pd.DataFrame({
            "time_period": ["2020-01-01"],
            "obs_value": [1.0],
            "ref_area": ["GEO"],
        })
        viz_data, _, _freq = _clean_single_df(df, None, None, None)
        assert "unit_measure" not in viz_data.columns

    def test_unit_measure_included_via_relevant_fields(self):
        """When relevant_fields explicitly lists unit_measure, it is kept."""
        df = _make_df(["Persons", "Percentage"])
        viz_data, _, _freq = _clean_single_df(
            df,
            relevant_fields=["time_period", "obs_value", "ref_area", "unit_measure"],
            chart_type=None,
            data_frequency=None,
        )
        assert "unit_measure" in viz_data.columns

    def test_unit_measure_added_by_relevant_fields_branch_when_multi(self):
        """Even when relevant_fields does NOT list it, multi-value detection adds it."""
        df = _make_df(["Persons", "Percentage"])
        viz_data, _, _freq = _clean_single_df(
            df,
            relevant_fields=["time_period", "obs_value", "ref_area"],
            chart_type=None,
            data_frequency=None,
        )
        assert "unit_measure" in viz_data.columns


# ---------------------------------------------------------------------------
# select_strategy — unit_measure counted in breakdown_counts
# ---------------------------------------------------------------------------


class TestSelectStrategyUnitMeasure:
    def _make_viz_df(
        self,
        unit_values: list[str] | None = None,
        n_years: int = 10,
        n_countries: int = 1,
    ) -> pd.DataFrame:
        rows = []
        for year in range(2010, 2010 + n_years):
            for country in [f"C{i}" for i in range(n_countries)]:
                units = unit_values or ["Persons"]
                for unit in units:
                    rows.append({
                        "year": str(year),
                        "value": 1.0,
                        "country": country,
                        "unit_measure": unit,
                    })
        return pd.DataFrame(rows)

    def test_multi_unit_triggers_small_multiples(self):
        """unit_measure with 2+ values always routes to SMALL_MULTIPLES.

        Different units (Persons vs Percentage) are inherently scale-incompatible —
        they can never share a Y-axis. The route is unconditional regardless of
        country count or year count.
        """
        df = self._make_viz_df(unit_values=["Persons", "Percentage"], n_countries=1)
        result = viz_config.select_strategy(df, n_indicators=1)

        assert result.strategy == viz_config.ChartStrategy.SMALL_MULTIPLES, (
            f"Expected SMALL_MULTIPLES, got {result.strategy}"
        )
        assert result.facet_dim == "unit_measure"
        assert result.scale_incompatible is True

    def test_multi_unit_multi_country_always_facets_by_unit_measure(self):
        """With multiple countries + unit_measure, facet_dim should ALWAYS be 'unit_measure'.

        Country goes into secondary_color_dim so the spec builder can create
        combo shade families (breakdown × country) within each unit panel.
        Mixing Persons and Percentage on one Y-axis is never correct regardless
        of country count.
        """
        df = self._make_viz_df(unit_values=["Persons", "Percentage"], n_countries=3)
        result = viz_config.select_strategy(df, n_indicators=1)

        assert result.strategy == viz_config.ChartStrategy.SMALL_MULTIPLES
        assert result.facet_dim == "unit_measure", (
            "facet_dim must be unit_measure, not country, to keep units on separate Y-axes"
        )
        assert result.secondary_color_dim == "country", (
            "secondary_color_dim should carry country for combo encoding"
        )

    def test_single_unit_does_not_affect_strategy(self):
        """unit_measure with a single value is not in breakdown_counts → normal routing."""
        df = self._make_viz_df(unit_values=["Persons"])
        result = viz_config.select_strategy(df, n_indicators=1)

        # Should be temporal_single (10 years, 1 country, no other breakdowns)
        assert result.strategy == viz_config.ChartStrategy.TEMPORAL_SINGLE

    def test_no_unit_measure_column_is_safe(self):
        """DataFrame without unit_measure column → no error, routing unchanged."""
        df = pd.DataFrame({
            "year": [str(y) for y in range(2010, 2020)],
            "value": [1.0] * 10,
            "country": ["GEO"] * 10,
        })
        result = viz_config.select_strategy(df, n_indicators=1)
        assert result.strategy == viz_config.ChartStrategy.TEMPORAL_SINGLE


# ---------------------------------------------------------------------------
# _extract_dimension_summary
# ---------------------------------------------------------------------------


class TestExtractDimensionSummary:
    def test_returns_multi_valued_dims(self):
        df = pd.DataFrame({
            "unit_measure": ["Persons", "Percentage", "Persons"],
            "sex": ["_T", "_T", "_T"],  # trivial → excluded
            "comp_breakdown_2": ["Phase 1", "Phase 2", "Phase 1"],
        })
        result = _extract_dimension_summary(df)

        assert "unit_measure" in result
        assert result["unit_measure"] == ["Percentage", "Persons"]
        assert "comp_breakdown_2" in result
        assert "sex" not in result, "All-_T sex column should not appear"

    def test_excludes_all_trivial_sentinels(self):
        df = pd.DataFrame({
            "unit_measure": ["U", "U"],
            "sex": ["_T", "_T"],
        })
        result = _extract_dimension_summary(df)
        assert result == {}

    def test_missing_columns_are_skipped_safely(self):
        df = pd.DataFrame({"year": [2020, 2021], "value": [1.0, 2.0]})
        result = _extract_dimension_summary(df)
        assert result == {}

    def test_single_valued_dim_excluded(self):
        df = pd.DataFrame({
            "unit_measure": ["Persons", "Persons", "Persons"],
        })
        result = _extract_dimension_summary(df)
        assert "unit_measure" not in result


# ---------------------------------------------------------------------------
# _build_data_summary
# ---------------------------------------------------------------------------


class TestBuildDataSummary:
    def _base_df(self) -> pd.DataFrame:
        return pd.DataFrame({
            "year": ["2019", "2020", "2021", "2022"],
            "country": ["Ethiopia", "Ethiopia", "Ethiopia", "Ethiopia"],
            "value": [100.0, 200.0, 150.0, 250.0],
            "unit_measure": ["Persons"] * 4,
        })

    def test_shape_always_present(self):
        df = self._base_df()
        result = _build_data_summary(df)
        assert result["shape"] == [4, 4]

    def test_year_range(self):
        df = self._base_df()
        result = _build_data_summary(df)
        assert result["year_range"] == ["2019", "2022"]

    def test_countries_sorted(self):
        df = pd.DataFrame({
            "year": ["2020", "2020"],
            "country": ["Zimbabwe", "Angola"],
            "value": [1.0, 2.0],
        })
        result = _build_data_summary(df)
        assert result["countries"] == ["Angola", "Zimbabwe"]

    def test_value_range_positive(self):
        df = self._base_df()
        result = _build_data_summary(df)
        assert result["value"]["min"] == 100.0
        assert result["value"]["max"] == 250.0
        assert result["value"]["has_negatives"] is False

    def test_value_range_with_negatives(self):
        df = pd.DataFrame({
            "year": ["2020", "2021"],
            "country": ["Georgia", "Georgia"],
            "value": [-1.5, 2.3],
        })
        result = _build_data_summary(df)
        assert result["value"]["has_negatives"] is True
        assert result["value"]["min"] == -1.5

    def test_missing_year_column_skipped(self):
        df = pd.DataFrame({"country": ["A"], "value": [1.0]})
        result = _build_data_summary(df)
        assert "year_range" not in result

    def test_missing_country_column_skipped(self):
        df = pd.DataFrame({"year": ["2020"], "value": [1.0]})
        result = _build_data_summary(df)
        assert "countries" not in result

    def test_missing_value_column_skipped(self):
        df = pd.DataFrame({"year": ["2020"], "country": ["A"]})
        result = _build_data_summary(df)
        assert "value" not in result

    def test_empty_dataframe_returns_shape_only(self):
        df = pd.DataFrame(columns=["year", "country", "value"])
        result = _build_data_summary(df)
        assert result["shape"] == [0, 3]
        assert "year_range" not in result
        assert "countries" not in result
        assert "value" not in result
