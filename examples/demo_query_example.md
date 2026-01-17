# Data360 MCP Demo Query Example

## Query
> "Show me the labor force participation of both male and females in japan, please also give me the total for the year 2022"

## Workflow Execution

### Step 1: Search Indicators
**Tool:** `data360_search_indicators`

**Args:**
```json
{
  "query": "labor force participation",
  "required_country": "Japan"
}
```

**Result:** 5 of 746 indicators returned, sorted by country coverage

| # | Indicator | Latest | Covers Japan | Dimensions |
|---|-----------|--------|--------------|------------|
| 1 | `WB_WDI_SL_TLF_CACT_FE_ZS` - Labor force participation rate, female | 2024 | ✅ | - |
| 2 | `WB_HCP_EMP_2WAP_A` - Labor force participation rate (%) | 2024 | ✅ | **[SEX]** |
| 3 | `WB_WDI_SL_TLF_CACT_FM_NE_ZS` - Ratio of female to male | 2024 | ✅ | - |
| 4 | `WB_SSGD_FEM_MALE_LFP_RATIO` - Ratio of female to male | 2021 | ✅ | - |
| 5 | `WB_SSGD_LF_PARTICIPATION_RATE` - Labor force participation rate | 2022 | ❌ | [URBANISATION,AGE,SEX] |

**LLM Selection:** Picked `WB_HCP_EMP_2WAP_A` because it has `[SEX]` dimension for male/female breakdown.

---

### Step 2: Get Data
**Tool:** `data360_get_data`

**Args:**
```json
{
  "database_id": "WB_HCP",
  "indicator_id": "WB_HCP_EMP_2WAP_A",
  "disaggregation_filters": {"REF_AREA": "JPN"},
  "start_year": 2022,
  "end_year": 2022
}
```

**Result:**
| Year | SEX | Value |
|------|-----|-------|
| 2022 | F (Female) | 54.667% |
| 2022 | _T (Total) | 64.154% |

---

### Step 3: Generate Response

**Answer:**
> In Japan, the labor force participation rates for 2022:
> - **Total**: 64.2%
> - **Female**: 54.7%

---

## Token Usage
| Metric | Value |
|--------|-------|
| Input tokens | 7,334 |
| Output tokens | 301 |
| **Total** | **7,635** |

## Observations
1. **Dimensions worked** - Search correctly identified `[SEX]` dimension
2. **covers_country worked** - Japan (JPN) was correctly detected
3. **No get_disaggregation** - Workflow uses 2 steps (Search → Get Data)
4. **LLM picked right indicator** - Chose one with SEX dimension for male/female breakdown
