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
            "WB_HNP": "Health Nutrition and Population Statistics"
        }

        assert db_mgr.resolve_database_ids("wb_wdi, wb_gs") == ["WB_WDI", "WB_GS"]
        assert db_mgr.resolve_database_ids("world development indicators; Gender") == ["WB_WDI", "WB_GS"]
        assert db_mgr.resolve_database_ids("  WDI ;  gender statistics ") == ["WB_WDI", "WB_GS"]
        with pytest.raises(ValueError) as exc:
            db_mgr.resolve_database_ids("wdi, nonexistent_db")
        assert "nonexistent_db" in str(exc.value)
