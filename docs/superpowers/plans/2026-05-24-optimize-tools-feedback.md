# Optimize Tools PR Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Address PR feedback from avsolatorio on PR #100 by pruning deprecated search parameters, adding data classification parameters to search, fanning out coverage check in multi-query search, caching dimensions calls with TTL, and updating the conftest/tests to verify the changes.

**Architecture:** Implement `_fetch_dimensions_with_cache` in `src/data360/api.py` utilizing `cachetools.TTLCache` to cache the dimensions HTTP response for 10 minutes. Clean up `_search_raw` signature and payload.

**Tech Stack:** Python 3.11, HTTPX, cachetools, pytest

---

### Task 1: Prune Deprecated Parameters from `_search_raw` and Add classification parameter

**Files:**
- Modify: `src/data360/api.py`
- Modify: `tests/test_multi_query_search.py`

- [ ] **Step 1: Write a test asserting that `_search_raw` does not accept `select_fields` or `odata_options`**
  Modify: `tests/test_multi_query_search.py`
  Remove the two tests: `test_single_query_path_uses_constant` and `test_multi_query_path_uses_constant` from `TestEnrichmentSelectFields` since `select_fields` will be removed.
  Add a test:
  ```python
  def test_search_raw_signature():
      import inspect
      from data360.api import _search_raw
      sig = inspect.signature(_search_raw)
      assert "select_fields" not in sig.parameters
      assert "odata_options" not in sig.parameters
  ```

- [ ] **Step 2: Run pytest to verify signature test fails**
  Run: `uv run pytest tests/test_multi_query_search.py -k test_search_raw_signature`
  Expected: FAIL

- [ ] **Step 3: Modify `_search_raw` and calls to remove deprecated parameters, and add public classification**
  Modify: `src/data360/api.py`
  Change:
  ```python
  async def _search_raw(
      query: str,
      limit: int = 5,
      offset: int = 0,
      count: bool = True,
      economy_codes: list[str] | None = None,
  ) -> SearchResponse:
  ```
  And in the payload dictionary inside `_search_raw`, add:
  ```python
  "data_classification": ["public"],
  ```
  Update calls:
  Remove `select_fields` in all calls to `_search_raw` inside `api.py`.

- [ ] **Step 4: Run test to verify passes**
  Run: `uv run pytest tests/test_multi_query_search.py`
  Expected: PASS

- [ ] **Step 5: Commit**
  Run:
  ```bash
  git add src/data360/api.py tests/test_multi_query_search.py
  git commit -m "refactor(search): prune deprecated parameters and add data classification"
  ```

---

### Task 2: Implement Dimensions Cache Wrapper

**Files:**
- Modify: `src/data360/api.py`
- Modify: `tests/conftest.py`

- [ ] **Step 1: Define cache and helper in `src/data360/api.py`**
  Add at module level (around line 85):
  ```python
  _DIMENSIONS_API_CACHE_TTL = 600  # 10 minutes in seconds
  _dimensions_api_cache: cachetools.TTLCache = cachetools.TTLCache(
      maxsize=256, ttl=_DIMENSIONS_API_CACHE_TTL
  )
  _dimensions_api_cache_lock = threading.Lock()
  ```

  Implement `_fetch_dimensions_with_cache` in `src/data360/api.py`:
  ```python
  async def _fetch_dimensions_with_cache(
      database_id: str,
      indicator_id: str,
  ) -> dict[str, Any]:
      """Fetch dimensions from the API with a 10-minute in-memory cache.

      Only caches successful responses. Returns parsed JSON dict.
      Raises httpx.HTTPStatusError or other request exceptions on non-400/404 failures.
      """
      _cache_key = (database_id, indicator_id)
      with _dimensions_api_cache_lock:
          _cached = _dimensions_api_cache.get(_cache_key)
      if _cached is not None:
          return _cached

      dimensions_url = (
          data360_config.dimensions_url or f"{data360_config.api_url}/portal/v1/dimensions"
      )
      headers = {"accept": "*/*", "Content-Type": "application/json"}
      payload = {"database_id": database_id, "indicator_id": indicator_id}

      client = get_shared_httpx_client()
      response = await client.post(
          dimensions_url,
          json=payload,
          headers=headers,
      )

      if response.status_code in (400, 404):
          return {"dimensions": []}

      response.raise_for_status()

      if not response.content or not response.text.strip():
          result = {"dimensions": []}
      else:
          result = response.json()

      with _dimensions_api_cache_lock:
          _dimensions_api_cache[_cache_key] = result

      return result
  ```

