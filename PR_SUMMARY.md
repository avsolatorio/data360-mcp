# Data360 MCP Enhancements - Pull Request Summary

## Overview

This PR introduces significant enhancements to the Data360 MCP server, focusing on **entity resolution**, **metadata validation**, and **LLM integration improvements**. These changes make the MCP tools more reliable and accurate for LLM-based data retrieval workflows.

---

## Architecture: LLM vs MCP Responsibilities

Understanding the division of labor between the LLM (chatbot) and MCP server is crucial:

| Responsibility | LLM (Chatbot) | MCP Server |
|----------------|---------------|------------|
| **Typo Correction** | Corrects "luxemborg" -> "Luxembourg" before calling tools | Not responsible |
| **Query Interpretation** | Understands "last 3 years" means 2024-2026 | Not responsible |
| **Entity Resolution** | Calls MCP tool with corrected query | Fuzzy matches "Luxembourg" -> "LUX" (can be replaced with GLiNER2) |
| **Frequency Decision** | Decides whether to request monthly/annual based on user intent | Validates if indicator supports it |
| **Time Filtering** | Converts "last 3 years" to start_year/end_year | Filters data server-side |
| **Data Presentation** | Formats tables, summaries, analysis | Just returns raw data |

**Example flow:**
```
User: "Show me luxemborg inflation monthly"
         ↓
LLM: Corrects to "Luxembourg", understands "monthly" = FREQ: "M"
         ↓
MCP: find_codelist_value("REF_AREA", "Luxembourg") → "LUX"
         ↓
LLM: Calls get_data with {"REF_AREA": "LUX", "FREQ": "M"}
         ↓
MCP: Returns filtered data or empty if monthly not available
         ↓
LLM: Presents data or informs user "Only annual data available"
```

---

## Key Changes

### 1. Unified CodelistManager (`providers.py`)

**Problem:** Country names needed conversion to ISO codes for API queries.

**Solution:** Created `CodelistManager` class that:
- Fetches global codelists (REF_AREA, UNIT_MEASURE) from API
- Provides static mappings for FREQ, SEX, AGE, URBANISATION
- Uses fuzzy matching to handle partial names
- Caches results for performance

---

### 2. New MCP Tool: `data360_find_codelist_value`

**Purpose:** LLM calls this to convert human-readable names to API codes.

**Supported codelist types:**
| Type | Example Input | Output |
|------|---------------|--------|
| `REF_AREA` | "Kenya", "Sub-Saharan Africa" | "KEN", "SSF" |
| `FREQ` | "monthly", "annual", "quarterly" | "M", "A", "Q" |
| `SEX` | "female", "male", "total" | "F", "M", "_T" |
| `AGE` | "youth", "working age", "elderly" | "Y15T24", "Y25T54", "Y65T99" |
| `URBANISATION` | "urban", "rural" | "URB", "RUR" |

**Example: Female unemployment query**
```
User: "What is the female unemployment rate in Kenya?"
         ↓
LLM: Identifies need for REF_AREA + SEX filters
         ↓
MCP: find_codelist_value("REF_AREA", "Kenya") → "KEN"
MCP: find_codelist_value("SEX", "female") → "F"
         ↓
LLM: get_data(..., disaggregation_filters={"REF_AREA": "KEN", "SEX": "F"})
         ↓
MCP: Returns unemployment data filtered to Kenya + Female only
```

---

### 4. New Tool: `data360_list_indicators`
**What it does:**
- Lists all indicator IDs for a specific database (e.g., "WB_WDI")
- Enables bulk analysis and auditing of datasets

### 5. Enhanced: `data360_discover_indicators`
**Enhancements:**
- Added `periodicity` field (e.g., "Annual", "Monthly", "Other")
- Restored `available_frequencies` (e.g., `["A"]`, `["_O"]`) for full context
- LLM checks both to decide if FREQ filter is needed
- Prevents invalid requests (e.g., monthly on "Other" frequency indicators)

**What it does:**
1. Searches for indicators matching the query
2. Fetches metadata for each (country coverage, dimensions, time range)
3. **Ranks results** to prioritize best matches

**Ranking logic:**
| Priority | Criteria | Score |
|----------|----------|-------|
| 1st | Has required country data | +100 |
| 2nd | Has all required dimensions (SEX, AGE, etc.) | +50 |
| 3rd | API search relevance score | +0-100 |

**Response includes:**
- `indicator_id`, `database_id`, `name`
- `has_country`: Does it have data for the requested country?
- `available_dimensions`: What filters are available (SEX, AGE, etc.)
- `available_frequencies`: `["A"]`, `["M"]`, `["_O"]`
- `periodicity`: "Annual", "Monthly", "Other"
- `time_range`: `{"start": "2000", "end": "2026"}`

---

### 4. Time Period Filtering

**Problem:** "Last 3 years" returned 60+ years of data.

**Solution:** Added `start_year`/`end_year` parameters to `get_data()`:
```python
get_data(..., start_year=2024, end_year=2026)  # Only 3 data points
```

---

### 5. LLM Demo Script (`scripts/llm_mcp_demo.py`)

Interactive demo with:
- Multi-turn conversation support
- Verbose tool call output
- System prompt with FREQ validation rules

---

## Files Modified

| File | Changes |
|------|---------|
| `src/data360/providers.py` | New `CodelistManager` class |
| `src/data360/mcp_server/tools.py` | Added `data360_find_codelist_value` |
| `src/data360/api.py` | Added time filtering, frequency metadata |
| `scripts/llm_mcp_demo.py` | New interactive demo |
| `scripts/start_server.sh` | New startup script |

---

## Why This Matters

1. **Token Efficiency** - Time filtering reduces data volume
2. **Accuracy** - Frequency validation prevents incorrect claims
3. **Clear Architecture** - LLM handles language, MCP handles data

---

## Verification & Analysis
### 1. Frequency Analysis Script
- Created `scripts/analyze_frequencies.py`
- Analyzed `WB_WDI`, `WB_SSGD`, and `FAO` databases
- Confirmed `WB_SSGD` contains both Annual (`A`) and Irregular (`_O`) indicators
- Validated that new logic correctly distinguishes between them to avoid API errors

### 2. Manual Testing
- **Unemployment (Irregular/Monthly):** Verified LLM correctly handles `_O` frequency (skips filter)
- **GDP (Annual):** Verified LLM applies `FREQ=A` correctly
- **Time Filtering:** Verified API correctly filters `timePeriodFrom=2020`

## Known Issues
- `WB_GEM` endpoint returns 417 error (unrelated to this PR, consistent with existing behavior)

