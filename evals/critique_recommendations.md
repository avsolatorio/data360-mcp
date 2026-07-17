# Viz Engine Critique Recommendations

> Auto-generated from **363 eval reports** (avg score: **7.8/10**).

> Use these to prioritize improvements in `viz_config.py` and `visualization.py`.


## Score Distribution

| Score | Count | Bar |
|---|---|---|
| 0/10 | 3 | ▓▓▓ |
| 2/10 | 8 | ▓▓▓▓▓▓▓▓ |
| 3/10 | 17 | ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ |
| 4/10 | 14 | ▓▓▓▓▓▓▓▓▓▓▓▓▓▓ |
| 5/10 | 8 | ▓▓▓▓▓▓▓▓ |
| 6/10 | 21 | ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ |
| 7/10 | 71 | ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ |
| 8/10 | 93 | ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ |
| 9/10 | 115 | ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ |
| 10/10 | 13 | ▓▓▓▓▓▓▓▓▓▓▓▓▓ |

## Issue Frequency Table

| Priority | Issue | Count | % Reports | Avg Score | Fix |
|---|---|---|---|---|---|
| **HIGH** | `axis_issues` | 236 | 65.0% | 8.0 | Ensure axis titles set via unit metadata; run FixValueAxisEncodingRule on all strategies |
| **HIGH** | `legend_suppressed` | 111 | 30.6% | 7.5 | Audit all strategies for unintentional legend=None; only suppress for truly single-series charts |
| **HIGH** | `correlation_routed_as_small_multiples` | 19 | 5.2% | 6.3 | TwoIndicatorRule: prefer CORRELATION_TEMPORAL for 2-ind + ≤8 countries + ≤6 years without hint |
| **MEDIUM** | `tooltip_incomplete` | 240 | 66.1% | 7.9 | Standardize tooltip template: country, year, value+unit, indicator_name |
| **MEDIUM** | `title_missing_or_weak` | 107 | 29.5% | 7.9 | Always set chart title using indicator_name + country context template; never leave None |
| **MEDIUM** | `color_encoding_weak` | 100 | 27.5% | 7.4 | Use WB palette with ≥8 distinct colors; apply ApplyWBStyleRule to all strategies |
| **MEDIUM** | `year_gap_lines` | 47 | 12.9% | 6.7 | Ensure LineYearGapStrokeDashRule applies to ALL temporal strategies, not only temporal_single |
| **MEDIUM** | `sort_order_missing` | 22 | 6.1% | 7.6 | Cross-sectional and chained-rank bars must have sort: {field: value, order: descending} by default |
| **MEDIUM** | `unit_missing` | 4 | 1.1% | 5.0 | Propagate UNIT_MULT from metadata through to axis labelExpr and tooltip format string |
| **LOW** | `country_label_missing` | 99 | 27.3% | 7.4 | End-of-line country labels for multi-series lines via labelExpr on countryName field |
| **INFO** | `data_mismatch` | 18 | 5.0% | 4.4 | Verify indicator_id in viz call matches search result; add assertion in run_viz_pipeline |
| **INFO** | `empty_or_sparse_data` | 3 | 0.8% | 0.3 | Pre-flight: return user-facing error if row_count=0 before calling viz pipeline |

---

## Detailed Recommendations

### `axis_issues` — [HIGH]
**Frequency**: 236/363 (65.0%)  
**Avg score when flagged**: 8.0/10  
**Fix**: Ensure axis titles set via unit metadata; run FixValueAxisEncodingRule on all strategies

**Representative critiques**:

> [8.2/10] *The spec is strongly aligned with the request: it uses the searched WB indicator ID for GDP growth, follows the search → disaggregation → viz sequence, and the temporal_single routing matches a 2015–2023 trend comparison for BRA/ARG/MEX. Data relevance is high because the values are GDP annual % growth for Brazil, Argentina, and Mexico, though the *

> [8.4/10] *The output strongly matches the intent: it uses the WB_WDI GDP growth indicator for Brazil, Argentina, and Mexico over 2015–2023, and the routing follows search → disaggregation → viz with the real indicator ID WB_WDI_NY_GDP_MKTP_KD_ZG and the temporal_single strategy. A line chart is an appropriate fit for 3 countries across 9 years. Encodings are*

> [8.5/10] *The spec aligns well with the question: it uses GDP growth data for Brazil, Argentina, and Mexico over 2015–2023, and the temporal_single routing is appropriate for one indicator across 9 years and 3 countries. Chart type fit is strong with a multi-series line chart, and the encodings are mostly correct: year is temporal, value quantitative, countr*


