# Viz Engine Quality Improvements — Implementation Plan

## Background

363 eval reports (GEval judge, OpenAI o4-mini) were analyzed via `extract_critique_insights.py`.
The judge consistently docked points across the same categories. This plan addresses them in priority order.

**Baseline score**: 7.0/10 (run 2, seed=42, 26 scenarios)  
**Target**: ≥ 8.5/10 average across all 13 strategies

---

## Open Questions

> [!IMPORTANT]
> Before starting Phase 2 (Legend Suppression Audit), confirm: should bar charts for cross-sectional with only one country ever show a color legend? Current behavior suppresses it unconditionally for single-country views.

> [!IMPORTANT]
> For Phase 4 (Country End Labels), confirm: is there a width budget concern? End-of-line labels may overflow for long country names at 680px chart width.

---

## Proposed Changes

### Phase 1 — Tooltip Standardization [HIGH IMPACT, LOW RISK]

> [!NOTE]
> Tooltips appear incomplete in 66% of reports (n=240, avg 7.9). Standardizing the template to always include country + year + value+unit + indicator name should lift the floor score.

#### [MODIFY] [viz_config.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/viz_config.py)

- Audit `build_structured_tooltips()` (line ~714): ensure `indicator_name` is always included as a tooltip field when available.
- Ensure the value field always carries a `format` string derived from `unit_measure` (%, comma-separated, B/M/K abbreviation).
- For choropleth (`build_choropleth_spec`): verify tooltip includes `country`, `value+unit`, `indicator_name` — currently the map hover may only show the value.
- For heatmap (`build_heatmap_spec`): confirm tooltip shows `country`, `year`, `value`, `indicator_name`.

**Files**: `src/data360/viz_config.py` (lines 714–790, 2636–2750)  
**Test**: Run `uv run python evals/explore_chart_types.py --strategy choropleth --count 4 --seed 1`

---

### Phase 2 — Legend Suppression Audit [HIGH IMPACT, LOW RISK]

> [!WARNING]
> `legend: None` is set in 4 places (lines 1798, 2361, 2612, 2919). Two of these are on the color encoding of multi-series charts that **do** need a legend. Removing it from those cases fixes 31% of reports (n=111, avg 7.5).

#### [MODIFY] [viz_config.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/viz_config.py)

- **Line 1798** (`build_cross_sectional_spec`): `color_enc["legend"] = None` — this is correct for cross-sectional bars where y-axis already labels each country. Keep.
- **Line 2361** (inside breakdown/small-multiples builder): suppress legend only when `color_dim == facet_dim` (legend is redundant if facet already separates). Otherwise keep legend visible.
- **Line 2612** (small-multiples facet): `"legend": None` on the color field — review: if facets are by country and color is by indicator, legend is needed.
- **Line 2919** (temporal multi-indicator stacked layer): audit if suppression is intentional.

**Files**: `src/data360/viz_config.py`  
**Test**: `uv run pytest tests/test_viz_comp_breakdown.py tests/test_viz_complex.py -x`

---

### Phase 3 — Axis Title Completeness [HIGH IMPACT, LOW RISK]

> [!NOTE]
> Axis issues appear in 65% of reports (n=236, avg 8.0). The judge commonly flags: Y-axis title missing or using raw field name, X-axis unlabeled for value fields.

#### [MODIFY] [viz_config.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/viz_config.py)

- Audit `FixValueAxisEncodingRule.apply()` (line ~4089): ensure it sets `title` on the value axis to the `unit_label` string, not `None`.
- For `build_choropleth_spec` and `build_heatmap_spec`: ensure the color scale axis has a title set to the indicator name + unit.
- Audit `build_temporal_single_spec` (line 1669): `y_title` should always be `indicator_name (unit)` — never empty.
- Check `TemporalAxisCleanupRule` (line ~4128): ensure it only sets `title=None` on the temporal x-axis (which shows year ticks), not on value axes.

**Files**: `src/data360/viz_config.py`  
**Test**: `uv run pytest tests/test_viz_grammar_contract.py -x`

