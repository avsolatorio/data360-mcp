"""Integration tests: verify that get_viz_spec produces Vega-Lite specs whose
data.values contain resolved human-readable labels instead of raw dimension codes.

Strategy:
  - Pre-populate the global CodelistManager singleton with fake resolved data.
  - Patch the full call chain at the network boundary (_fetch_data_internal and
    data360.api.get_metadata / get_disaggregation) so tests run fully offline.
  - Assert the stored spec JSON contains resolved labels, not raw codes.
"""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pandas as pd
import pytest

from data360.providers import get_codelist_manager

# ---------------------------------------------------------------------------
# Resolved codelist fixture
# ---------------------------------------------------------------------------

_RESOLVED = {
    "COMP_BREAKDOWN": {
        "WGI_EST": "Governance estimate",
        "WGI_SC": "Percentile rank",
        "WGI_SC_LB": "Lower confidence bound",
        "WGI_SC_UB": "Upper confidence bound",
        "WGI_SE": "Standard error",
        "WGI_SR": "Source count",
    },
    "SEX": {"F": "Female", "M": "Male", "_T": "Total"},
    "AGE": {"_T": "All ages", "Y15T24": "15 to 24 years"},
    "URBANISATION": {"URB": "Urban area", "RUR": "Rural area"},
    "UNIT_MEASURE": {"PT": "Percent", "USD": "US Dollars", "NUM": "Number"},
    "REF_AREA": {"GEO": "Georgia", "KEN": "Kenya"},
}

_CODES = ["WGI_EST", "WGI_SC", "WGI_SE", "WGI_SR", "WGI_SC_LB", "WGI_SC_UB"]
_YEARS = pd.date_range("1996", periods=5, freq="YE")


@pytest.fixture(autouse=True)
def inject_codelist():
    """Inject pre-resolved labels into the global singleton before each test."""
    mgr = get_codelist_manager()
    original = dict(mgr._extdataportal)
    mgr._extdataportal = dict(_RESOLVED)
    yield
    mgr._extdataportal = original


# ---------------------------------------------------------------------------
# Minimal fake API data
# ---------------------------------------------------------------------------

def _make_wgi_rows(country: str = "GEO", codes: list | None = None) -> list[dict]:
    if codes is None:
        codes = _CODES
    return [
        {
            "REF_AREA": country,
            "TIME_PERIOD": yr.strftime("%Y-%m-%dT00:00:00"),
            "OBS_VALUE": "1.23",
            "COMP_BREAKDOWN_1": code,
            "FREQ": "A",
            "UNIT_MEASURE": "PT",
        }
        for code in codes
        for yr in _YEARS
    ]


def _make_sex_rows(country: str = "GEO") -> list[dict]:
    return [
        {
            "REF_AREA": country,
            "TIME_PERIOD": yr.strftime("%Y-%m-%dT00:00:00"),
            "OBS_VALUE": "1.0",
            "SEX": sex,
            "FREQ": "A",
            "UNIT_MEASURE": "PT",
        }
        for sex in ("F", "M")
        for yr in _YEARS
    ]


def _fake_meta(name: str = "Governance Effectiveness", unit: str = "PT") -> MagicMock:
    m = MagicMock()
    m.indicator_metadata = {"name": name, "unit_measure": unit, "measurement_unit": unit}
    return m


# ---------------------------------------------------------------------------
# Spec extraction helpers
# ---------------------------------------------------------------------------

def _latest_spec() -> dict:
    """Return the most recently written spec from static/viz_specs/."""
    candidates = list(Path("static/viz_specs").glob("*.json"))
    assert candidates, "No Vega-Lite spec found in static/viz_specs/"
    return json.loads(max(candidates, key=lambda p: p.stat().st_mtime).read_text())


def _collect_values(spec: dict) -> list[dict]:
    """Recursively collect all data rows from a Vega-Lite spec."""
    rows: list[dict] = []

    def _walk(obj):
        if isinstance(obj, dict):
            if "values" in obj and isinstance(obj["values"], list):
                rows.extend(r for r in obj["values"] if isinstance(r, dict))
            if "datasets" in obj and isinstance(obj["datasets"], dict):
                for ds in obj["datasets"].values():
                    if isinstance(ds, list):
                        rows.extend(r for r in ds if isinstance(r, dict))
            for v in obj.values():
                _walk(v)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(spec)
    return rows


# ---------------------------------------------------------------------------
# Shared patch stack for get_viz_spec tests
# ---------------------------------------------------------------------------

