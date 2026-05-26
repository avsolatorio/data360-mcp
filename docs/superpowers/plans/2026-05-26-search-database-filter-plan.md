# Search Database Filter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow users to filter indicator search results by database by adding a `database` argument to the search tool, resolving it to a database ID and database name using the database ID manager, and passing it to the Search V3 endpoint.

**Architecture:** Add database resolution logic to `DatabaseManager` in `src/data360/providers.py` and pass the resolved database name into the `database_names` parameter of the Search V3 endpoint payload in `src/data360/api.py`. Expose the `database` parameter in the MCP tool wrapper in `src/data360/mcp_server/tools.py`.

**Tech Stack:** Python, Pydantic, FastMCP, pytest

---

### Task 1: Add `resolve_database_id` to `DatabaseManager`

**Files:**
- Create: `tests/test_database_resolution.py`
- Modify: `src/data360/providers.py:22-157`

- [ ] **Step 1: Write the failing test**

Write a new test file `tests/test_database_resolution.py` to verify that `resolve_database_id` correctly resolves various database queries to their corresponding database IDs.

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_database_resolution.py -v`
Expected: FAIL with "AttributeError: 'DatabaseManager' object has no attribute 'resolve_database_id'"

- [ ] **Step 3: Write minimal implementation**

Add the `resolve_database_id` method to the `DatabaseManager` class in `src/data360/providers.py`.

```python
    def resolve_database_id(self, query: str | None) -> str | None:
        """Resolve a database search term to a database ID from the cache.

        Matches by exact ID, exact name, substring of ID, or substring of name.
        """
        if not query:
            return None
        query_lower = query.lower().strip()

        # 1. Exact match on database ID (key)
        for db_id in self._cache:
            if query_lower == db_id.lower():
                return db_id

        # 2. Exact match on database name (value)
        for db_id, name in self._cache.items():
            if query_lower == name.lower():
                return db_id

        # 3. Substring match on database ID
        for db_id in self._cache:
            if query_lower in db_id.lower():
                return db_id

        # 4. Substring match on database name
        for db_id, name in self._cache.items():
            if query_lower in name.lower():
                return db_id

        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_database_resolution.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_database_resolution.py src/data360/providers.py
git commit -m "feat(providers): add resolve_database_id to DatabaseManager"
```

---

### Task 2: Implement `database` parameter in `_search_raw` and `search` in `src/data360/api.py`

**Files:**
- Modify: `src/data360/api.py`
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write the failing test**

Add failing test cases inside `tests/test_api.py` under the `TestSearch` class verifying database name resolution and payload injection.

```python
    @pytest.mark.asyncio
    async def test_search_with_database_filter_success(
        self, httpx_mock: pytest_httpx.HTTPXMock
    ):
        """Test search with a valid database filter that gets resolved."""
        captured_payloads = []

        def capture_callback(request: httpx.Request) -> httpx.Response:
            captured_payloads.append(json.loads(request.content))
            return httpx.Response(
                200,
                json={
                    "count": 1,
                    "results": [
                        {
                            "idno": "WB_WDI_SP_POP_TOTL",
                            "name": "Population, total",
                            "databases": [{"idno": "WB_WDI"}],
                            "description": "Total population",
                            "dimensions": [],
                        }
                    ],
                },
            )

        httpx_mock.add_callback(
            capture_callback,
            method="POST",
            url="https://api.test.example.com/portal/v1/public_data360_search",
        )

        with patch("data360.providers.get_database_manager") as mock_mgr_getter:
            from unittest.mock import MagicMock
            mock_mgr = MagicMock()
            # Mock mapping and resolution
            mock_mgr.resolve_database_id.return_value = "WB_WDI"
            mock_mgr.get_mapping = AsyncMock(return_value={"WB_WDI": "World Development Indicators"})
            mock_mgr_getter.return_value = mock_mgr

            result = await search("population", database="wdi")

        assert isinstance(result, EnrichedSearchResponse)
        assert len(result.indicators) == 1
        assert len(captured_payloads) == 1
        assert captured_payloads[0].get("database_names") == ["World Development Indicators"]
        assert result.error is None

    @pytest.mark.asyncio
    async def test_search_with_unresolved_database_filter(self):
        """Test search with a database filter that cannot be resolved returns an error."""
        with patch("data360.providers.get_database_manager") as mock_mgr_getter:
            from unittest.mock import MagicMock
            mock_mgr = MagicMock()
            mock_mgr.resolve_database_id.return_value = None
            mock_mgr_getter.return_value = mock_mgr

            result = await search("population", database="InvalidDB")

        assert isinstance(result, EnrichedSearchResponse)
        assert result.error is not None
        assert "could not be resolved" in result.error
        assert not result.indicators
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api.py -k "test_search_with_database"`
Expected: FAIL with TypeError or failure to accept `database` parameter.

- [ ] **Step 3: Modify `_search_raw` and `search` in `src/data360/api.py`**

Update `_search_raw` to accept `database: str | None = None`. Add the resolution step and inject it into the HTTP POST request payload.
Update `search` signature and its internal routing/execution paths (single-query, multi-query, query_groups) to accept and forward `database`.

In `src/data360/api.py`:
Update `_search_raw` signature and implementation:
```python
async def _search_raw(
    query: str,
    limit: int = 5,
    offset: int = 0,
    count: bool = True,
    economy_codes: list[str] | None = None,
    database: str | None = None,
) -> SearchResponse:
    ...
    database_names = []
    if database:
        from .providers import get_database_manager
        db_mgr = get_database_manager()
        db_id = db_mgr.resolve_database_id(database)
        if db_id:
            mapping = await db_mgr.get_mapping()
            db_name = mapping.get(db_id)
            if db_name:
                database_names = [db_name]
        else:
            return SearchResponse(
                error=f"Database '{database}' could not be resolved to a known database ID.",
                items=[],
                total_count=0,
                count=0,
            )
    ...
    payload = {
        "site": "data360",
        "query_string": request.query,
        "types": ["indicator"],
        "data_classification": ["public"],
        "skip": request.offset,
        "items_per_page": request.limit,
    }
    if economy_codes:
        payload["economy_codes"] = economy_codes
    if database_names:
        payload["database_names"] = database_names
