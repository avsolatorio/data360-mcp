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
        """Test that trivial disaggregation returns only 6 core fields."""
        EXPECTED_FIELD_COUNT = 6
        row = self._make_full_row()
        result = _strip_data_row(row)
        assert len(result) == EXPECTED_FIELD_COUNT
        assert set(result.keys()) == {
            "OBS_VALUE", "TIME_PERIOD", "REF_AREA", "UNIT_MEASURE", "UNIT_MULT", "claim_id",
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
            "TIME_FORMAT", "COMMENT_OBS", "OBS_STATUS", "OBS_CONF",
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
            method="POST", url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": [{"field_name": "REF_AREA", "field_value": [{"code": "KEN"}]}]},
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
            method="POST", url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": [
                {"field_name": "REF_AREA", "field_value": [{"code": "USA"}]},
                {"field_name": "SEX", "field_value": [{"code": "_T"}, {"code": "F"}]},
            ]},
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
            method="POST", url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": [{"field_name": "REF_AREA", "field_value": [{"code": "PHL"}]}]},
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

    def test_empty_dimensions(self):
        """Test that empty input returns empty output."""
        from data360.api import _strip_disaggregation

        result = _strip_disaggregation([])
        assert result == []

    def test_single_country_ref_area(self):
        """Test REF_AREA with a single country still produces count + sample."""
        from data360.api import _strip_disaggregation

        dims = [{"field_name": "REF_AREA", "field_value": ["KEN"]}]
        result = _strip_disaggregation(dims)
        ref = next(d for d in result if d["field_name"] == "REF_AREA")
        assert ref["count"] == 1
        assert ref["sample"] == ["KEN"]
        assert "field_value" not in ref


class TestGetDataDisaggregationIndependence:
    """Tests confirming get_data re-fetches disaggregation independently."""

    @pytest.mark.asyncio
    async def test_get_data_does_not_consume_stripped_disaggregation(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Confirm that get_data fetches raw disaggregation via the API,
        not the stripped output from _strip_disaggregation.

        This verifies that the REF_AREA shape change (count/sample instead
        of field_value) in _strip_disaggregation does NOT break get_data's
        internal _build_disaggregation_params which reads field_value.
        """
        mock_data_response = {
            "value": [{
                "OBS_VALUE": "100", "TIME_PERIOD": "2023", "REF_AREA": "KEN",
                "UNIT_MEASURE": "PT", "SEX": "_T", "AGE": "_T",
                "URBANISATION": "_T", "COMP_BREAKDOWN_1": "_Z",
                "COMP_BREAKDOWN_2": "_Z", "COMP_BREAKDOWN_3": "_Z",
                "DATABASE_ID": "WB_WDI", "INDICATOR": "WB_WDI_SP_POP_TOTL",
                "FREQ": "A",
            }],
        }
        httpx_mock.add_response(
            method="POST", url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_WDI_SP_POP_TOTL"}}]},
        )
        httpx_mock.add_response(
            method="POST", url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": [
                {"field_name": "REF_AREA", "field_value": [{"code": "KEN"}, {"code": "USA"}, {"code": "GBR"}]},
                {"field_name": "SEX", "field_value": [{"code": "_T"}]},
            ]},
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/data\\?.*"),
            json=mock_data_response,
        )
        result = await get_data("WB_WDI", "WB_WDI_SP_POP_TOTL")
        # Should succeed without errors -- confirms get_data uses raw
        # disaggregation (with field_value) not the stripped version.
        assert result.error is None
        assert result.data is not None
        assert len(result.data) == 1


class TestUnitMeasureQualification:
    """Tests for unit measure qualification using UNIT_MULT."""

    def test_qualify_unit_name_helper(self):
        """Test _qualify_unit_name helper function directly."""
        from data360.api import _qualify_unit_name

        # Test PS (Persons/people) with UNIT_MULT=6 (million)
        assert _qualify_unit_name("Persons", 6, "PS") == "million people"
        assert _qualify_unit_name("people", 6, "PS") == "million people"
        assert _qualify_unit_name(None, 6, "PS") == "million"

        # Test other units and multipliers
        assert _qualify_unit_name("US Dollars", 6, "USD") == "million US Dollars"
        assert _qualify_unit_name("US Dollars", 3, "USD") == "thousand US Dollars"
        assert _qualify_unit_name("US Dollars", 9, "USD") == "billion US Dollars"
        assert _qualify_unit_name("US Dollars", 0, "USD") == "US Dollars"
        assert _qualify_unit_name("US Dollars", None, "USD") == "US Dollars"
        assert _qualify_unit_name("US Dollars", "invalid", "USD") == "US Dollars"

    @pytest.mark.asyncio
    async def test_get_data_qualifies_unit_measure_name(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test that get_data qualifies UNIT_MEASURE_NAME using UNIT_MULT."""
        mock_data_response = {
            "value": [{
                "OBS_VALUE": "86.0392",
                "TIME_PERIOD": "2022",
                "REF_AREA": "NGA",
                "UNIT_MEASURE": "PS",
                "UNIT_MULT": 6,
                "SEX": "_T",
                "AGE": "_T",
                "URBANISATION": "_T",
            }],
        }
        httpx_mock.add_response(
            method="POST", url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_PIP_NPOOR_IPL"}}]},
        )
        httpx_mock.add_response(
            method="POST", url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": [{"field_name": "REF_AREA", "field_value": [{"code": "NGA"}]}]},
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/data\\?.*"),
            json=mock_data_response,
        )
        result = await get_data("WB_PIP", "WB_PIP_NPOOR_IPL")
        assert result.error is None
        assert result.data is not None
        assert len(result.data) == 1
        row = result.data[0]
        # UNIT_MULT should be preserved
        assert row["UNIT_MULT"] == 6
        # UNIT_MEASURE_NAME should be qualified as "million people" instead of "Persons"
        assert row["UNIT_MEASURE_NAME"] == "million people"

    @pytest.mark.asyncio
    async def test_get_data_preserves_unmapped_unit_measure_name_without_multiplier(self, httpx_mock: pytest_httpx.HTTPXMock):
        """Test that get_data does not overwrite UNIT_MEASURE_NAME if no mapping exists and UNIT_MULT is 0."""
        mock_data_response = {
            "value": [{
                "OBS_VALUE": "86.0392",
                "TIME_PERIOD": "2022",
                "REF_AREA": "NGA",
                "UNIT_MEASURE": "XYZ",
                "UNIT_MEASURE_NAME": "Descriptive XYZ Label",
                "UNIT_MULT": 0,
                "SEX": "_T",
                "AGE": "_T",
                "URBANISATION": "_T",
            }],
        }
        httpx_mock.add_response(
            method="POST", url="https://api.test.example.com/metadata",
            json={"value": [{"series_description": {"idno": "WB_PIP_NPOOR_IPL"}}]},
        )
        httpx_mock.add_response(
            method="POST", url=re.compile(r".*/portal/v1/dimensions.*"),
            json={"dimensions": [{"field_name": "REF_AREA", "field_value": [{"code": "NGA"}]}]},
        )
        httpx_mock.add_response(
            method="GET", url=re.compile(r".*/data\\?.*"),
            json=mock_data_response,
        )
        result = await get_data("WB_PIP", "WB_PIP_NPOOR_IPL")
        assert result.error is None
        assert result.data is not None
        assert len(result.data) == 1
        row = result.data[0]
        # UNIT_MEASURE_NAME should be preserved as "Descriptive XYZ Label" instead of being overwritten with raw code "XYZ"
        assert row["UNIT_MEASURE_NAME"] == "Descriptive XYZ Label"
