# Theme Filtering for Search: Research Findings and Implementation Plan

## Problem Statement

Users want to scope indicator search results to certain "documents" — either by
**source** (e.g. WDI only) or by **theme** (e.g. Poverty, Climate Change,
Digital). Source/database filtering already works server-side today
(`data360_search_indicators(database="wdi")`, implemented in
`src/data360/api.py:654-695`). Theme filtering does not exist yet.

This document records research into how the Data360 backend and portal handle
themes, and proposes an implementation plan for the MCP server.

---

## Research Findings

### 1. The theme taxonomy is public

Themes are defined by the **Data360 Topics Hierarchy** (`HCL_TOPICS_D360`),
retrievable without authentication:

```
GET https://data360api.worldbank.org/data360/portal/v1/hierarchy?type=site&id=HCL_TOPICS_D360
```

Response structure (`data.Hierarchy[0]`):

| Level | ID pattern | Example |
|---|---|---|
| PILLAR (WB Practice Groups) | `P1`..`P5` | `P3` = Prosperity |
| Data360 Topic L1 | `P3_000001` | `P3_000001` = Economic Policy |
| Data360 Topic L2 | `P3_0000xx` | `P3_000019` = Inequality and Shared Prosperity |

Each node carries `id`, `value` (name), `description`, `technical_value`
(slug), `indicator_count`, `dataset_count`, child `codes`, and — on L2 nodes —
curated `indicators` arrays (`[{id: "WB_WDI_SP_POP_TOTL", ...}]`).

Pillar snapshot (August 2026):

| Pillar | ID | Indicators | Datasets | L1 topics |
|---|---|---|---|---|
| Planet | P1 | 291 | 31 | Agriculture and Food, AgriConnect, Climate Change, Environment, Water |
| People | P2 | 834 | 18 | Education, Gender, Health Nutrition & Population, Social Protection |
| Prosperity | P3 | 4,537 | 70 | Economic Policy, Growth and Jobs, Finance, Institutions, Poverty, Trade Investment and Competitiveness |
| Infrastructure | P4 | 274 | 33 | Energy & Extractives, Global Infrastructure Finance, Transport, Urban Resilience and Land |
| Digital | P5 | 144 | 15 | Connectivity, Data Infrastructure, Cybersecurity, Digital Industry and Jobs, Digital Services |

### 2. The search index is themed, but the public endpoint does not expose the filter

The search backend (Azure AI Search behind the proxy) returns a
**`topics/name` facet** whose values match the hierarchy topic names (e.g.
"Economic Policy: 71", "Prosperity: 103" for a "GDP" query). However:

- Result items do **not** include a `topics` field (only the facet aggregate).
- The **public** endpoint used by this MCP server,
  `POST /data360/portal/v1/public_data360_search`, silently ignores every
  theme-filter parameter variant tested (`topic_ids`, `topics`,
  `topic_names`, `themes`, `theme_ids`, Azure-style `filter`, etc. — ~25
  variants). It only honors `database_names` and `economy_codes`.
- Unknown payload keys do not error; they are dropped.

### 3. How the Data360 portal filters by theme

The portal SPA (extracted from `clientlib-data360-data.js`, webpack chunk 8430
`SearchListingWrapper`) builds this request payload:

```json
{
  "site": "data360",
  "data_classification": ["public"],
  "query_string": "<term>",
  "types": ["indicator"],
  "dimensions": [],                       // disaggregation facet
  "database_names": [],                   // source filter
  "economy_codes": [],                    // country + region
  "topic_ids": ["P3_000001"],             // THEME filter (hierarchy IDs)
  "source_names": [],                     // organization filter
  "vocabulary_names": [],
  "skip": 0,
  "items_per_page": 20,
  "orderby": ""
}
```

Theme facet selections are collected as checked hierarchy node IDs
(`themeParams` in the SPA pushes `node.id` recursively through `codes`).
**Critically**, the portal POSTs this to the OAuth-protected endpoint
`/data360/int/data360/portal/v1/search` (auth via API key + token from
`/wbg/aem/service/refresh-search-token`), not the public endpoint. The
payload schema is otherwise identical, which strongly suggests the backend
proxy simply does not whitelist `topic_ids` on the public variant yet.

---

## Implementation Plan

### Work item 1 — Theme taxonomy service (new `src/data360/themes.py`)