```

Update `search` signature and forward database parameter in `search` function body:
```python
async def search(  # noqa: PLR0911
    query: str | None = None,
    required_country: str | None = None,
    limit: int = DEFAULT_SEARCH_LIMIT,
    offset: int = 0,
    queries: list[str] | None = None,
    query_groups: list[QueryGroup] | None = None,
    result_layout: str = "merged",
    dedupe: bool = True,
    database: str | None = None,
    # The following parameters are accepted for robustness...
    ...
) -> "EnrichedSearchResponse | MultiQuerySearchResponse":
    ...
    # queries task creation:
        raw_tasks = [
            _search_raw(
                query=q,
                limit=limit,
                offset=offset,
                economy_codes=[c.strip() for c in country_code.split(";")] if country_code else None,
                database=database,
            )
            for q in clean_queries
        ]

    # query_groups task creation:
        raw_tasks = [
            _search_raw(
                query=q,
                limit=limit,
                offset=offset,
                economy_codes=[c.strip() for c in code.split(";")] if code else None,
                database=database,
            )
            for q, code in zip(clean_queries, per_query_codes)
        ]

    # single-query search call:
    try:
        search_result = await _search_raw(
            query=query,  # type: ignore[arg-type]  # validated non-None above
            limit=limit,
            offset=offset,
            economy_codes=[c.strip() for c in country_code.split(";")] if country_code else None,
            database=database,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_api.py -k "test_search_with_database"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/data360/api.py tests/test_api.py
git commit -m "feat(api): implement database filtering in search and _search_raw"
```

---

### Task 3: Expose `database` in MCP Tool `_search_indicators`

**Files:**
- Modify: `src/data360/mcp_server/tools.py`

- [ ] **Step 1: Write the failing test**

Add verification in `tests/test_api.py` or `tests/test_mcp_resources_and_prompts.py` that the registered MCP tool schema for `data360_search_indicators` has the `database` parameter.

```python
def test_search_indicators_tool_schema():
    from data360.mcp_server.tools import _search_indicators
    import inspect
    sig = inspect.signature(_search_indicators)
    assert "database" in sig.parameters
    assert sig.parameters["database"].default is None
```

Place this test inside `tests/test_mcp_resources_and_prompts.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mcp_resources_and_prompts.py -k "test_search_indicators_tool_schema"`
Expected: FAIL with AssertionError or "database not in sig.parameters"

- [ ] **Step 3: Modify `_search_indicators` in `src/data360/mcp_server/tools.py`**

```python
async def _search_indicators(
    query: str | None = None,
    required_country: str | None = None,
    limit: int = 5,
    offset: int = 0,
    queries: list[str] | None = None,
    query_groups: list[dict[str, Any]] | None = None,
    result_layout: str = "merged",
    dedupe: bool = True,
    database: str | None = None,
) -> Any:
    """Search for Data360 indicators with enriched metadata for selection.

    Use when the user asks for data on a development topic (e.g. GDP, poverty, education).
    Provide exactly one of `query`, `queries`, or `query_groups`.

    Args:
        query: Single topic query (e.g. "unemployment"). Avoid special characters like parentheses () or dollar signs $ as they cause search failures. Example: 'GDP per capita'.
        required_country: Semicolon-separated ISO country codes (e.g. "KEN;USA"). Consider calling `data360_expand_country_group` to find country codes in regional/income groups, or `data360_find_codelist_value` to resolve country names.
        limit: Max indicators per query (default 5).
        offset: Offset for pagination.
        queries: List of topics for multi-topic search. Example: ['GDP per capita', 'inflation rate'].
        query_groups: Grouped queries with specific country scopes. Example: [{'queries': ['GDP per capita'], 'country': 'Kenya'}].
        result_layout: Mode to return results: "merged" (flat, deduped list of indicators) or "by_query" (indicators grouped by search query).
        dedupe: De-duplicate indicators across query results.
        database: Optional database filter (e.g., "WDI", "Gender Statistics", or ID "WB_WDI") to narrow down search results.
    """
    return await data360_api.search(
        query=query,
        required_country=required_country,
        limit=limit,
        offset=offset,
        queries=queries,
        query_groups=query_groups,
        result_layout=result_layout,
        dedupe=dedupe,
        database=database,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_mcp_resources_and_prompts.py -k "test_search_indicators_tool_schema"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/data360/mcp_server/tools.py tests/test_mcp_resources_and_prompts.py
git commit -m "feat(mcp): expose database filter parameter in search_indicators tool"
```
