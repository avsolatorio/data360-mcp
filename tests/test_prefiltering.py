"""Tests for get_data payload prefiltering logic."""

import re

import pytest
import pytest_httpx
from data360.api import _strip_data_row, get_data


class TestStripDataRow:
    """Tests for _strip_data_row helper function."""

    def _make_full_row(self, **overrides):
        """Build a full 24-field data row with optional overrides."""
        row = {
            "OBS_VALUE": "100.5",
            "TIME_PERIOD": "2023",
            "REF_AREA": "KEN",
            "UNIT_MEASURE": "PT",
            "claim_id": "abc12345",
            "TIME_FORMAT": "P1Y",
            "UNIT_MULT": 0,
            "COMMENT_OBS": None,
            "OBS_STATUS": "A",
            "OBS_CONF": "PU",
            "AGG_METHOD": "_Z",
            "DECIMALS": "2",
            "COMMENT_TS": "GDP per capita",
            "DATA_SOURCE": "WB_WDI",
            "LATEST_DATA": False,
            "DATABASE_ID": "WB_WDI",
            "INDICATOR": "WB_WDI_NY_GDP_PCAP_KD",
            "SEX": "_T",
            "AGE": "_T",
            "URBANISATION": "_T",
            "COMP_BREAKDOWN_1": "_Z",
            "COMP_BREAKDOWN_2": "_Z",
            "COMP_BREAKDOWN_3": "_Z",
            "FREQ": "A",
            "UNIT_TYPE": None,
        }
        row.update(overrides)
        return row

    def test_core_fields_only(self):
        """Test that trivial disaggregation returns only 5 core fields."""
        EXPECTED_FIELD_COUNT = 5
        row = self._make_full_row()
        result = _strip_data_row(row)
        assert len(result) == EXPECTED_FIELD_COUNT
        assert set(result.keys()) == {
            "OBS_VALUE", "TIME_PERIOD", "REF_AREA", "UNIT_MEASURE", "claim_id",
        }

    def test_preserves_sex(self):
        """Test that SEX=F is retained."""
        row = self._make_full_row(SEX="F")
        result = _strip_data_row(row)
        assert result["SEX"] == "F"

    def test_preserves_age(self):
        """Test that AGE=Y15T24 is retained."""
        row = self._make_full_row(AGE="Y15T24")
        result = _strip_data_row(row)
        assert result["AGE"] == "Y15T24"

    def test_preserves_urbanisation(self):
        """Test that URBANISATION=URB is retained."""
        row = self._make_full_row(URBANISATION="URB")
        result = _strip_data_row(row)
        assert result["URBANISATION"] == "URB"

    def test_preserves_comp_breakdown_ipc(self):
        """Test that IPC phase data is retained in COMP_BREAKDOWN_1/2."""
        row = self._make_full_row(
            COMP_BREAKDOWN_1="IPC_IPC_CURRENT",
            COMP_BREAKDOWN_2="IPC_IPC_PHASE1",
        )
        result = _strip_data_row(row)
        assert result["COMP_BREAKDOWN_1"] == "IPC_IPC_CURRENT"
        assert result["COMP_BREAKDOWN_2"] == "IPC_IPC_PHASE1"

    def test_preserves_comp_breakdown_oecd(self):
        """Test that OECD indicator type is retained."""
        row = self._make_full_row(
            COMP_BREAKDOWN_1="OECD_BROADBAND_INDICATOR_TYPE_FBB"
        )
        result = _strip_data_row(row)
        assert result["COMP_BREAKDOWN_1"] == "OECD_BROADBAND_INDICATOR_TYPE_FBB"

    def test_strips_all_boilerplate(self):
        """Test that all 14 boilerplate fields are absent from output."""
        row = self._make_full_row()
        result = _strip_data_row(row)
        boilerplate = {
            "TIME_FORMAT", "UNIT_MULT", "COMMENT_OBS", "OBS_STATUS", "OBS_CONF",
            "AGG_METHOD", "DECIMALS", "COMMENT_TS", "DATA_SOURCE", "LATEST_DATA",
            "DATABASE_ID", "INDICATOR", "FREQ", "UNIT_TYPE", "COMP_BREAKDOWN_3",
        }
        assert not boilerplate & set(result.keys())

    def test_trivial_t_stripped(self):
        """Test that _T values in conditional fields are stripped."""
        row = self._make_full_row(SEX="_T", AGE="_T", URBANISATION="_T")
        result = _strip_data_row(row)
        assert "SEX" not in result
        assert "AGE" not in result
        assert "URBANISATION" not in result

    def test_trivial_z_stripped(self):
        """Test that _Z values in conditional fields are stripped."""
        row = self._make_full_row(COMP_BREAKDOWN_1="_Z", COMP_BREAKDOWN_2="_Z")
        result = _strip_data_row(row)
        assert "COMP_BREAKDOWN_1" not in result
        assert "COMP_BREAKDOWN_2" not in result


