# Design Specification: Addressing PR Feedback on feat/optimize-tools-98

This design document outlines the changes to address the code review feedback from `avsolatorio` on PR #100.

## 1. Caching Dimensions/Disaggregation Calls

### Problem
Both `get_metadata` and `get_disaggregation` make raw HTTP POST requests to the dimensions endpoint (`/portal/v1/dimensions`) with the same payload (`{"database_id": database_id, "indicator_id": indicator_id}`). These calls are frequent and would benefit from caching with a TTL of 10 minutes (600 seconds) to prevent redundant network requests and improve performance.

### Solution
1. Introduce a new caching layer for the dimensions API using `cachetools.TTLCache`.
2. Implement a helper function `_fetch_dimensions_with_cache` that encapsulates the HTTP call and caching.
3. Integrate the helper function into `get_metadata` and `get_disaggregation`.
4. Ensure the cache is cleared in tests between runs.

### Implementation Details
* **Cache Definition**:
  ```python
  _DIMENSIONS_API_CACHE_TTL = 600  # 10 minutes in seconds
  _dimensions_api_cache: cachetools.TTLCache = cachetools.TTLCache(
      maxsize=256, ttl=_DIMENSIONS_API_CACHE_TTL
  )
  _dimensions_api_cache_lock = threading.Lock()
  ```
* **Helper Function**:
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

---

## 2. Pruning Deprecated Parameters from `_search_raw`

### Problem
The parameters `select_fields` and `odata_options` in `_search_raw` are deprecated under SearchV3 (which returns flat indicators and does not support select/OData queries). However, they are still present in the method signature and passed in calls.

### Solution
1. Remove `select_fields: list[str] | None = None` and `odata_options: dict[str, str] | None = None` from the signature of `_search_raw`.
2. Update the calls in `api.py` to not pass these parameters.
3. Clean up unit tests in `tests/test_multi_query_search.py` that assert these parameters are passed.

---

## 3. Adding Public Data Classification in `_search_raw`

### Problem
`_search_raw` should explicitly ask for public indicators.

### Solution
Add `"data_classification": ["public"]` to the request payload dict in `_search_raw`:
```python
    payload = {
        "site": "data360",
        "query_string": request.query,
        "types": ["indicator"],
        "data_classification": ["public"],
        "skip": request.offset,
        "items_per_page": request.limit,
    }
```

---

## 4. Verification Plan

### Automated Tests
* Run existing test suites: `uv run pytest --ignore=tests/test_prompt_injection.py`
* Update existing assertions that mock and check `select_fields` on `_search_raw` calls.
* Add unit tests to verify:
  * `_fetch_dimensions_with_cache` caches successful calls for 10 minutes.
  * `_fetch_dimensions_with_cache` does not cache 400/404 status codes.
  * Cache is properly isolated in tests.