---

### Phase 4 — Sort Order on Bar Charts [MEDIUM IMPACT, LOW RISK]

> [!NOTE]
> Missing sort appears in 6% of reports (n=22, avg 7.6). Cross-sectional and chained-rank bars should always sort descending by value by default. Currently sort is only applied when the caller explicitly signals it.

#### [MODIFY] [viz_config.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/viz_config.py)

- In `build_cross_sectional_spec` (line ~1766): ensure `y: {field: "country", sort: {field: "value", order: "descending"}}` is the default. Currently it may default to alphabetical if no sort signal is present.
- In `build_distribution_spec` (line ~1847): strip plot should sort by value for interpretability.

**Files**: `src/data360/viz_config.py`  
**Test**: `uv run python evals/explore_chart_types.py --strategy cross_sectional --count 6 --seed 5`

---

### Phase 5 — Year Gap Dashing on All Temporal Strategies [MEDIUM IMPACT, LOW RISK]

> [!NOTE]
> Year-gap issues appear in 12% of reports (n=47, avg 6.7). `LineYearGapStrokeDashRule` is in `POST_PROCESSING_RULES` and should apply to all strategies but only fires when `mark = line`. Need to verify it actually applies to `temporal_multi_indicator`, `correlation_temporal`, and `stacked_area`.

#### [MODIFY] [viz_config.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/viz_config.py)

- Audit `LineYearGapStrokeDashRule.apply()` (line ~4226): check if it traverses layered specs (list of layers) — it may only patch the top-level `mark`, missing nested line layers in `temporal_multi_indicator`.
- Add recursive spec traversal so the rule patches nested `{"mark": "line"}` objects inside `layer: [...]`.

**Files**: `src/data360/viz_config.py` (line ~4226–4280)  
**Test**: `uv run pytest tests/test_temporal_frequency.py -x`

---

### Phase 6 — Zero Line on All Signed-Value Charts [LOW IMPACT, LOW RISK]

> [!NOTE]
> `ZeroLineRule` is already in `POST_PROCESSING_RULES` (line 5028). Issue is likely that it only fires when the domain crosses zero, which requires the actual data values to be present at post-processing time. Verify rule receives `df` kwarg.

#### [MODIFY] [visualization.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/visualization.py)

- Confirm `ZeroLineRule` receives `df=viz_data` at both call sites (lines 1583, 2068) — check the `sig.parameters` introspection already handles it.
- If not, add `"df"` to the kwargs dispatch logic.

**Files**: `src/data360/visualization.py` (lines 1583–1600, 2068)  
**Test**: Manual — run a GDP growth scenario which spans negative values (2020 COVID dip) and check for zero line in spec.

---

### Phase 7 — Country End Labels on Multi-Series Lines [LOW IMPACT, MEDIUM RISK]

> [!NOTE]
> Country label issues appear in 27% of reports (n=99, avg 7.4). The judge expects country names at the end of each line series. This is a Vega-Lite text mark layer added to the temporal_single spec.

#### [MODIFY] [viz_config.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/viz_config.py)

- In `build_temporal_single_spec` (line ~1669): when `country_count > 1`, add a text layer anchored to the last data point of each series:
  ```json
  {"mark": {"type": "text", "align": "left", "dx": 4},
   "encoding": {"x": {"...: last year"}, "y": {"...: last value"},
                "text": {"field": "country"}, "color": {"field": "country"}}}
  ```
- Guard with `country_count <= 8` to avoid label clutter in high-cardinality cases.
- Use `transform: [{"filter": "datum.year == max_year"}]` or `aggregate` to select last point.

> [!CAUTION]
> End labels can overflow the chart viewport. Test at 680px width with 8 countries before enabling. If overflow detected, fall back to a right-aligned legend instead.

**Files**: `src/data360/viz_config.py`  
**Test**: `uv run python evals/explore_chart_types.py --strategy temporal_single --count 6 --seed 7`

