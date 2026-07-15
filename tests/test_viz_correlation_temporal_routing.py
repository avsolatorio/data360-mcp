"""Phase 8 — Correlation temporal auto-routing.

When a user has 2 indicators, multiple countries, and multiple years,
the current router always chooses SMALL_MULTIPLES. For small datasets
(≤8 countries × ≤8 years), a CORRELATION_TEMPORAL (connected scatter)
is far more informative — it reveals how the relationship between the
two indicators evolves over time for each country.

Contract:
  - 2 indicators, country_count ≤ 8, year_count ≤ 8 → CORRELATION_TEMPORAL
  - 2 indicators, country_count > 8 OR year_count > 8 → SMALL_MULTIPLES (unchanged)
  - 2 indicators, single year → CORRELATION (existing cross-sectional scatter)
  - Explicit hint (scatter/point/connected_scatter) still overrides via ExplicitScatterRule
  - The resulting spec must be a layered (line + circle) connected scatter
"""

from __future__ import annotations

import pandas as pd
import pytest

from data360.viz_config import (
    CORRELATION_TEMPORAL_AUTO_MAX_COUNTRIES,
    CORRELATION_TEMPORAL_AUTO_MAX_YEARS,
    ChartStrategy,
    select_strategy,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _two_ind_df(n_countries: int, n_years: int) -> pd.DataFrame:
    """2-indicator wide-format DF as produced by get_multi_indicator_viz_spec."""
    countries = [f"C{i:02d}" for i in range(n_countries)]
    years = [str(2020 + i) for i in range(n_years)]
    rows = []
    for c in countries:
        for y in years:
            rows.append({
                "country": c,
                "year": y,
                "indicator_a": float(hash(c + y) % 100),
                "indicator_b": float(hash(c + y + "b") % 100),
            })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Phase 8: auto-routing to CORRELATION_TEMPORAL for small 2-indicator datasets
# ---------------------------------------------------------------------------


class TestCorrelationTemporalAutoRouting:
    """2 indicators + small multi-country multi-year data should route to CORRELATION_TEMPORAL when scatter hint is provided."""

    @pytest.mark.parametrize("n_countries,n_years", [
        (2, 5),
        (3, 8),
        (8, 2),
        (8, 8),
        (4, 4),
    ])
    def test_small_dataset_routes_to_correlation_temporal(self, n_countries, n_years):
        """≤8 countries × ≤8 years with 2 indicators + scatter hint → CORRELATION_TEMPORAL."""
        df = _two_ind_df(n_countries, n_years)
        result = select_strategy(
            df,
            n_indicators=2,
            indicator_cols=["indicator_a", "indicator_b"],
            chart_type_hint="scatter",
        )
        assert result.strategy == ChartStrategy.CORRELATION_TEMPORAL, (
            f"Expected CORRELATION_TEMPORAL for {n_countries} countries × {n_years} years, "
            f"got {result.strategy.value!r}. Connected scatter better shows relationship "
            f"evolution than {n_countries} small-multiples panels."
        )

    @pytest.mark.parametrize("n_countries,n_years", [
        (9, 5),   # too many countries
        (15, 3),  # way too many countries
        (3, 9),   # too many years
        (4, 15),  # way too many years
    ])
    def test_large_dataset_stays_small_multiples(self, n_countries, n_years):
        """Beyond thresholds, SMALL_MULTIPLES remains the better choice."""
        df = _two_ind_df(n_countries, n_years)
        result = select_strategy(
            df,
            n_indicators=2,
            indicator_cols=["indicator_a", "indicator_b"],
        )
        assert result.strategy == ChartStrategy.SMALL_MULTIPLES, (
            f"Expected SMALL_MULTIPLES for {n_countries} countries × {n_years} years "
            f"(beyond threshold {CORRELATION_TEMPORAL_AUTO_MAX_COUNTRIES} countries / "
            f"{CORRELATION_TEMPORAL_AUTO_MAX_YEARS} years), "
            f"got {result.strategy.value!r}."
        )

    def test_single_year_two_indicators_stays_correlation(self):
        """Single year with 2 indicators is a cross-sectional scatter — not a connected scatter."""
        df = _two_ind_df(n_countries=5, n_years=1)
        result = select_strategy(
            df,
            n_indicators=2,
            indicator_cols=["indicator_a", "indicator_b"],
        )
        assert result.strategy == ChartStrategy.CORRELATION, (
            f"Expected CORRELATION for single-year 2-indicator data, got {result.strategy.value!r}."
        )

    def test_correlation_temporal_result_has_correct_metadata(self):
        """StrategyResult must carry indicator_cols and color_dim=country for the spec builder."""
        df = _two_ind_df(n_countries=4, n_years=5)
        result = select_strategy(
            df,
            n_indicators=2,
            indicator_cols=["indicator_a", "indicator_b"],
            chart_type_hint="scatter",
        )
        assert result.strategy == ChartStrategy.CORRELATION_TEMPORAL
        assert result.indicator_cols == ["indicator_a", "indicator_b"], (
            "CORRELATION_TEMPORAL StrategyResult must carry indicator_cols for build_correlation_temporal_spec."
        )
        assert result.color_dim == "country", (
            "CORRELATION_TEMPORAL StrategyResult must set color_dim='country' for country color coding."
        )

    def test_explicit_scatter_hint_still_overrides(self):
        """A user explicitly requesting 'scatter' must still override auto-routing."""
        df = _two_ind_df(n_countries=10, n_years=10)  # outside threshold
        result = select_strategy(
            df,
            n_indicators=2,
            indicator_cols=["indicator_a", "indicator_b"],
            chart_type_hint="scatter",
        )
        # ExplicitScatterRule fires before TwoIndicatorRule
        assert result.strategy in (ChartStrategy.CORRELATION_TEMPORAL, ChartStrategy.CORRELATION), (
            "Explicit scatter hint must override auto-routing regardless of data size."
        )


# ---------------------------------------------------------------------------
# Constants sanity check
# ---------------------------------------------------------------------------


class TestConstantValues:
    """The threshold constants must be within sensible bounds."""

    def test_max_countries_in_range(self):
        assert 2 <= CORRELATION_TEMPORAL_AUTO_MAX_COUNTRIES <= 12, (
            f"CORRELATION_TEMPORAL_AUTO_MAX_COUNTRIES={CORRELATION_TEMPORAL_AUTO_MAX_COUNTRIES} "
            f"is outside the sensible range [2, 12]."
        )

    def test_max_years_in_range(self):
        assert 2 <= CORRELATION_TEMPORAL_AUTO_MAX_YEARS <= 15, (
            f"CORRELATION_TEMPORAL_AUTO_MAX_YEARS={CORRELATION_TEMPORAL_AUTO_MAX_YEARS} "
            f"is outside the sensible range [2, 15]."
        )
