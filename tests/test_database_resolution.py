import pytest
from unittest.mock import patch
from data360.providers import DatabaseManager

class TestDatabaseResolution:
    @pytest.mark.asyncio
    async def test_resolve_database_id_success(self):
        db_mgr = DatabaseManager()
        # Seed cache manually for deterministic testing
        db_mgr._cache = {
            "WB_WDI": "World Development Indicators",
            "WB_GS": "Gender Statistics",
            "WB_HNP": "Health Nutrition and Population Statistics"
        }

        # 1. Exact ID match (case-insensitive)
        assert db_mgr.resolve_database_id("wb_wdi") == "WB_WDI"
        # 2. Exact Name match (case-insensitive)
        assert db_mgr.resolve_database_id("world development indicators") == "WB_WDI"
        # 3. Substring ID match
        assert db_mgr.resolve_database_id("WDI") == "WB_WDI"
        # 4. Substring Name match
        assert db_mgr.resolve_database_id("Gender") == "WB_GS"

    @pytest.mark.asyncio
    async def test_resolve_database_id_none_or_unresolved(self):
        db_mgr = DatabaseManager()
        db_mgr._cache = {
            "WB_WDI": "World Development Indicators"
        }
        assert db_mgr.resolve_database_id(None) is None
        assert db_mgr.resolve_database_id("") is None
        assert db_mgr.resolve_database_id("Nonexistent Database") is None

    @pytest.mark.asyncio
    async def test_resolve_database_ids_multiple(self):
        db_mgr = DatabaseManager()
        db_mgr._cache = {
            "WB_WDI": "World Development Indicators",
            "WB_GS": "Gender Statistics",
            "WB_HNP": "Health Nutrition and Population Statistics",
            "WB_ESG": "Environment, Social & Governance (ESG)"
        }

        assert db_mgr.resolve_database_ids("wb_wdi; wb_gs") == ["WB_WDI", "WB_GS"]
        assert db_mgr.resolve_database_ids("world development indicators; Gender") == ["WB_WDI", "WB_GS"]
        assert db_mgr.resolve_database_ids("  WDI ;  gender statistics ") == ["WB_WDI", "WB_GS"]

        # Test database containing a comma is resolved as a single unit
        assert db_mgr.resolve_database_ids("Environment, Social & Governance (ESG)") == ["WB_ESG"]
        assert db_mgr.resolve_database_ids("wdi; Environment, Social & Governance (ESG)") == ["WB_WDI", "WB_ESG"]

        with pytest.raises(ValueError) as exc:
            db_mgr.resolve_database_ids("wdi; nonexistent_db")
        assert "nonexistent_db" in str(exc.value)

    @pytest.mark.asyncio
    async def test_resolve_database_ids_fuzzy(self):
        db_mgr = DatabaseManager()
        db_mgr._cache = {
            "WB_WDI": "World Development Indicators",
            "WB_WGI": "Worldwide Governance Indicators",
            "WB_GS": "Gender Statistics"
        }

        # Fuzzy names with typos or variations that satisfy the 0.7 threshold
        assert db_mgr.resolve_database_id("world development indicator") == "WB_WDI"
        assert db_mgr.resolve_database_id("worldwide governd") == "WB_WGI"
        assert db_mgr.resolve_database_id("gender stats") == "WB_GS"

        # Under the threshold (nonexistent/completely different)
        assert db_mgr.resolve_database_id("some random stuff") is None
