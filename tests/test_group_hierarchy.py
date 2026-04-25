"""Tests for GroupHierarchyManager, alias matching, and expand_country_group."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from data360.providers import (
    _GROUP_ALIASES,
    CodelistManager,
    GroupHierarchyManager,
    expand_country_group,
    find_codelist_value,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_GROUPS = {
    # SAS reflects the actual FMR H_REF_AREA_GROUPS v38.0 membership.
    # AFG and PAK are NOT in SAS; they are in MEA-family groups.
    "SAS": {"name": "South Asia", "type": "REGION", "countries": ["BGD", "BTN", "IND", "LKA", "MDV", "NPL"]},
    "LIC": {"name": "Low income", "type": "INCOME", "countries": ["AFG", "BDI", "BFA", "CAF", "COD"]},
    "SSF": {"name": "Sub-Saharan Africa", "type": "REGION", "countries": ["AGO", "BDI", "BEN", "BFA", "BWA", "CAF"]},
    "FCS": {"name": "Fragile and conflict affected situations", "type": "OTHER", "countries": ["AFG", "BDI", "CAF", "COD"]},
    "IDA": {"name": "IDA total", "type": "LENDING", "countries": ["AFG", "BGD", "BDI"]},
    "9AF": {"name": "UN M49 Africa", "type": "REGION_UN", "countries": ["AGO", "BDI", "BEN"]},
    "002": {"name": "Africa", "type": "CONTINENT", "countries": ["AGO", "BDI", "BEN", "BFA"]},
}

SAMPLE_DATA = {
    "_meta": {
        "source": "FMR H_REF_AREA_GROUPS v38.0 + CL_REF_GROUPINGS",
        "built_at": "2026-04-22",
        "hierarchy_version": "38.0",
        "total_groups": 7,
        "total_countries": 14,
        "group_types": ["CONTINENT", "INCOME", "LENDING", "OTHER", "REGION", "REGION_UN"],
    },
    "groups": SAMPLE_GROUPS,
    # all_countries is the union of all countries across all groups.
    # AFG appears via LIC/FCS/IDA; BGD via IDA; SAS no longer contributes AFG or PAK.
    "all_countries": sorted({"BGD", "BTN", "IND", "LKA", "MDV", "NPL",
                              "AFG", "BDI", "BFA", "CAF", "COD", "AGO", "BEN", "BWA"}),
}


@pytest.fixture()
def tmp_data_file(tmp_path: Path) -> Path:
    """Write sample data to a temp file and return its path."""
    p = tmp_path / "ref_area_groups.json"
    p.write_text(json.dumps(SAMPLE_DATA), encoding="utf-8")
    return p


@pytest.fixture()
def manager(tmp_data_file: Path) -> GroupHierarchyManager:
    """Fresh GroupHierarchyManager pointing at sample data."""
    m = GroupHierarchyManager()
    m._DATA_FILE = tmp_data_file  # Override to point at test fixture
    return m


# ---------------------------------------------------------------------------
# GroupHierarchyManager -- basic API
# ---------------------------------------------------------------------------


class TestGroupHierarchyManager:
    def test_is_group_known_region(self, manager):
        assert manager.is_group("SAS") is True

    def test_is_group_known_income(self, manager):
        assert manager.is_group("LIC") is True

    def test_is_group_known_lending(self, manager):
        assert manager.is_group("IDA") is True

    def test_is_group_known_other(self, manager):
        assert manager.is_group("FCS") is True

    def test_is_group_known_region_un(self, manager):
        assert manager.is_group("9AF") is True

    def test_is_group_known_continent(self, manager):
        assert manager.is_group("002") is True

    def test_is_group_unknown(self, manager):
        assert manager.is_group("KEN") is False

    def test_is_group_case_insensitive(self, manager):
        assert manager.is_group("sas") is True
        assert manager.is_group("Sas") is True

    def test_is_country_individual(self, manager):
        # IND is in SAS countries but not itself a group
        assert manager.is_country("IND") is True

    def test_is_country_group_code(self, manager):
        # SAS is a group, not an individual country
        assert manager.is_country("SAS") is False

    def test_expand_group_sas(self, manager):
        countries = manager.expand_group("SAS")
        # SAS in FMR v38.0 has 6 members; AFG and PAK are in MEA-family groups, not SAS.
        assert sorted(countries) == ["BGD", "BTN", "IND", "LKA", "MDV", "NPL"]

    def test_expand_group_lic(self, manager):
        # LIC has 5 countries in the sample fixture
        lic_countries = SAMPLE_GROUPS["LIC"]["countries"]
        countries = manager.expand_group("LIC")
        assert "AFG" in countries
        assert len(countries) == len(lic_countries)

    def test_expand_group_unknown(self, manager):
        assert manager.expand_group("INVALID") == []

    def test_expand_group_case_insensitive(self, manager):
        assert manager.expand_group("sas") == manager.expand_group("SAS")

    def test_get_group_type_region(self, manager):
        assert manager.get_group_type("SAS") == "REGION"

    def test_get_group_type_income(self, manager):
        assert manager.get_group_type("LIC") == "INCOME"

    def test_get_group_type_lending(self, manager):
        assert manager.get_group_type("IDA") == "LENDING"

    def test_get_group_type_other(self, manager):
        assert manager.get_group_type("FCS") == "OTHER"

    def test_get_group_type_region_un(self, manager):
        assert manager.get_group_type("9AF") == "REGION_UN"

    def test_get_group_type_continent(self, manager):
        assert manager.get_group_type("002") == "CONTINENT"

    def test_get_group_type_unknown(self, manager):
        assert manager.get_group_type("KEN") is None

    def test_get_group_info(self, manager):
        info = manager.get_group_info("SAS")
        assert info is not None
        assert info["name"] == "South Asia"
        assert info["type"] == "REGION"
        assert "IND" in info["countries"]

    def test_get_group_info_unknown(self, manager):
        assert manager.get_group_info("NOTREAL") is None

    def test_get_meta(self, manager):
        meta = manager.get_meta()
        assert meta["hierarchy_version"] == "38.0"
        assert "source" in meta

    def test_search_groups_by_name(self, manager):
        results = manager.search_groups("South")
        ids = [r["id"] for r in results]
        assert "SAS" in ids

    def test_search_groups_by_id(self, manager):
        results = manager.search_groups("LIC")
        assert any(r["id"] == "LIC" for r in results)

    def test_search_groups_limit(self, manager):
        limit = 2
        results = manager.search_groups("a", limit=limit)
        assert len(results) <= limit

    def test_search_groups_no_match(self, manager):
        results = manager.search_groups("xyzzznotreal")
        assert results == []

    def test_include_types_filter(self, tmp_data_file):
        m = GroupHierarchyManager(include_types={"INCOME"})
        m._DATA_FILE = tmp_data_file
        assert m.is_group("LIC") is True
        assert m.is_group("SAS") is False  # REGION filtered out
        assert m.is_group("FCS") is False  # OTHER filtered out

    def test_missing_data_file_graceful(self, tmp_path):
        m = GroupHierarchyManager()
        m._DATA_FILE = tmp_path / "does_not_exist.json"
        # Should not raise; loads empty state
        assert m.is_group("SAS") is False
        assert m.expand_group("SAS") == []


# ---------------------------------------------------------------------------
# Alias map
# ---------------------------------------------------------------------------


class TestGroupAliases:
    """Verify the alias map only covers phrases where fuzzy search genuinely fails."""

    @pytest.mark.parametrize("phrase,expected_code", [
        # Category 1: "and" vs "&" variants
        ("east asia and pacific", "EAS"),
        ("europe and central asia", "ECS"),
        ("latin america and the caribbean", "LCN"),
        ("middle east and north africa", "MEA"),
        ("middle east & north africa", "MEA"),
        ("low and middle income", "LMY"),
        # Category 2: abbreviation not in official name
        ("mena", "MEA"),
        # Category 3: shorthands not in official name
        ("fragile states", "FCS"),
        ("small island states", "SST"),
        ("eastern africa", "AFE"),
        ("western africa", "AFW"),
        # Category 4: semantic synonym
        ("lower income", "LIC"),
    ])
    def test_alias_exists(self, phrase, expected_code):
        assert _GROUP_ALIASES[phrase] == expected_code

    def test_alias_map_is_minimal(self):
        """The alias map must not grow without justification.

        Phrases like 'south asia', 'low income countries', 'sub-saharan africa'
        are already handled by the fuzzy/substring search in CodelistManager and
        do NOT belong in this map. If a new entry is added, a comment must explain
        why fuzzy search fails for it.
        """
        # Phrases that fuzzy handles natively should never appear in the alias map.
        fuzzy_native_phrases = [
            "south asia", "south asian", "south asian countries",
            "sub-saharan africa", "sub-saharan",
            "low income", "low income countries",
            "high income", "high income countries",
            "lower middle income", "upper middle income",
            "middle income", "middle income countries",
            "least developed", "least developed countries",
            "small states", "oecd", "oecd members",
            "european union", "eu", "arab world",
            "latin america", "north america",
            "ida", "ibrd",
            "fragile and conflict", "fragile and conflict affected",
        ]
        for phrase in fuzzy_native_phrases:
            assert phrase not in _GROUP_ALIASES, (
                f"'{phrase}' was re-added to _GROUP_ALIASES but the fuzzy search "
                f"already handles it. Remove it unless you can prove fuzzy fails."
            )

    def test_all_alias_values_are_uppercase(self):
        for phrase, code in _GROUP_ALIASES.items():
            assert code == code.upper(), f"Alias '{phrase}' has non-uppercase code '{code}'"

    def test_all_alias_keys_are_lowercase(self):
        for phrase in _GROUP_ALIASES:
            assert phrase == phrase.lower(), f"Alias key '{phrase}' is not lowercase"


# ---------------------------------------------------------------------------
# find_codelist_value -- alias path for REF_AREA
# ---------------------------------------------------------------------------


class TestFindCodelistValueAliases:
    """Test alias shortcut path in find_codelist_value for REF_AREA."""

    @pytest.mark.asyncio
    async def test_alias_hit_returns_group_metadata(self, tmp_data_file):
        # Use 'fragile states' -> FCS: a genuine alias (fuzzy would not catch it
        # because 'states' does not appear in 'Fragile and conflict affected situations').
        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                results = await find_codelist_value("REF_AREA", "fragile states")

        assert len(results) == 1
        r = results[0]
        assert r["id"] == "FCS"
        assert r["is_group"] is True
        assert r["group_type"] == "OTHER"
        assert r["member_count"] == len(SAMPLE_GROUPS["FCS"]["countries"])
        assert "data360_expand_country_group" in r["note"]

    @pytest.mark.asyncio
    async def test_alias_case_insensitive(self, tmp_data_file):
        # 'Mena' and 'MENA' must resolve to MEA via the alias map.
        # MEA is not in the fixture so the group_info lookup returns None;
        # that is correct — we only assert the alias key normalisation here.
        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                results_mixed = await find_codelist_value("REF_AREA", "Fragile States")
                results_upper = await find_codelist_value("REF_AREA", "FRAGILE STATES")

        assert results_mixed[0]["id"] == "FCS"
        assert results_upper[0]["id"] == "FCS"


# ---------------------------------------------------------------------------
# expand_country_group function
# ---------------------------------------------------------------------------


class TestExpandCountryGroup:
    @pytest.mark.asyncio
    async def test_expand_sas(self, tmp_data_file):
        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                with patch("data360.providers.get_codelist_manager") as mock_cl:
                    mock_cl.return_value.get_codelist_mapping = AsyncMock(return_value={
                        "IND": "India", "BGD": "Bangladesh",
                        "BTN": "Bhutan", "LKA": "Sri Lanka",
                        "MDV": "Maldives", "NPL": "Nepal",
                    })
                    result = await expand_country_group("SAS")

        assert result["group_code"] == "SAS"
        assert result["group_name"] == "South Asia"
        assert result["group_type"] == "REGION"
        sas_count = len(SAMPLE_GROUPS["SAS"]["countries"])  # 6
        assert result["count"] == sas_count
        assert "IND" in result["country_codes"]
        # AFG and PAK are NOT members of SAS in the FMR hierarchy.
        assert "AFG" not in result["country_codes"]
        assert "PAK" not in result["country_codes"]
        assert result["hierarchy_version"] == "38.0"
        country_codes_list = result["country_codes"].split(",")
        assert len(country_codes_list) == sas_count

    @pytest.mark.asyncio
    async def test_expand_lic(self, tmp_data_file):
        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                with patch("data360.providers.get_codelist_manager") as mock_cl:
                    mock_cl.return_value.get_codelist_mapping = AsyncMock(return_value={})
                    result = await expand_country_group("LIC")

        assert result["group_code"] == "LIC"
        assert result["group_type"] == "INCOME"
        assert result["count"] == len(SAMPLE_GROUPS["LIC"]["countries"])

    @pytest.mark.asyncio
    async def test_expand_case_insensitive(self, tmp_data_file):
        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                with patch("data360.providers.get_codelist_manager") as mock_cl:
                    mock_cl.return_value.get_codelist_mapping = AsyncMock(return_value={})
                    result_lower = await expand_country_group("sas")
                    result_upper = await expand_country_group("SAS")

        assert result_lower["group_code"] == result_upper["group_code"] == "SAS"

    @pytest.mark.asyncio
    async def test_expand_via_alias(self, tmp_data_file):
        """expand_country_group resolves genuine aliases as fallback.

        Uses 'fragile states' -> FCS: a case where fuzzy search would not
        find FCS because 'states' is not in the official name.
        """
        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                with patch("data360.providers.get_codelist_manager") as mock_cl:
                    mock_cl.return_value.get_codelist_mapping = AsyncMock(return_value={})
                    result = await expand_country_group("fragile states")

        assert result["group_code"] == "FCS"

    @pytest.mark.asyncio
    async def test_expand_unknown_code_returns_error(self, tmp_data_file):
        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                result = await expand_country_group("NOTREAL")

        assert "error" in result
        assert "NOTREAL" in result["error"]

    @pytest.mark.asyncio
    async def test_expand_continent(self, tmp_data_file):
        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                with patch("data360.providers.get_codelist_manager") as mock_cl:
                    mock_cl.return_value.get_codelist_mapping = AsyncMock(return_value={})
                    result = await expand_country_group("002")

        assert result["group_code"] == "002"
        assert result["group_type"] == "CONTINENT"

    @pytest.mark.asyncio
    async def test_expand_codelist_failure_graceful(self, tmp_data_file):
        """If REF_AREA codelist fetch fails, codes are still returned (names = codes)."""
        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                with patch("data360.providers.get_codelist_manager") as mock_cl:
                    mock_cl.return_value.get_codelist_mapping = AsyncMock(
                        side_effect=Exception("API unavailable")
                    )
                    result = await expand_country_group("SAS")

        # Should still succeed; names fall back to code strings
        assert result["group_code"] == "SAS"
        assert result["count"] == len(SAMPLE_GROUPS["SAS"]["countries"])
        assert all(c["code"] == c["name"] for c in result["countries"])


# ---------------------------------------------------------------------------
# REF_AREA search enrichment (via CodelistManager._search_global)
# ---------------------------------------------------------------------------


class TestRefAreaEnrichment:
    """Test that _search_global enriches REF_AREA results with group metadata."""

    @pytest.mark.asyncio
    async def test_search_returns_is_group_true_for_group(self, tmp_data_file):
        """When the Data360 codelist returns SAS, is_group=True should be added."""
        cm = CodelistManager()
        # Seed cache with SAS entry
        cm._cache["REF_AREA"] = [{"Id": "SAS", "Name": "South Asia"}]
        cm._loaded.add("REF_AREA")

        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                results = cm._search_global("REF_AREA", "sas", 5)

        assert results[0]["id"] == "SAS"
        assert results[0]["is_group"] is True
        assert results[0]["group_type"] == "REGION"
        assert results[0]["member_count"] == len(SAMPLE_GROUPS["SAS"]["countries"])

    @pytest.mark.asyncio
    async def test_search_returns_is_group_false_for_country(self, tmp_data_file):
        """When the Data360 codelist returns KEN, is_group=False should be added."""
        cm = CodelistManager()
        cm._cache["REF_AREA"] = [{"Id": "KEN", "Name": "Kenya"}]
        cm._loaded.add("REF_AREA")

        with patch("data360.providers._group_hierarchy_manager", None):
            ghm = GroupHierarchyManager()
            ghm._DATA_FILE = tmp_data_file
            with patch("data360.providers.get_group_hierarchy_manager", return_value=ghm):
                results = cm._search_global("REF_AREA", "ken", 5)

        assert results[0]["id"] == "KEN"
        assert results[0]["is_group"] is False

    def test_non_ref_area_not_enriched(self, tmp_data_file):
        """UNIT_MEASURE searches should not get is_group metadata."""
        cm = CodelistManager()
        cm._cache["UNIT_MEASURE"] = [{"Id": "USD", "Name": "US Dollar"}]
        cm._loaded.add("UNIT_MEASURE")

        results = cm._search_global("UNIT_MEASURE", "usd", 5)
        assert "is_group" not in results[0]


# ---------------------------------------------------------------------------
# Data integrity: alias map and shipped data file are consistent
# ---------------------------------------------------------------------------


class TestDataIntegrity:
    """Validate that the alias map and shipped ref_area_groups.json are consistent."""

    def test_all_alias_values_exist_in_shipped_data(self):
        """Every code in _GROUP_ALIASES must exist as a group in ref_area_groups.json.

        This catches the case where an alias points to a code that was removed or
        renamed in a new hierarchy version.
        """
        from data360.providers import GroupHierarchyManager

        # Use the real shipped data file, not the test fixture.
        ghm = GroupHierarchyManager()
        missing = [
            (phrase, code)
            for phrase, code in _GROUP_ALIASES.items()
            if not ghm.is_group(code)
        ]
        assert missing == [], (
            f"These alias entries point to unknown group codes in ref_area_groups.json: "
            f"{missing}. Either fix the alias or regenerate the data file."
        )

    def test_shipped_data_sas_excludes_afg_and_pak(self):
        """Regression: SAS in the shipped data must NOT include AFG or PAK.

        AFG and PAK belong to MEA-family groups in the FMR hierarchy v38.0.
        This test ensures the build script and shipped file remain grounded
        to the source and do not include erroneous entries.
        """
        from data360.providers import GroupHierarchyManager

        ghm = GroupHierarchyManager()
        sas_countries = ghm.expand_group("SAS")
        assert "AFG" not in sas_countries, "AFG should not be in SAS per FMR v38.0"
        assert "PAK" not in sas_countries, "PAK should not be in SAS per FMR v38.0"
        assert "IND" in sas_countries, "IND must be in SAS"
        assert "BGD" in sas_countries, "BGD must be in SAS"