- [ ] **Step 2: Clear cache in `tests/conftest.py`**
  Modify: `tests/conftest.py`
  Import `_dimensions_api_cache` and `_dimensions_api_cache_lock` from `data360.api`.
  Clear `_dimensions_api_cache` in the `_isolate_data360_api_state` fixture.

- [ ] **Step 3: Update `get_metadata` and `get_disaggregation` to use `_fetch_dimensions_with_cache`**
  Modify: `src/data360/api.py`
  In `get_metadata`:
  ```python
      # 2. Fetch Dimensions
      if fetch_disaggregation:
          try:
              dimensions_json = await _fetch_dimensions_with_cache(
                  database_id, indicator_id
              )
              raw_disaggregations = _parse_dimensions_response(dimensions_json)
              disaggregations = _strip_disaggregation(
                  _get_valid_disaggregations(raw_disaggregations),
                  queried_countries,
              )
          except Exception as e:
              mcp_err = classify_error(e, context="disaggregation")
              errors.append(mcp_err.detail)
  ```
  In `get_disaggregation`:
  ```python
      try:
          dimensions_json = await _fetch_dimensions_with_cache(
              database_id, indicator_id
          )
          raw_data = _parse_dimensions_response(dimensions_json)
          valid_dimensions = _get_valid_disaggregations(raw_data)
          result_disagg = {
              "dimensions": _strip_disaggregation(valid_dimensions, queried_countries)
          }
          with _disaggregation_cache_lock:
              _disaggregation_cache[_disagg_cache_key] = result_disagg
          return result_disagg

      except Exception as e:
          mcp_err = classify_error(e, context="disaggregation")
          return {"error": mcp_err.detail}
  ```

- [ ] **Step 4: Run pytest to verify all tests pass**
  Run: `uv run pytest --ignore=tests/test_prompt_injection.py`
  Expected: PASS

- [ ] **Step 5: Commit**
  Run:
  ```bash
  git add src/data360/api.py tests/conftest.py
  git commit -m "feat(api): implement cached dimensions fetch with 10-minute TTL"
  ```

---

### Task 3: Write cache verification tests

**Files:**
- Modify: `tests/test_api.py`

- [ ] **Step 1: Write test case for TTL cache verification**
  Add to `tests/test_api.py`:
  ```python
  @pytest.mark.asyncio
  async def test_dimensions_api_cache_ttl(self, httpx_mock: pytest_httpx.HTTPXMock):
      from data360.api import _dimensions_api_cache, get_metadata
      
      # Mock the metadata fetch first
      httpx_mock.add_response(
          method="POST",
          url=f"{_test_api}/metadata",
          json={"value": [{"series_description": {"database_id": "WB_WDI", "idno": "IND_1"}}]}
      )
      
      # Mock the dimensions call
      httpx_mock.add_response(
          method="POST",
          url=f"{_test_api}/portal/v1/dimensions",
          json={"dimensions": [{"field_name": "SEX", "field_value": ["M", "F"]}]}
      )

      # First call should hit HTTP
      await get_metadata("WB_WDI", "IND_1")
      
      # Second call should use cache (no new HTTP requests received)
      await get_metadata("WB_WDI", "IND_1")
      
      # Assert only 1 request was sent to the dimensions endpoint
      requests = httpx_mock.get_requests()
      dimensions_reqs = [r for r in requests if "portal/v1/dimensions" in str(r.url)]
      assert len(dimensions_reqs) == 1
  ```

- [ ] **Step 2: Run pytest to verify conftest clears the cache and test passes**
  Run: `uv run pytest tests/test_api.py -k test_dimensions_api_cache_ttl`
  Expected: PASS

- [ ] **Step 3: Commit**
  Run:
  ```bash
  git add tests/test_api.py
  git commit -m "test(api): verify 10-minute TTL dimensions caching"
  ```