### `legend_suppressed` — [HIGH]
**Frequency**: 111/363 (30.6%)  
**Avg score when flagged**: 7.5/10  
**Fix**: Audit all strategies for unintentional legend=None; only suppress for truly single-series charts

**Representative critiques**:

> [8.0/10] *Data and routing largely match the request: the spec uses the searched WB indicator ID for GDP growth, follows search → disaggregation → viz, and shows Brazil, Argentina, and Mexico over 2015–2023 with an appropriate temporal_single line chart. Grammar is mostly sound with temporal x, quantitative y, nominal color, and structured tooltips, plus goo*

> [8.5/10] *The spec aligns well with the question: it uses GDP growth data for Brazil, Argentina, and Mexico over 2015–2023, and the temporal_single routing is appropriate for one indicator across 9 years and 3 countries. Chart type fit is strong with a multi-series line chart, and the encodings are mostly correct: year is temporal, value quantitative, countr*

> [8.9/10] *The spec aligns well with the scenario: it uses GDP growth data for Brazil, Argentina, and Mexico over 2015–2023, and the multi-series line chart matches the temporal_single strategy for 3 countries across 9 years. Disaggregation is correctly encoded with country on color, and the grammar is mostly sound with temporal x, quantitative y, and useful *


### `correlation_routed_as_small_multiples` — [HIGH]
**Frequency**: 19/363 (5.2%)  
**Avg score when flagged**: 6.3/10  
**Fix**: TwoIndicatorRule: prefer CORRELATION_TEMPORAL for 2-ind + ≤8 countries + ≤6 years without hint

**Representative critiques**:

> [2.7/10] *The data mostly matches the requested scope: Kenya, 2020, with age and sex breakdown for indicator WB_HNP_SP_POP_5Y, but the spec introduces mixed unit_measure values and even includes a stray Percentage record, triggering an unnecessary small-multiples split by unit. The chart type is a poor fit: instead of the expected diverging population pyrami*

> [6.6/10] *The spec uses the correct inflation indicator title and the requested 2015–2023 time span, and the countries shown are within the listed G20 economies. A multi-series line chart is acceptable per the routing strategy, but it is a weak fit for 19 countries × 9 years compared with the expected heatmap or small multiples, so readability suffers. Disag*

> [7.9/10] *The spec matches the correlation scenario well with a scatter plot using quantitative x for GDP per capita and quantitative y for life expectancy, and it keeps the data to 2022 for the requested countries. It also encodes the country breakdown with color and adds useful tooltips, titles, and axis labels. However, data relevance is slightly off beca*


### `tooltip_incomplete` — [MEDIUM]
**Frequency**: 240/363 (66.1%)  
**Avg score when flagged**: 7.9/10  
**Fix**: Standardize tooltip template: country, year, value+unit, indicator_name

**Representative critiques**:

> [8.2/10] *The spec is strongly aligned with the request: it uses the searched WB indicator ID for GDP growth, follows the search → disaggregation → viz sequence, and the temporal_single routing matches a 2015–2023 trend comparison for BRA/ARG/MEX. Data relevance is high because the values are GDP annual % growth for Brazil, Argentina, and Mexico, though the *

> [8.4/10] *The output strongly matches the intent: it uses the WB_WDI GDP growth indicator for Brazil, Argentina, and Mexico over 2015–2023, and the routing follows search → disaggregation → viz with the real indicator ID WB_WDI_NY_GDP_MKTP_KD_ZG and the temporal_single strategy. A line chart is an appropriate fit for 3 countries across 9 years. Encodings are*

> [8.5/10] *The spec aligns well with the question: it uses GDP growth data for Brazil, Argentina, and Mexico over 2015–2023, and the temporal_single routing is appropriate for one indicator across 9 years and 3 countries. Chart type fit is strong with a multi-series line chart, and the encodings are mostly correct: year is temporal, value quantitative, countr*


### `title_missing_or_weak` — [MEDIUM]
**Frequency**: 107/363 (29.5%)  
**Avg score when flagged**: 7.9/10  
**Fix**: Always set chart title using indicator_name + country context template; never leave None

**Representative critiques**:

> [8.0/10] *Data and routing largely match the request: the spec uses the searched WB indicator ID for GDP growth, follows search → disaggregation → viz, and shows Brazil, Argentina, and Mexico over 2015–2023 with an appropriate temporal_single line chart. Grammar is mostly sound with temporal x, quantitative y, nominal color, and structured tooltips, plus goo*