def _viz_patches(api_rows: list[dict], meta: MagicMock | None = None, country_map: dict | None = None):
    """Return a context-manager stack that fully isolates get_viz_spec from network."""
    if meta is None:
        meta = _fake_meta()
    if country_map is None:
        country_map = {"GEO": "Georgia", "KEN": "Kenya"}

    # _fetch_data_internal is called with a URL and returns a DataFrame.
    fake_df = pd.DataFrame(api_rows)
    fake_df.columns = [c.lower() for c in fake_df.columns]

    from contextlib import asynccontextmanager
    from unittest.mock import patch

    @asynccontextmanager
    async def _stack():
        with (
            patch(
                "data360.visualization._fetch_data_internal",
                new_callable=AsyncMock,
                return_value=fake_df,
            ),
            patch("data360.api.get_metadata", new_callable=AsyncMock, return_value=meta),
            patch(
                "data360.api.get_data_api_url",
                new_callable=AsyncMock,
                return_value="https://fake-api/data?DATABASE_ID=WB_WGI&INDICATOR=GOV_WGI_GE&REF_AREA=GEO",
            ),
            patch(
                "data360.providers.get_codelist_mapping",
                new_callable=AsyncMock,
                return_value=country_map,
            ),
        ):
            yield

    return _stack()


# ---------------------------------------------------------------------------
# Tests: get_viz_spec full pipeline
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_viz_spec_comp_breakdown_uses_resolved_labels():
    """comp_breakdown_1 values in the spec must be human labels, not raw codes."""
    from data360.visualization import get_viz_spec

    async with _viz_patches(_make_wgi_rows("GEO")):
        result = await get_viz_spec(
            database_id="WB_WGI",
            indicator_id="GOV_WGI_GE",
            country_code="GEO",
        )

    assert "url" in result, f"get_viz_spec returned error: {result}"
    spec = _latest_spec()
    rows = _collect_values(spec)
    assert rows, "Spec has no data values"

    breakdown_vals = {r.get("comp_breakdown_1") for r in rows if "comp_breakdown_1" in r}
    raw = set(_CODES) & breakdown_vals
    assert not raw, (
        f"Raw COMP_BREAKDOWN codes still in spec: {raw}. "
        f"Expected resolved labels like: {list(_RESOLVED['COMP_BREAKDOWN'].values())[:3]}"
    )
    assert "Governance estimate" in breakdown_vals or "Percentile rank" in breakdown_vals, (
        f"No resolved label found. Got: {breakdown_vals}"
    )


@pytest.mark.asyncio
async def test_get_viz_spec_country_names_resolved():
    """country column must contain 'Georgia', not 'GEO'."""
    from data360.visualization import get_viz_spec

    single_rows = [r for r in _make_wgi_rows("GEO") if r["COMP_BREAKDOWN_1"] == "WGI_EST"]
    async with _viz_patches(single_rows):
        result = await get_viz_spec(
            database_id="WB_WGI",
            indicator_id="GOV_WGI_GE",
            country_code="GEO",
            disaggregation_filters={"COMP_BREAKDOWN_1": "WGI_EST"},
        )

    assert "url" in result, f"get_viz_spec returned error: {result}"
    spec = _latest_spec()
    rows = _collect_values(spec)
    countries = {r.get("country") for r in rows if "country" in r}
    assert "GEO" not in countries, f"Raw code 'GEO' still in spec. countries={countries}"
    assert "Georgia" in countries, f"'Georgia' not resolved. countries={countries}"


@pytest.mark.asyncio
async def test_get_viz_spec_sex_resolved():
    """SEX dimension values must be 'Female'/'Male', not 'F'/'M'."""
    from data360.visualization import get_viz_spec

    async with _viz_patches(_make_sex_rows("GEO")):
        result = await get_viz_spec(
            database_id="WB_TEST",
            indicator_id="TEST_IND",
            country_code="GEO",
        )

    assert "url" in result, f"get_viz_spec returned error: {result}"
    spec = _latest_spec()
    data_rows = _collect_values(spec)
    sex_vals = {r.get("sex") for r in data_rows if "sex" in r}
    assert "F" not in sex_vals, f"Raw 'F' still in spec sex column: {sex_vals}"
    assert "M" not in sex_vals, f"Raw 'M' still in spec sex column: {sex_vals}"
    assert "Female" in sex_vals or "Male" in sex_vals, (
        f"Expected 'Female'/'Male', got: {sex_vals}"
    )


@pytest.mark.asyncio
async def test_get_viz_spec_unit_label_resolved_in_title():
    """Chart title/subtitle must contain 'Percent' from UNIT_MEASURE='PT' resolution."""
    from data360.visualization import get_viz_spec

    single_rows = [r for r in _make_wgi_rows("GEO") if r["COMP_BREAKDOWN_1"] == "WGI_EST"]
    async with _viz_patches(single_rows, meta=_fake_meta(unit="PT")):
        result = await get_viz_spec(
            database_id="WB_WGI",
            indicator_id="GOV_WGI_GE",
            country_code="GEO",
            disaggregation_filters={"COMP_BREAKDOWN_1": "WGI_EST"},
        )

    assert "url" in result, f"get_viz_spec returned error: {result}"
    spec = _latest_spec()
    title_text = json.dumps(spec.get("title", ""), ensure_ascii=False)
    assert "Percent" in title_text, (
        f"Expected 'Percent' from UNIT_MEASURE resolution in title, got: {title_text[:300]}"
    )