---

### Phase 8 — Correlation Temporal Auto-Routing [HIGH IMPACT, MEDIUM RISK]

> [!NOTE]
> `TwoIndicatorRule` (line 1061–1068) forces `small_multiples` for 2 indicators + multi-country + multi-year. `correlation_temporal` is only reachable via explicit `chart_type="scatter"`. This is the root cause of 19 low-scoring reports (avg 6.3).

#### [MODIFY] [viz_config.py](file:///Users/rafaelmacalaba/WBG/data360-mcp/src/data360/viz_config.py)

- In `TwoIndicatorRule.evaluate()` (line ~1061): add a branch before the `small_multiples` fallback:
  ```python
  if ctx.year_count > 1 and ctx.country_count > 1:
      if ctx.country_count <= 8 and ctx.year_count <= 8:
          # Prefer connected scatter over small multiples for readable comparison
          return StrategyResult(
              ChartStrategy.CORRELATION_TEMPORAL,
              f"2 indicators, {ctx.country_count} economies, {ctx.year_count} years → connected scatter",
              indicator_cols=ctx.ind_cols,
              color_dim="country",
          )
      # Falls through to small_multiples for high-cardinality
  ```

> [!WARNING]
> This changes default routing behavior for existing users. Any caller that currently gets `small_multiples` for 2-indicator multi-country multi-year data will now get `correlation_temporal` instead. Run the full test suite before merging.

**Files**: `src/data360/viz_config.py` (lines 1061–1068)  
**Test**: `uv run pytest tests/ -x && uv run python evals/explore_chart_types.py --strategy correlation_temporal --count 4 --seed 42`

---

## Verification Plan

### After Each Phase

```bash
# Re-run critique extractor to measure improvement
uv run python evals/extract_critique_insights.py

# Run targeted exploration for the fixed strategy
uv run python evals/explore_chart_types.py --strategy <name> --count 6 --seed 42

# Run full test suite
uv run pytest tests/ -x -q
```

### After All Phases (Full Regression)

```bash
# Full 26-scenario stress test
uv run python evals/explore_chart_types.py --count 26 --seed 42

# Full 52-scenario run for statistical confidence
uv run python evals/explore_chart_types.py --count 52 --seed 99
```

**Pass criterion**: Overall average ≥ 8.5/10 across all strategies.

---

## Progress Log

| Phase | Status | Baseline Score | Post-Fix Score | Delta | Notes |
|---|---|---|---|---|---|
| 1 — Tooltip standardization | `[ ]` | 7.0 | — | — | |
| 2 — Legend suppression audit | `[ ]` | — | — | — | |
| 3 — Axis title completeness | `[ ]` | — | — | — | |
| 4 — Sort order on bars | `[ ]` | — | — | — | |
| 5 — Year gap dashing | `[ ]` | — | — | — | |
| 6 — Zero line all strategies | `[ ]` | — | — | — | |
| 7 — Country end labels | `[ ]` | — | — | — | |
| 8 — Correlation temporal routing | `[ ]` | — | — | — | |

---

## Learnings

_Updated as each phase completes._

**2026-07-04** — Initial analysis from 363 reports:
- Tooltip (66%) and axis (65%) issues are the highest-frequency complaints but at avg 7.9–8.0, meaning they are minor deductions per chart, not showstoppers.
- Legend suppression (31%, avg 7.5) is more damaging because it hides the key categorical encoding when there is no y-axis label to compensate.
- `correlation_temporal` routing failure is rare (5%) but catastrophic when it happens (avg 6.3 vs 8.6 for correlation). Root cause is a single `if` branch in `TwoIndicatorRule`.
- Choropleth has a persistent country-ISO-to-topojson mismatch problem that is separate from routing — the spec is generated correctly but some ISO codes don't resolve in the Vega topojson. This needs a lookup table fix, not a routing fix.
- The `LineYearGapStrokeDashRule` is in the rules list but may not traverse layered specs — needs verification before assuming it works for multi-indicator charts.