> [8.4/10] *The output strongly matches the intent: it uses the WB_WDI GDP growth indicator for Brazil, Argentina, and Mexico over 2015–2023, and the routing follows search → disaggregation → viz with the real indicator ID WB_WDI_NY_GDP_MKTP_KD_ZG and the temporal_single strategy. A line chart is an appropriate fit for 3 countries across 9 years. Encodings are*

> [8.5/10] *The spec aligns well with the question: it uses GDP growth data for Brazil, Argentina, and Mexico over 2015–2023, and the temporal_single routing is appropriate for one indicator across 9 years and 3 countries. Chart type fit is strong with a multi-series line chart, and the encodings are mostly correct: year is temporal, value quantitative, countr*


### `color_encoding_weak` — [MEDIUM]
**Frequency**: 100/363 (27.5%)  
**Avg score when flagged**: 7.4/10  
**Fix**: Use WB palette with ≥8 distinct colors; apply ApplyWBStyleRule to all strategies

**Representative critiques**:

> [4.1/10] *Data relevance is weak because the question asks for male vs female labor force participation in India from 2010–2022 broken down by sex, but the spec only contains Female records and does not show Male. Chart type fit is acceptable as a temporal line chart matches the 13-year trend. Grammar/readability are mixed: x as temporal and y quantitative a*

> [8.0/10] *Data and routing largely match the request: the spec uses the searched WB indicator ID for GDP growth, follows search → disaggregation → viz, and shows Brazil, Argentina, and Mexico over 2015–2023 with an appropriate temporal_single line chart. Grammar is mostly sound with temporal x, quantitative y, nominal color, and structured tooltips, plus goo*

> [8.9/10] *The spec aligns well with the scenario: it uses GDP growth data for Brazil, Argentina, and Mexico over 2015–2023, and the multi-series line chart matches the temporal_single strategy for 3 countries across 9 years. Disaggregation is correctly encoded with country on color, and the grammar is mostly sound with temporal x, quantitative y, and useful *


### `year_gap_lines` — [MEDIUM]
**Frequency**: 47/363 (12.9%)  
**Avg score when flagged**: 6.7/10  
**Fix**: Ensure LineYearGapStrokeDashRule applies to ALL temporal strategies, not only temporal_single

**Representative critiques**:

> [4.1/10] *Data relevance is weak because the question asks for male vs female labor force participation in India from 2010–2022 broken down by sex, but the spec only contains Female records and does not show Male. Chart type fit is acceptable as a temporal line chart matches the 13-year trend. Grammar/readability are mixed: x as temporal and y quantitative a*

> [8.0/10] *Data and routing largely match the request: the spec uses the searched WB indicator ID for GDP growth, follows search → disaggregation → viz, and shows Brazil, Argentina, and Mexico over 2015–2023 with an appropriate temporal_single line chart. Grammar is mostly sound with temporal x, quantitative y, nominal color, and structured tooltips, plus goo*

> [8.9/10] *The spec strongly matches the scenario: it uses GDP annual growth data for Brazil, Argentina, and Mexico across 2015–2023, and the multi-series line chart is the correct fit for a temporal_single strategy with 3 countries over 9 years. Disaggregation is encoded well with color by country, and the grammar is solid with temporal x, quantitative y, an*


### `sort_order_missing` — [MEDIUM]
**Frequency**: 22/363 (6.1%)  
**Avg score when flagged**: 7.6/10  
**Fix**: Cross-sectional and chained-rank bars must have sort: {field: value, order: descending} by default

**Representative critiques**:

> [8.5/10] *The spec aligns well with the question: it uses GDP growth data for Brazil, Argentina, and Mexico over 2015–2023, and the temporal_single routing is appropriate for one indicator across 9 years and 3 countries. Chart type fit is strong with a multi-series line chart, and the encodings are mostly correct: year is temporal, value quantitative, countr*

> [8.7/10] *The spec aligns well with the scenario: it uses the life expectancy indicator title, includes the five requested countries (China, Japan, Korea, Rep., Viet Nam, Thailand), and covers the 2000–2022 range in the data. The line mark is appropriate for a multi-country temporal trend, and country is correctly encoded by color with a clear legend. Gramma*

> [8.8/10] *The spec aligns well with the scenario: it uses a multi-series line chart for the GDP growth indicator across Brazil, Argentina, and Mexico over 2015–2023, with country correctly encoded by color and year on the x-axis. Grammar is strong overall, with appropriate temporal/quantitative/nominal encodings, useful tooltips, and clear title, subtitle, y*


### `unit_missing` — [MEDIUM]
**Frequency**: 4/363 (1.1%)  
**Avg score when flagged**: 5.0/10  
**Fix**: Propagate UNIT_MULT from metadata through to axis labelExpr and tooltip format string

**Representative critiques**:

> [0.4/10] *The output has no usable data: rankings is empty, total_with_data and total_requested are 0, year is null, and metadata/unit are missing. It does not match the requested task of ranking the bottom 10 G20 countries for WB_WDI_EN_ATM_CO2E_PC in ascending order, since it returns order='desc' and an indicator metadata error instead of country results. *

> [8.1/10] *The output has strong data presence with a non-empty 2022 snapshot, all five requested BRICS countries (BRA, RUS, IND, CHN, ZAF), correct indicator metadata for WB_WDI_NY_GDP_PCAP_KD, and plausible GDP per capita values with a coherent ranking from China to India. It is also labeled and interpretable, including country names, ranks, values, spread *

> [9.0/10] *The chart aligns closely with the pipeline: it uses the correct 2020 top-10 G20 countries from the retrieved ranking, preserves descending order via a horizontal bar chart with y sorted by -x, and maps values accurately with only trivial rounding differences for China, Germany, and South Africa. The chart type fits the stated cross-sectional strate*


### `country_label_missing` — [LOW]
**Frequency**: 99/363 (27.3%)  
**Avg score when flagged**: 7.4/10  
**Fix**: End-of-line country labels for multi-series lines via labelExpr on countryName field

**Representative critiques**:

> [8.0/10] *Data and routing largely match the request: the spec uses the searched WB indicator ID for GDP growth, follows search → disaggregation → viz, and shows Brazil, Argentina, and Mexico over 2015–2023 with an appropriate temporal_single line chart. Grammar is mostly sound with temporal x, quantitative y, nominal color, and structured tooltips, plus goo*

> [8.5/10] *The spec aligns well with the question: it uses GDP growth data for Brazil, Argentina, and Mexico over 2015–2023, and the temporal_single routing is appropriate for one indicator across 9 years and 3 countries. Chart type fit is strong with a multi-series line chart, and the encodings are mostly correct: year is temporal, value quantitative, countr*

> [8.9/10] *The spec aligns well with the scenario: it uses GDP growth data for Brazil, Argentina, and Mexico over 2015–2023, and the multi-series line chart matches the temporal_single strategy for 3 countries across 9 years. Disaggregation is correctly encoded with country on color, and the grammar is mostly sound with temporal x, quantitative y, and useful *


### `data_mismatch` — [INFO]
**Frequency**: 18/363 (5.0%)  
**Avg score when flagged**: 4.4/10  
**Fix**: Verify indicator_id in viz call matches search result; add assertion in run_viz_pipeline

**Representative critiques**:

> [3.4/10] *The spec uses the correct poverty indicator title and years within 2020–2022, but the data relevance is weak because it includes only 6 of the 10 requested countries and mixes different latest years instead of producing a clean latest-year cross-sectional view. Chart type fit is poor: the scenario explicitly expects a horizontal bar chart sorted by*

> [4.1/10] *Data relevance is weak because the question asks for male vs female labor force participation in India from 2010–2022 broken down by sex, but the spec only contains Female records and does not show Male. Chart type fit is acceptable as a temporal line chart matches the 13-year trend. Grammar/readability are mixed: x as temporal and y quantitative a*

> [8.0/10] *The spec uses the correct country (India), includes both male and female labor force participation series, and covers 2010–2022, so data relevance is strong. A two-series line chart is the right choice for the temporal_multi_indicator strategy, and sex is clearly encoded by color. Grammar is mostly sound with temporal x, quantitative y, and tooltip*


### `empty_or_sparse_data` — [INFO]
**Frequency**: 3/363 (0.8%)  
**Avg score when flagged**: 0.3/10  
**Fix**: Pre-flight: return user-facing error if row_count=0 before calling viz pipeline

**Representative critiques**:

> [0.1/10] *The response contains no usable data: rankings is empty, total_with_data and total_requested are 0, year and metadata are null, and the tool returned an error about missing metadata for indicator WB_WDI_EN_ATM_CO2E_PC. It does not match the requested scenario of ranking the bottom 10 CO2 emitters per capita within the G20, since the order is incorr*

> [0.3/10] *The response includes some metadata and labels, but it fails the core task: there is no ranking data, total_with_data is 0, rankings is empty, and an error is returned. It is incorrect for the requested bottom 10 G20 CO2 emitters because the order is desc instead of the requested asc, the year is null despite YEAR:auto, and no countries or values a*

> [0.4/10] *The output has no usable data: rankings is empty, total_with_data and total_requested are 0, year is null, and metadata/unit are missing. It does not match the requested task of ranking the bottom 10 G20 countries for WB_WDI_EN_ATM_CO2E_PC in ascending order, since it returns order='desc' and an indicator metadata error instead of country results. *