@pytest.mark.asyncio
async def test_get_viz_spec_passes_percent_token_to_dispatch():
    from data360 import viz_config
    from data360.visualization import get_viz_spec

    single_rows = [r for r in _make_wgi_rows("GEO") if r["COMP_BREAKDOWN_1"] == "WGI_EST"]
    async with _viz_patches(single_rows, meta=_fake_meta(unit="PT")):
        with patch("data360.viz_config.dispatch_spec", wraps=viz_config.dispatch_spec) as mock_dispatch:
            result = await get_viz_spec(
                database_id="WB_WGI",
                indicator_id="GOV_WGI_GE",
                country_code="GEO",
                disaggregation_filters={"COMP_BREAKDOWN_1": "WGI_EST"},
            )

    assert "url" in result, f"get_viz_spec returned error: {result}"
    assert mock_dispatch.call_args.kwargs["unit_measure"] == "%"


@pytest.mark.asyncio
async def test_get_multi_indicator_viz_spec_passes_usd_token_to_dispatch():
    from data360 import viz_config
    from data360.visualization import get_multi_indicator_viz_spec

    df1 = pd.DataFrame([
        {"time_period": "2020-01-01", "ref_area": "GEO", "obs_value": "1.1", "unit_measure": "USD"},
        {"time_period": "2021-01-01", "ref_area": "GEO", "obs_value": "1.2", "unit_measure": "USD"},
    ])
    df2 = pd.DataFrame([
        {"time_period": "2020-01-01", "ref_area": "GEO", "obs_value": "2.1", "unit_measure": "USD"},
        {"time_period": "2021-01-01", "ref_area": "GEO", "obs_value": "2.2", "unit_measure": "USD"},
    ])

    with (
        patch(
            "data360.visualization._fetch_single_indicator",
            new_callable=AsyncMock,
            side_effect=[(df1, "Series A", "USD"), (df2, "Series B", "USD")],
        ),
        patch(
            "data360.providers.get_codelist_mapping",
            new_callable=AsyncMock,
            return_value={"GEO": "Georgia"},
        ),
        patch(
            "data360.visualization.get_database_mapping",
            new_callable=AsyncMock,
            return_value={},
        ),
        patch(
            "data360.visualization.save_specs_to_static",
            return_value="http://localhost/spec.json",
        ),
        patch("data360.viz_config.dispatch_spec", wraps=viz_config.dispatch_spec) as mock_dispatch,
    ):
        result = await get_multi_indicator_viz_spec(
            indicator_ids=[
                {"database_id": "WB_WDI", "indicator_id": "IND_A"},
                {"database_id": "WB_WDI", "indicator_id": "IND_B"},
            ],
            country_code="GEO",
        )

    assert result.get("error") is None, f"get_multi_indicator_viz_spec returned error: {result}"
    assert mock_dispatch.called, f"dispatch_spec was not called. Result: {result}"
    assert mock_dispatch.call_args.kwargs["unit_measure"] == "USD"


# ---------------------------------------------------------------------------
# Direct DataFrame pipeline test — fast, no file I/O, no network
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_full_resolution_pipeline_on_dataframe():
    """End-to-end: raw DataFrame → _map_country_codes + _map_dimension_codes → no raw codes."""
    from data360.visualization import _map_country_codes, _map_dimension_codes

    df = pd.DataFrame({
        "year": list(_YEARS) * 4,
        "value": [1.0] * 20,
        "country": ["GEO"] * 20,
        "comp_breakdown_1": (["WGI_EST"] * 5 + ["WGI_SC"] * 5) * 2,
        "sex": ["F"] * 10 + ["M"] * 10,
    })

    with patch(
        "data360.providers.get_codelist_mapping",
        new_callable=AsyncMock,
        return_value={"GEO": "Georgia", "KEN": "Kenya"},
    ):
        df = await _map_country_codes(df)
        df = await _map_dimension_codes(df)

    assert "GEO" not in df["country"].values
    assert "Georgia" in df["country"].values

    breakdown_vals = set(df["comp_breakdown_1"].unique())
    assert not (breakdown_vals & {"WGI_EST", "WGI_SC"}), f"Raw codes not resolved: {breakdown_vals}"
    assert "Governance estimate" in breakdown_vals
    assert "Percentile rank" in breakdown_vals

    sex_vals = set(df["sex"].unique())
    assert "F" not in sex_vals
    assert "M" not in sex_vals
    assert "Female" in sex_vals
    assert "Male" in sex_vals