class TestGetDataPrefiltering:
    """Integration tests for get_data payload prefiltering."""

    @pytest.mark.asyncio
    async def test_get_data_strips_boilerplate(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test that get_data strips boilerplate fields from response."""
        mock_data_response = {
            "value": [{
                "OBS_VALUE": "100", "TIME_PERIOD": "2023", "REF_AREA": "KEN",
                "UNIT_MEASURE": "PT", "TIME_FORMAT": "P1Y", "UNIT_MULT": 0,
                "COMMENT_OBS": None, "OBS_STATUS": "A", "OBS_CONF": "PU",
                "AGG_METHOD": "_Z", "DECIMALS": "2", "COMMENT_TS": None,
                "DATA_SOURCE": "WB_WDI", "LATEST_DATA": True,
                "DATABASE_ID": "WB_WDI", "INDICATOR": "WB_WDI_SP_POP_TOTL",
                "SEX": "_T", "AGE": "_T", "URBANISATION": "_T",
                "COMP_BREAKDOWN_1": "_Z", "COMP_BREAKDOWN_2": "_Z",
                "COMP_BREAKDOWN_3": "_Z", "FREQ": "A", "UNIT_TYPE": None,
            }],
        }
        httpx_mock.add_response(
            method="POST", url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_SP_POP_TOTL"}}]},
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/disaggregation.*"),
            json=[{"field_name": "REF_AREA", "field_value": ["KEN"]}],
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/data\\?.*"),
            json=mock_data_response,
        )
        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")
        assert result.data is not None
        assert len(result.data) == 1
        row = result.data[0]
        assert "OBS_VALUE" in row
        assert "claim_id" in row
        assert "DATABASE_ID" not in row
        assert "INDICATOR" not in row
        assert "SEX" not in row

    @pytest.mark.asyncio
    async def test_get_data_keeps_disaggregation(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test that non-trivial disaggregation fields are retained."""
        mock_data_response = {
            "value": [{
                "OBS_VALUE": "57.5", "TIME_PERIOD": "2024", "REF_AREA": "USA",
                "UNIT_MEASURE": "PT", "SEX": "F", "AGE": "_T", "URBANISATION": "_T",
                "COMP_BREAKDOWN_1": "_Z", "COMP_BREAKDOWN_2": "_Z",
                "COMP_BREAKDOWN_3": "_Z", "DATABASE_ID": "WB_HCP",
                "INDICATOR": "WB_HCP_EMP_2WAP_A", "FREQ": "A",
            }],
        }
        httpx_mock.add_response(
            method="POST", url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_HCP_EMP_2WAP_A"}}]},
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/disaggregation.*"),
            json=[
                {"field_name": "REF_AREA", "field_value": ["USA"]},
                {"field_name": "SEX", "field_value": ["_T", "F"]},
            ],
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/data\\?.*"),
            json=mock_data_response,
        )
        result = await get_data("WB_HCP", "WB_HCP_EMP_2WAP_A")
        assert result.data is not None
        row = result.data[0]
        assert row["SEX"] == "F"
        assert "AGE" not in row

    @pytest.mark.asyncio
    async def test_get_data_promotes_comment_ts(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test that COMMENT_TS is promoted to metadata."""
        mock_data_response = {
            "value": [{
                "OBS_VALUE": "3744.7", "TIME_PERIOD": "2023", "REF_AREA": "PHL",
                "UNIT_MEASURE": "USD_K_2015",
                "COMMENT_TS": "GDP per capita (constant 2015 US$)",
                "DATABASE_ID": "WB_WDI", "INDICATOR": "WB_WDI_NY_GDP_PCAP_KD",
                "SEX": "_T", "AGE": "_T", "URBANISATION": "_T",
                "COMP_BREAKDOWN_1": "_Z", "COMP_BREAKDOWN_2": "_Z",
                "COMP_BREAKDOWN_3": "_Z", "FREQ": "A",
            }],
        }
        httpx_mock.add_response(
            method="POST", url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_NY_GDP_PCAP_KD", "name": "GDP per capita"}}]},
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/disaggregation.*"),
            json=[{"field_name": "REF_AREA", "field_value": ["PHL"]}],
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/data\\?.*"),
            json=mock_data_response,
        )
        result = await get_data("WB_WDI", "WB_WDI_NY_GDP_PCAP_KD")
        assert result.metadata is not None
        assert result.metadata["indicator_description"] == "GDP per capita (constant 2015 US$)"
        assert result.data is not None
        for row in result.data:
            assert "COMMENT_TS" not in row


class TestStripDisaggregation:
    """Tests for _strip_disaggregation helper function."""

    def _make_dimensions(self, **overrides):
        """Build a typical disaggregation response with optional overrides."""
        dims = [
            {"field_name": "FREQ", "label_name": "Frequency", "field_value": ["A"]},
            {"field_name": "REF_AREA", "label_name": "Reference area",
             "field_value": ["KEN", "USA", "GBR", "FRA", "DEU", "JPN", "CHN", "IND"]},
            {"field_name": "INDICATOR", "label_name": "Indicator",
             "field_value": ["WB_WDI_NY_GDP_PCAP_KD"]},
            {"field_name": "SEX", "label_name": "Sex", "field_value": ["_T"]},
            {"field_name": "AGE", "label_name": "Age", "field_value": ["_T"]},
            {"field_name": "URBANISATION", "label_name": "Urbanisation",
             "field_value": ["_T"]},
            {"field_name": "UNIT_MEASURE", "label_name": "Unit",
             "field_value": ["USD_K_2015"]},
            {"field_name": "TIME_PERIOD", "label_name": "Time period",
             "field_value": ["2020", "2018", "2023", "2019", "2021", "2022"]},
        ]
        return dims

    def test_strips_indicator_and_freq(self):
        """Test that INDICATOR and FREQ dimensions are removed."""
        from data360.api import _strip_disaggregation

        dims = self._make_dimensions()
        result = _strip_disaggregation(dims)
        names = [d["field_name"] for d in result]
        assert "INDICATOR" not in names
        assert "FREQ" not in names

    def test_strips_single_value_t_dimensions(self):
        """Test that SEX/AGE/URBANISATION with only _T are removed."""
        from data360.api import _strip_disaggregation

        dims = self._make_dimensions()
        result = _strip_disaggregation(dims)
        names = [d["field_name"] for d in result]
        assert "SEX" not in names
        assert "AGE" not in names
        assert "URBANISATION" not in names

    def test_preserves_multi_value_dimensions(self):
        """Test that SEX with multiple values is preserved."""
        from data360.api import _strip_disaggregation

        dims = self._make_dimensions()
        # Replace SEX with multi-value
        for d in dims:
            if d["field_name"] == "SEX":
                d["field_value"] = ["_T", "F", "M"]
        result = _strip_disaggregation(dims)
        sex_dim = next((d for d in result if d["field_name"] == "SEX"), None)
        assert sex_dim is not None
        assert sex_dim["field_value"] == ["_T", "F", "M"]

    def test_sorts_time_period(self):
        """Test that TIME_PERIOD values are sorted chronologically."""
        from data360.api import _strip_disaggregation

        dims = self._make_dimensions()
        result = _strip_disaggregation(dims)
        tp = next(d for d in result if d["field_name"] == "TIME_PERIOD")
        assert tp["field_value"] == ["2018", "2019", "2020", "2021", "2022", "2023"]

    def test_summarizes_ref_area(self):
        """Test that REF_AREA is replaced with count + sorted sample."""
        from data360.api import _strip_disaggregation

        dims = self._make_dimensions()
        result = _strip_disaggregation(dims)
        ref = next(d for d in result if d["field_name"] == "REF_AREA")
        assert ref["count"] == 8
        assert len(ref["sample"]) == 5
        assert "field_value" not in ref
        # Sample should be sorted alphabetically
        assert ref["sample"] == sorted(ref["sample"])

    def test_preserves_label_name(self):
        """Test that label_name is preserved when present."""
        from data360.api import _strip_disaggregation

        dims = self._make_dimensions()
        result = _strip_disaggregation(dims)
        tp = next(d for d in result if d["field_name"] == "TIME_PERIOD")
        assert tp["label_name"] == "Time period"

    def test_preserves_unit_measure(self):
        """Test that UNIT_MEASURE is preserved (not in strip list)."""
        from data360.api import _strip_disaggregation

        dims = self._make_dimensions()
        result = _strip_disaggregation(dims)
        um = next((d for d in result if d["field_name"] == "UNIT_MEASURE"), None)
        assert um is not None
        assert um["field_value"] == ["USD_K_2015"]


    def test_ref_area_with_queried_countries(self):
        """Test that queried countries are checked against REF_AREA."""
        from data360.api import _strip_disaggregation

        dims = self._make_dimensions()
        result = _strip_disaggregation(dims, queried_countries=["KEN", "USA", "BRA"])
        ref = next(d for d in result if d["field_name"] == "REF_AREA")
        assert ref["count"] == 8
        assert ref["queried"] == {"KEN": True, "USA": True, "BRA": False}
        assert "sample" not in ref

    def test_ref_area_without_queried_countries(self):
        """Test that sample is used when no queried countries provided."""
        from data360.api import _strip_disaggregation

        dims = self._make_dimensions()
        result = _strip_disaggregation(dims, queried_countries=None)
        ref = next(d for d in result if d["field_name"] == "REF_AREA")
        assert ref["count"] == 8
        assert "sample" in ref
        assert "queried" not in ref