---

## Verbatim Judge Observations by Topic

### Tooltip

- [2.1] tooltips, but axis semantics are incorrect and the legend is suppressed.
- [2.7] tooltips, yet the temporal x-axis for a single year and line connections across many age groups are conceptually wrong.
- [2.9] tooltip, and axis styling.
- [3.2] tooltips, and styled axes, but the chart does not actually visualize trade openness vs FDI relationship over time.
- [3.2] tooltips, though legend suppression on color hurts interpretation.
- [3.4] tooltips, though the sparse, uneven country-year records make the line encoding misleading for ranking.

### Axis

- [2.1] axis and value on the y-axis, effectively plotting a time series.
- [2.1] axis semantics are incorrect and the legend is suppressed.
- [2.3] axis and a single generic value field on the y-axis, so life expectancy is not plotted against GDP per capita.
- [2.3] axis labeling is misleading and there is no legend use despite color encoding by country being redundant under faceting.
- [2.7] axis and male/female on opposite x-sides, it uses two line charts over time despite only one year being present.
- [2.7] axis, so the key disaggregation is not properly represented.

### Legend

- [2.1] legend is suppressed.
- [2.3] legend use despite color encoding by country being redundant under faceting.
- [2.7] legend, missing age axis, and incorrect structure make the visualization fail the scenario intent.
- [2.9] legend for Urban/Rural.
- [3.2] legend suppression on color hurts interpretation.
- [3.2] legend for urbanisation.

### Title

- [2.1] title, subtitle, styling, and tooltips, but axis semantics are incorrect and the legend is suppressed.
- [2.3] title, subtitle, and styled axes, but axis labeling is misleading and there is no legend use despite color encoding by country being redundant under faceting.
- [2.7] title and styling, but the missing legend, missing age axis, and incorrect structure make the visualization fail the scenario intent.
- [2.9] title, tooltip, and axis styling.
- [3.2] title, subtitle, tooltips, and styled axes, but the chart does not actually visualize trade openness vs FDI relationship over time.
- [3.2] title/subtitle are present and styling is polished, but the subtitle only names France, axes lack clear titles, and there is no visible legend for urbanisation.

### Color

- [2.3] color encoding by country being redundant under faceting.
- [2.7] color, but age is not placed on a primary visual axis, so the key disaggregation is not properly represented.
- [2.9] color is mapped to country rather than residence, so there is no meaningful disaggregation encoding or legend for Urban/Rural.
- [3.2] color by urbanisation, which matches the routing strategy, but the test case expected disaggregation by sector and there is no sector field.
- [3.2] color hurts interpretation.
- [3.3] color is mapped to country rather than residence.

### Sort

- [3.4] sorted by value for Sub-Saharan Africa latest year, but the output is a multi-series line chart driven by the temporal_single route.
- [3.4] sorting recommendation.
- [3.6] sort countries on a y-axis or present the requested cross-sectional ranking.
- [3.8] sorted ranking layout.
- [3.9] sorted by value with countries on the y-axis, while the output is a multi-series line chart driven by the temporal_single routing.
- [3.9] sorting for cross-sectional comparison.

### Unit

- [2.7] unit_measure values and even includes a stray Percentage record, triggering an unnecessary small-multiples split by unit.
- [6.5] unit inconsistency: one record is Male 80 years old and over with unit_measure 'Percentage' and value 0.
- [6.5] unit but no facet is implemented.
- [6.5] unit_measure, creating a mixed-scale bug for the pyramid.
- [6.8] units, and clear styling, but the x-axis title is null and the many country colors with legend suppressed add unnecessary encoding for a single-series cross-section.
- [7.1] unit subtitle, though the reversed ordering makes that label somewhat misleading.

### Source

- [7.6] source data, so data mapping and chart type fit are strong.
- [8.5] source data without obvious mutation or loss.
- [8.6] source data and no evident mutations or omissions.
- [8.6] source attribution to WDI.
- [8.8] source (WDI) and latest-year rank framing noted in the retrieved snapshot.
- [8.9] source attribution from WDI.

### Data Gap

- [0.1] missing metadata for indicator WB_WDI_EN_ATM_CO2E_PC.
- [4.0] missing from the plotted data (notably Portugal is not requested, but Moldova etc.
- [6.5] missing country-year observations.
- [7.6] missing, and the data include odd duplicated/start-end year pairings within period groups that could create confusing line connections for the colored series.
- [7.6] missing several years, which weakens data relevance.
- [7.9] missing years for some country-series combinations, which may reflect incomplete relevance or coverage.
