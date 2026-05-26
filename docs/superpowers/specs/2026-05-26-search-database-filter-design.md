# Search Database Filter Design Specification

Support filtering search queries by database in the search tool. Resolves user-supplied database names/IDs to official database names and forwards them to the Search V3 endpoint.

## Proposed Changes

### `src/data360/providers.py`
- Add `resolve_database_id(self, query: str) -> str | None` to the `DatabaseManager` class.
- The method will query the cached database mapping (id -> name) to resolve user inputs:
  1. Exact database ID match (case-insensitive).
  2. Exact database name match (case-insensitive).
  3. Substring match on database ID.
  4. Substring match on database name.

### `src/data360/api.py`
- Update the `_search_raw` helper function signature to accept `database: str | None = None`.
- In `_search_raw`, if `database` is provided:
  - Call `db_mgr.resolve_database_id(database)` to find the matching database ID.
  - If a database ID is resolved, retrieve the official database name from the database mapping.
  - Add this name to `database_names: [db_name]` inside the search payload for the Search V3 endpoint.
  - If it cannot be resolved, return a `SearchResponse` with an error indicating that the database could not be resolved.
- Update the `search` function signature to accept `database: str | None = None`.
- Update single-query, multi-query, and `query_groups` paths to forward the `database` parameter to `_search_raw`.

### `src/data360/mcp_server/tools.py`
- Update the `_search_indicators` wrapper function to accept `database: str | None = None`.
- Update the docstring to document the new `database` argument.
- Pass `database` to the `data360_api.search` call.

## Verification Plan

### Automated Tests
- Create tests in `tests/test_api.py` (or a dedicated test file) covering:
  - Exact database ID matching (e.g. `WB_WDI` -> `World Development Indicators`).
  - Substring/name matching (e.g. `wdi` -> `World Development Indicators`).
  - Search requests with invalid databases returning the appropriate resolution error.
  - Verification that the generated Search V3 endpoint HTTP request payload contains the correct `database_names` list.
