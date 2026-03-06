"""Tests for data360.visualization module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from data360.visualization import get_viz_spec


class TestGetVizSpecDracoFallbackWarning:
    """Verify that a warning is surfaced when Draco fails and fallback is used."""

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
        """Set up all the mocks needed to isolate the Draco fallback path."""
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
        ):
            yield {
                "get_data_api_url": mock_url,
                "fetch_data": mock_fetch,
                "get_metadata": mock_meta,
                "save_specs": mock_save,
                "get_codelist_mapping": mock_codelist,
            }

    @pytest.mark.asyncio
    async def test_fallback_returns_warning(self, patches):
        """When Draco raises StopIteration, the response should include a warning key."""
        with patch("data360.visualization.Draco") as MockDraco:
            draco_instance = MagicMock()
            draco_instance.complete_spec.return_value = iter([])
            MockDraco.return_value = draco_instance

            result = await get_viz_spec(
                database_id="WB_WDI",
                indicator_id="FAKE_IND",
            )

        assert result["url"] is not None, "Expected a URL from fallback generation"
        assert result["error"] is None, "Expected no error from successful fallback"
        assert "warning" in result, "Expected a 'warning' key when Draco falls back"
        assert "fallback" in result["warning"].lower(), (
            f"Warning message should mention fallback, got: {result['warning']}"
        )

    @pytest.mark.asyncio
    async def test_draco_success_has_no_warning(self, patches):
        """When Draco succeeds, no warning key should be present."""
        # Build a chainable mock chart that returns a valid spec from to_dict()
        mock_chart = MagicMock()
        mock_vl_spec = {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "mark": "point",
            "encoding": {"x": {"field": "year", "type": "temporal"},
                         "y": {"field": "value", "type": "quantitative"}},
        }
        # Chain: chart.properties(...).interactive().encode(...).to_dict()
        mock_chart.properties.return_value = mock_chart
        mock_chart.interactive.return_value = mock_chart
        mock_chart.encode.return_value = mock_chart
        mock_chart.to_dict.return_value = mock_vl_spec

        with (
            patch("data360.visualization.Draco") as MockDraco,
            patch("data360.visualization.answer_set_to_dict") as mock_as2d,
            patch("data360.visualization.AltairRenderer") as MockRenderer,
        ):
            fake_model = MagicMock()
            draco_instance = MagicMock()
            draco_instance.complete_spec.return_value = iter([fake_model])
            MockDraco.return_value = draco_instance

            mock_as2d.return_value = {"view": [{"mark": [{"type": "point", "encoding": []}]}]}

            renderer_instance = MagicMock()
            renderer_instance.render.return_value = mock_chart
            MockRenderer.return_value = renderer_instance

            result = await get_viz_spec(
                database_id="WB_WDI",
                indicator_id="FAKE_IND",
            )

        assert result["error"] is None, f"Unexpected error: {result['error']}"
        assert result["url"] is not None
        assert "warning" not in result, (
            f"No warning expected on Draco success, got: {result.get('warning')}"
        )

    @pytest.mark.asyncio
    async def test_fallback_also_fails_returns_error(self, patches):
        """When both Draco and the manual fallback fail, an error is returned."""
        with (
            patch("data360.visualization.Draco") as MockDraco,
            patch("data360.visualization.alt") as MockAlt,
        ):
            draco_instance = MagicMock()
            draco_instance.complete_spec.return_value = iter([])
            MockDraco.return_value = draco_instance

            MockAlt.Chart.side_effect = RuntimeError("Altair broke")

            result = await get_viz_spec(
                database_id="WB_WDI",
                indicator_id="FAKE_IND",
            )

        assert result["url"] is None
        assert result["error"] is not None
        assert "fallback failed" in result["error"].lower()