- `ThemeManager` modeled on `DatabaseManager` (`src/data360/providers.py:22-141`)
  with TTL cache and background refresh.
- Fetches and parses the public hierarchy endpoint into a flat index:
  - `ThemeNode {id, name, pillar_id, level, description, technical_value,
    indicator_count, dataset_count, indicator_ids}`
  - Membership sets: per-node union of subtree `indicators` arrays (used for
    strict filtering in work item 3).
- `resolve_theme_ids("prosperity; economic policy")` -> `["P3", "P3_000001"]`,
  supporting exact IDs, names, slugs, substring and fuzzy matching — mirroring
  `resolve_database_ids`.
- `src/data360/config.py`: add `themes_hierarchy_url` setting (default
  derived from `api_url`).

### Work item 2 — Theme discovery tooling (no filtering semantics)

- New MCP tool **`data360_list_themes`** (`src/data360/mcp_server/tools.py`):
  returns pillars with L1 topics and indicator/dataset counts; optional
  `pillar` argument expands L2 sub-topics.
- New MCP resource **`data360://themes`**
  (`src/data360/mcp_server/resources.py`), alongside the existing
  `data360://databases` resource.
- Update `data360://search-usage`, the `data360_search_indicators` docstring,
  and prompt guidance:
  - Prefer `database="wdi"` for **source** scoping (exact, server-side).
  - Use `theme=` for **topic** scoping (see work item 3 caveats).

### Work item 3 — Strict theme filter on search

- Add `theme: str | None = None` parameter flowing through
  `tools.py:_search_indicators` -> `api.search()` (`src/data360/api.py:993`)
  -> `_search_raw()` (`src/data360/api.py:631`).
- `_search_raw` includes `"topic_ids"` in the payload anyway: zero-cost
  forward compatibility — filtering becomes exact automatically if/when the
  backend whitelists it.
- **Client-side enforcement**: post-filter results by
  `idno ∈ theme_indicator_set(theme)`. If filtering empties the result set,
  return an explanatory note (curated membership lists are partial) with theme
  statistics rather than a silent empty success.
- Apply the same post-filter inside the multi-query fan-out path
  (`src/data360/api.py:1144-1303`) so `queries`/`query_groups` honor `theme`.
- Response models (`src/data360/models.py`): add `applied_theme_ids` and
  `theme_filtered` transparency fields.

### Work item 4 — Backend change request

- New `docs/backend-change-request-topic-ids.md` containing the evidence in
  this document (SPA payload schema, public-vs-internal endpoint discrepancy,
  empirical test matrix) and the specific ask:
  1. Honor `topic_ids` on `public_data360_search`.
  2. Return item-level `topics` in search results (enables future
     facet-accurate client-side filtering).
- Once shipped upstream, the `topic_ids` passthrough from work item 3 makes
  strict filtering exact with no MCP-side changes.

### Work item 5 — Tests and verification

- pytest (pattern: `tests/test_prefiltering.py`):
  - Hierarchy parsing from a fixture payload.
  - Theme name/ID/slug resolution, including failure modes.
  - Strict post-filter behavior with mocked `_search_raw` (pass-through,
    filtered, and empty-result note paths).
  - Payload assertion: `topic_ids` present in the outgoing search request.
- Run the full test suite plus lint/typecheck per repo configuration.

---

## Known Limitations

- **Strict filtering is bounded by curated lists.** Pillar-level
  `indicator_count` (e.g. Prosperity = 4,537) exceeds the indicators
  enumerated in subtree `indicators` arrays, so strict post-filtering may
  under-return relative to what the backend considers in-theme. This is
  documented in tool output and resolved fully by work item 4.
- **Facet values are not resolvable to IDs automatically** — the
  `topics/name` facet returns names; mapping them back to hierarchy IDs relies
  on the ThemeManager's name matching.
- Theme filtering cannot be combined with result-level verification until the
  backend returns item-level topics.

## Alternatives Considered

| Option | Verdict |
|---|---|
| Theme-aware ranking (annotate/sort by membership, no exclusion) | Rejected for now — confusing "in-theme" badges on partial lists; can be added later |
| Trust `database` filter alone | Insufficient — themes cut across databases (e.g. Poverty spans WB_WDI, WB_PIP, WB_MPO) |
| Proxy the OAuth `/int/search` endpoint | Rejected — requires credentials we do not have and should not depend on |
