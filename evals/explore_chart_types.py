"""
explore_chart_types.py
======================

Stress-tests the Data360 visualization engine by generating random scenario
combinations across all chart strategies and diverse data shapes.

Covers all 13 generator paths (11 ChartStrategy values + 2 chained variants):
  temporal_single, temporal_multi_indicator, correlation, correlation_temporal,
  cross_sectional, distribution, breakdown_comparison, small_multiples,
  heatmap, choropleth, chained_rank, chained_compare, chained_summarize

Usage
-----
    uv run python evals/explore_chart_types.py              # 26 scenarios (2 per strategy)
    uv run python evals/explore_chart_types.py --count 52   # 4 per strategy
    uv run python evals/explore_chart_types.py --seed 42    # reproducible run
    uv run python evals/explore_chart_types.py --strategy choropleth
    uv run python evals/explore_chart_types.py --list       # list strategy names
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import random
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv
    _repo = Path(__file__).parent.parent
    load_dotenv(_repo / ".env.evals", override=False)
    load_dotenv(_repo / ".env", override=False)
except ImportError:
    pass

from evals.test_viz_scorer import (
    run_scenario,
    save_report,
    REPORTS_DIR,
    SERVER_UP,
    OPENAI_KEY_SET,
    MCP_BASE_URL,
)

# ---------------------------------------------------------------------------
# Indicator pools
# ---------------------------------------------------------------------------

INDICATORS: dict[str, dict] = {
    "gdp_growth":           {"db": "WB_WDI", "id": "WB_WDI_NY_GDP_MKTP_KD_ZG",  "name": "GDP growth (annual %)"},
    "gdp_per_capita":       {"db": "WB_WDI", "id": "WB_WDI_NY_GDP_PCAP_KD",      "name": "GDP per capita (const 2015 USD)"},
    "inflation_cpi":        {"db": "WB_WDI", "id": "WB_WDI_FP_CPI_TOTL_ZG",      "name": "Inflation CPI (annual %)"},
    "trade_gdp":            {"db": "WB_WDI", "id": "WB_WDI_NE_TRD_GNFS_ZS",      "name": "Trade (% of GDP)"},
    "fdi_net":              {"db": "WB_WDI", "id": "WB_WDI_BX_KLT_DINV_WD_GD_ZS","name": "FDI net inflows (% of GDP)"},
    "imf_gdp_growth":       {"db": "IMF_WEO","id": "IMF_WEO_NGDP_RPCH",           "name": "Real GDP growth (IMF WEO)"},
    "life_expectancy":      {"db": "WB_WDI", "id": "WB_WDI_SP_DYN_LE00_IN",       "name": "Life expectancy at birth (years)"},
    "under5_mortality":     {"db": "WB_WDI", "id": "WB_WDI_SH_DYN_MORT",          "name": "Under-5 mortality rate (per 1000)"},
    "poverty_headcount":    {"db": "WB_WDI", "id": "WB_WDI_SI_POV_DDAY",          "name": "Poverty headcount ratio at $2.15/day (%)"},
    "school_enrollment":    {"db": "WB_WDI", "id": "WB_WDI_SE_PRM_ENRR",          "name": "Primary school enrollment, gross (%)"},
    "internet_users":       {"db": "WB_WDI", "id": "WB_WDI_IT_NET_USER_ZS",       "name": "Internet users (% of population)"},
    "co2_per_capita":       {"db": "WB_ESG", "id": "WB_ESG_EN_ATM_CO2E_PC",       "name": "CO2 emissions per capita (metric tons)"},
    "renewable_energy":     {"db": "WB_ESG", "id": "WB_ESG_EG_FEC_RNEW_ZS",       "name": "Renewable energy (% total final consumption)"},
    "access_electricity":   {"db": "WB_WDI", "id": "WB_WDI_EG_ELC_ACCS_ZS",       "name": "Access to electricity (% of population)"},
    "public_employment":    {"db": "WB_WWBI", "id": "WB_WWBI_BI_EMP_TOTL_PB",        "name": "Public employment (% of total employment)"},
}

INDICATOR_PAIRS: list[dict] = [
    {"ids": ["WB_WDI_NY_GDP_MKTP_KD_ZG", "WB_WDI_FP_CPI_TOTL_ZG"],
     "dbs": ["WB_WDI", "WB_WDI"], "name": "GDP Growth vs Inflation"},
    {"ids": ["WB_WDI_SP_DYN_LE00_IN", "WB_WDI_NY_GDP_PCAP_KD"],
     "dbs": ["WB_WDI", "WB_WDI"], "name": "Life Expectancy vs GDP per Capita"},
    {"ids": ["WB_WDI_NE_TRD_GNFS_ZS", "WB_WDI_BX_KLT_DINV_WD_GD_ZS"],
     "dbs": ["WB_WDI", "WB_WDI"], "name": "Trade openness vs FDI Inflows"},
    {"ids": ["WB_ESG_EN_ATM_CO2E_PC", "WB_ESG_EG_FEC_RNEW_ZS"],
     "dbs": ["WB_ESG", "WB_ESG"], "name": "CO2 Emissions vs Renewable Energy"},
]

# ---------------------------------------------------------------------------
# Country pools
# ---------------------------------------------------------------------------

SMALL_GROUPS: list[list[str]] = [
    ["USA", "CHN"], ["DEU", "FRA"], ["BRA", "ARG"], ["IND", "PAK"],
    ["NGA", "ZAF"], ["KEN", "ETH"], ["TUR", "EGY"], ["CAN", "AUS"],
    ["JPN", "KOR"], ["GBR", "IRL"], ["MEX", "COL"], ["IDN", "MYS"],
]

MEDIUM_GROUPS: list[list[str]] = [
    ["BRA", "RUS", "IND", "CHN", "ZAF"],
    ["USA", "GBR", "DEU", "FRA", "JPN", "CAN", "ITA"],
    ["IDN", "MYS", "THA", "PHL", "VNM", "SGP"],
    ["BRA", "MEX", "COL", "ARG", "CHL", "PER"],
    ["KEN", "ETH", "TZA", "UGA", "RWA", "MOZ"],
    ["SAU", "ARE", "EGY", "IRN", "ISR", "MAR"],
    ["SWE", "NOR", "FIN", "DNK", "ISL"],
    ["IND", "BGD", "PAK", "LKA", "NPL"],
]

LARGE_GROUPS: list[list[str]] = [
    ["USA","CHN","DEU","GBR","JPN","FRA","ITA","CAN","AUS","KOR","MEX","BRA","IND","IDN","ZAF","TUR","SAU","ARG","RUS"],
    ["NGA","ZAF","KEN","ETH","TZA","GHA","UGA","DZA","AGO","MOZ","CMR","CIV","MDG","MLI","BFA"],
    ["DEU","FRA","GBR","ITA","ESP","POL","ROU","NLD","BEL","SWE","CZE","HUN","AUT","CHE","PRT","GRC"],
    ["CHN","JPN","KOR","IND","IDN","THA","MYS","PHL","VNM","BGD","PAK","AUS","NZL","SGP","MNG"],
    ["USA","CAN","MEX","BRA","COL","ARG","CHL","PER","VEN","ECU","BOL","PRY","URY","GTM","CUB"],
]

WIDE_GROUPS: list[list[str]] = [
    ["CHN","JPN","KOR","IDN","THA","MYS","PHL","VNM","MMR","KHM","SGP","MNG","AUS","NZL","LAO","BGD","PAK","LKA"],
    ["NGA","ZAF","KEN","ETH","TZA","GHA","UGA","DZA","AGO","MOZ","CMR","CIV","MDG","MLI","BFA","NER","SEN","ZMB","ZWE","RWA"],
    ["DEU","FRA","GBR","ITA","ESP","POL","ROU","NLD","BEL","SWE","RUS","UKR","KAZ","UZB","TUR","AZE","ARM","GEO","MDA","BLR"],
    ["BRA","MEX","COL","ARG","CHL","PER","VEN","ECU","BOL","PRY","URY","GTM","CUB","DOM","HND","SLV","NIC","CRI","PAN","HTI"],
]

SHORT_RANGES  = [(2015, 2020), (2018, 2022), (2017, 2021), (2019, 2022)]
MEDIUM_RANGES = [(2010, 2020), (2010, 2022), (2005, 2020), (2012, 2022)]
LONG_RANGES   = [(2000, 2022), (1990, 2020), (2000, 2020), (1995, 2022)]
SINGLE_YEARS  = [2015, 2018, 2019, 2020, 2021, 2022]
RANK_YEARS    = [2018, 2019, 2020, 2021]

# ---------------------------------------------------------------------------
# Scenario generators
# ---------------------------------------------------------------------------

_counter = [0]

def _next_id(strategy: str) -> str:
    _counter[0] += 1
    tag = strategy.replace("_", "")[:10]
    return f"rnd_{_counter[0]:03d}_{tag}"


def make_temporal_single(rng: random.Random) -> dict:
    keys = [k for k in INDICATORS if k != "public_employment"]
    ind = INDICATORS[rng.choice(keys)]
    countries = rng.choice(SMALL_GROUPS + MEDIUM_GROUPS[:4])
    start, end = rng.choice(MEDIUM_RANGES + LONG_RANGES)
    sid = _next_id("temporal_single")
    return {
        "id": sid, "mode": "viz",
        "label": f"Temporal — {ind['name']} ({len(countries)}c, {start}-{end})",
        "description": (
            f"Time series of {ind['name']} for {', '.join(countries)} "
            f"from {start} to {end}. Expect: temporal_single line chart."
        ),
        "database_id": ind["db"], "indicator_id": ind["id"],
        "country_code": ";".join(countries),
        "start_year": start, "end_year": end,
    }


def make_temporal_multi_indicator(rng: random.Random) -> dict:
    pair = rng.choice(INDICATOR_PAIRS)
    country = rng.choice(["USA","DEU","BRA","IND","CHN","KEN","NGA","JPN","GBR","FRA"])
    start, end = rng.choice(MEDIUM_RANGES)
    sid = _next_id("temporal_multi_ind")
    return {
        "id": sid, "mode": "viz",
        "label": f"Multi-Ind — {pair['name']} in {country} ({start}-{end})",
        "description": (
            f"Two-indicator comparison in {country}: {pair['name']} "
            f"from {start} to {end}. Expect: temporal_multi_indicator layered lines."
        ),
        "database_ids": pair["dbs"], "indicator_ids": pair["ids"],
        "country_code": country,
        "start_year": start, "end_year": end,
    }


def make_correlation(rng: random.Random) -> dict:
    pair = rng.choice(INDICATOR_PAIRS[:3])
    countries = rng.choice(LARGE_GROUPS)
    year = rng.choice(SINGLE_YEARS)
    sid = _next_id("correlation")
    return {
        "id": sid, "mode": "viz",
        "label": f"Correlation — {pair['name']}, {len(countries)}c ({year})",
        "description": (
            f"Scatter of {pair['name']} across {len(countries)} countries in {year}. "
            f"Expect: correlation scatter."
        ),
        "database_ids": pair["dbs"], "indicator_ids": pair["ids"],
        "country_code": ";".join(countries),
        "start_year": year, "end_year": year,
    }


def make_correlation_temporal(rng: random.Random) -> dict:
    pair = rng.choice(INDICATOR_PAIRS[:3])
    countries = rng.choice(MEDIUM_GROUPS[:5])
    start, end = rng.choice(SHORT_RANGES)
    sid = _next_id("corr_temporal")
    return {
        "id": sid, "mode": "viz",
        "label": f"Corr-Temporal — {pair['name']}, {len(countries)}c ({start}-{end})",
        "description": (
            f"Connected scatter of {pair['name']} for {len(countries)} countries "
            f"from {start} to {end}. Expect: correlation_temporal (connected scatter)."
        ),
        "database_ids": pair["dbs"], "indicator_ids": pair["ids"],
        "country_code": ";".join(countries),
        "start_year": start, "end_year": end,
        # Explicit hint required: TwoIndicatorRule defaults multi-country multi-year
        # to small_multiples; 'scatter' triggers ExplicitScatterRule instead.
        "chart_type": "scatter",
    }


def make_cross_sectional(rng: random.Random) -> dict:
    ind = INDICATORS[rng.choice(list(INDICATORS.keys()))]
    countries = rng.choice(SMALL_GROUPS[4:] + MEDIUM_GROUPS[:5])
    year = rng.choice(SINGLE_YEARS)
    sid = _next_id("cross_section")
    return {
        "id": sid, "mode": "viz",
        "label": f"Cross-Sectional — {ind['name']}, {len(countries)}c ({year})",
        "description": (
            f"Bar chart comparing {ind['name']} across {', '.join(countries)} in {year}. "
            f"Expect: cross_sectional horizontal bar."
        ),
        "database_id": ind["db"], "indicator_id": ind["id"],
        "country_code": ";".join(countries),
        "start_year": year, "end_year": year,
    }


def make_distribution(rng: random.Random) -> dict:
    keys = [k for k in INDICATORS if k not in ("public_employment",)]
    ind = INDICATORS[rng.choice(keys)]
    countries = rng.choice(LARGE_GROUPS)
    year = rng.choice(SINGLE_YEARS)
    sid = _next_id("distribution")
    return {
        "id": sid, "mode": "viz",
        "label": f"Distribution — {ind['name']}, {len(countries)}c ({year})",
        "description": (
            f"Distribution / strip plot of {ind['name']} across {len(countries)} countries in {year}. "
            f"Expect: distribution strip/beeswarm."
        ),
        "database_id": ind["db"], "indicator_id": ind["id"],
        "country_code": ";".join(countries),
        "start_year": year, "end_year": year,
        "chart_type": "distribution",
    }


def make_breakdown_comparison(rng: random.Random) -> dict:
    countries = rng.choice(SMALL_GROUPS[:6])
    start, end = rng.choice(SHORT_RANGES)
    sid = _next_id("breakdown")
    return {
        "id": sid, "mode": "viz",
        "label": f"Breakdown — WWBI public employment, {', '.join(countries)} ({start}-{end})",
        "description": (
            f"Grouped bar of WWBI public employment (WB_WWBI) disaggregated by sector "
            f"for {', '.join(countries)} from {start} to {end}. "
            f"Expect: breakdown_comparison."
        ),
        "database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": ";".join(countries),
        "start_year": start, "end_year": end,
    }


def make_small_multiples(rng: random.Random) -> dict:
    countries = rng.choice(MEDIUM_GROUPS[:5])
    start, end = rng.choice(MEDIUM_RANGES[:2])
    sid = _next_id("small_mult")
    return {
        "id": sid, "mode": "viz",
        "label": f"Small Multiples — WWBI employment, {len(countries)}c ({start}-{end})",
        "description": (
            f"Faceted chart of WWBI public employment (WB_WWBI, with sector breakdown) "
            f"across {len(countries)} countries from {start} to {end}. "
            f"Expect: small_multiples faceted panels."
        ),
        "database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": ";".join(countries),
        "start_year": start, "end_year": end,
    }


def make_heatmap(rng: random.Random) -> dict:
    hmap_keys = ["gdp_growth","inflation_cpi","life_expectancy","renewable_energy",
                 "access_electricity","co2_per_capita"]
    ind = INDICATORS[rng.choice(hmap_keys)]
    pool = rng.choice(LARGE_GROUPS)
    n = rng.randint(12, min(18, len(pool)))
    countries = pool[:n]
    start = rng.choice([2010, 2011, 2012])
    span = rng.choice([8, 9, 10])
    end = start + span
    sid = _next_id("heatmap")
    return {
        "id": sid, "mode": "viz",
        "label": f"Heatmap — {ind['name']}, {len(countries)}c x {span+1}yr",
        "description": (
            f"Country x year heatmap of {ind['name']} for {len(countries)} countries "
            f"from {start} to {end}. Expect: heatmap."
        ),
        "database_id": ind["db"], "indicator_id": ind["id"],
        "country_code": ";".join(countries),
        "start_year": start, "end_year": end,
        # Explicit hint: HeatmapRule only fires at >20 countries by default;
        # ExplicitHeatmapRule fires on hint='heatmap' with any country count.
        "chart_type": "heatmap",
    }


def make_choropleth(rng: random.Random) -> dict:
    choro_keys = ["gdp_per_capita","life_expectancy","poverty_headcount",
                  "co2_per_capita","renewable_energy","access_electricity","internet_users"]
    ind = INDICATORS[rng.choice(choro_keys)]
    wide = rng.choice(WIDE_GROUPS)
    year = rng.choice(SINGLE_YEARS)
    sid = _next_id("choropleth")
    return {
        "id": sid, "mode": "viz",
        "label": f"Choropleth — {ind['name']}, {len(wide)}c ({year})",
        "description": (
            f"Geographic map of {ind['name']} across {len(wide)} countries in {year}. "
            f"Expect: choropleth."
        ),
        "database_id": ind["db"], "indicator_id": ind["id"],
        "country_code": ";".join(wide),
        "start_year": year, "end_year": year,
        # Explicit hint: HighCardinalityCrossSectionalRule only fires at >20 countries;
        # ExplicitMapRule fires on hint='map' regardless of count.
        "chart_type": "map",
    }


def make_chained_rank(rng: random.Random) -> dict:
    rank_keys = ["gdp_per_capita","life_expectancy","co2_per_capita",
                 "renewable_energy","internet_users","under5_mortality"]
    ind = INDICATORS[rng.choice(rank_keys)]
    countries = rng.choice(LARGE_GROUPS)
    year = rng.choice(RANK_YEARS)
    order = rng.choice(["desc", "asc"])
    top_n = rng.choice([8, 10, 12])
    direction = "highest" if order == "desc" else "lowest"
    sid = _next_id("chained_rank")
    return {
        "id": sid, "mode": "chained_viz", "data_tool": "rank",
        "label": f"Chained Rank — {direction} {top_n} {ind['name']} ({year})",
        "description": (
            f"Rank {len(countries)} countries by {ind['name']} in {year}; "
            f"chart top {top_n} ({direction}) as sorted bar."
        ),
        "database_id": ind["db"], "indicator_id": ind["id"],
        "country_code": ";".join(countries),
        "order": order, "top_n": top_n, "rank_year": year,
        "chart_title": f"{'Top' if order == 'desc' else 'Bottom'} {top_n}: {ind['name']} ({year})",
    }


def make_chained_compare(rng: random.Random) -> dict:
    comp_keys = ["gdp_growth","gdp_per_capita","life_expectancy",
                 "inflation_cpi","co2_per_capita","access_electricity"]
    ind = INDICATORS[rng.choice(comp_keys)]
    countries = rng.choice(SMALL_GROUPS + MEDIUM_GROUPS[:4])
    start, end = rng.choice(MEDIUM_RANGES)
    sid = _next_id("chained_comp")
    return {
        "id": sid, "mode": "chained_viz", "data_tool": "compare",
        "label": f"Chained Compare — {ind['name']}, {len(countries)}c ({start}-{end})",
        "description": (
            f"Compare {', '.join(countries)} on {ind['name']} from {start} to {end}; "
            f"chart as multi-series line."
        ),
        "database_id": ind["db"], "indicator_id": ind["id"],
        "country_code": ";".join(countries),
        "start_year": start, "end_year": end, "include_time_series": True,
        "chart_title": f"{ind['name']}: {' vs '.join(countries[:3])} ({start}-{end})",
    }


def make_chained_summarize(rng: random.Random) -> dict:
    summ_keys = ["gdp_growth","poverty_headcount","life_expectancy",
                 "under5_mortality","renewable_energy","imf_gdp_growth"]
    ind = INDICATORS[rng.choice(summ_keys)]
    countries = rng.choice(SMALL_GROUPS[:8] + MEDIUM_GROUPS[:3])
    start, end = rng.choice(SHORT_RANGES + MEDIUM_RANGES[:2])
    sid = _next_id("chained_summ")
    return {
        "id": sid, "mode": "chained_viz", "data_tool": "summarize",
        "label": f"Chained Summarize — {ind['name']} trend, {len(countries)}c ({start}-{end})",
        "description": (
            f"Summarize {ind['name']} for {', '.join(countries)} from {start} to {end}; "
            f"chart the trend."
        ),
        "database_id": ind["db"], "indicator_id": ind["id"],
        "country_code": ";".join(countries),
        "start_year": start, "end_year": end,
        "chart_title": f"{ind['name']} Trend ({start}-{end})",
    }


# ---------------------------------------------------------------------------
# Strategy dispatch
# ---------------------------------------------------------------------------

STRATEGY_NAMES = [
    "temporal_single", "temporal_multi_indicator", "correlation",
    "correlation_temporal", "cross_sectional", "distribution",
    "breakdown_comparison", "small_multiples", "heatmap", "choropleth",
    "chained_rank", "chained_compare", "chained_summarize",
]

_GENERATORS: dict[str, Any] = {
    "temporal_single":        make_temporal_single,
    "temporal_multi_indicator": make_temporal_multi_indicator,
    "correlation":            make_correlation,
    "correlation_temporal":   make_correlation_temporal,
    "cross_sectional":        make_cross_sectional,
    "distribution":           make_distribution,
    "breakdown_comparison":   make_breakdown_comparison,
    "small_multiples":        make_small_multiples,
    "heatmap":                make_heatmap,
    "choropleth":             make_choropleth,
    "chained_rank":           make_chained_rank,
    "chained_compare":        make_chained_compare,
    "chained_summarize":      make_chained_summarize,
}


def generate_scenarios(
    count: int,
    seed: int | None,
    strategy_filter: str | None,
) -> list[dict]:
    rng = random.Random(seed)
    _counter[0] = 0  # reset sequential ID

    if strategy_filter:
        if strategy_filter not in _GENERATORS:
            raise ValueError(
                f"Unknown strategy {strategy_filter!r}. "
                f"Options: {list(_GENERATORS.keys())}"
            )
        active = {strategy_filter: _GENERATORS[strategy_filter]}
    else:
        active = _GENERATORS

    cycle = list(active.keys())
    return [_GENERATORS[cycle[i % len(cycle)]](rng) for i in range(count)]


# ---------------------------------------------------------------------------
# Run loop
# ---------------------------------------------------------------------------

async def run_exploration(scenarios: list[dict], pass_threshold: float) -> list[dict]:
    results: list[dict] = []

    for i, scen in enumerate(scenarios, 1):
        sid = scen["id"]
        print(f"\n({i}/{len(scenarios)}) [{sid}] {scen['label']}")
        print(f"  mode={scen.get('mode','viz')} | db={scen.get('database_id','multi')}")
        try:
            res = await run_scenario(scen)
            score = res.get("score")
            critique = res.get("critique")
            err = res.get("error")

            save_report(
                scenario_id=sid,
                scenario=scen,
                viz_result={
                    "database_id":   scen.get("database_id"),
                    "indicator_id":  scen.get("indicator_id"),
                    "indicator_name": scen.get("label"),
                    "chart_url":     res.get("chart_url"),
                    "strategy":      res.get("strategy"),
                    "reason":        res.get("reason"),
                    "error":         err,
                    "search_result": None,
                },
                score=score,
                critique=critique,
                tool_data=res.get("tool_data"),
            )

            status = (
                "PASS" if (score or 0) >= pass_threshold
                else ("WARN" if (score or 0) >= 5.0 else "FAIL")
            )
            print(f"  Score: {score}/10 [{status}] | Strategy: {res.get('strategy','N/A')}")
            if err:
                print(f"  Error: {err}")

            results.append({
                "id": sid, "label": scen["label"],
                "mode": scen.get("mode", "viz"),
                "actual_strategy": res.get("strategy"),
                "score": score, "status": status, "error": err,
            })
        except Exception as exc:
            exc_type = type(exc).__name__
            exc_msg = str(exc) if str(exc) else f"<empty — {exc_type}>"
            print(f"  EXCEPTION ({exc_type}): {exc_msg}")
            results.append({
                "id": sid, "label": scen["label"],
                "mode": scen.get("mode", "viz"),
                "actual_strategy": None,
                "score": None, "status": "ERROR", "error": exc_msg,
            })

    return results


def print_summary(results: list[dict], pass_threshold: float) -> None:
    print("\n" + "=" * 70)
    print("EXPLORATION SUMMARY")
    print("=" * 70)

    by_strat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        strat = r.get("actual_strategy") or "unknown"
        by_strat[strat].append(r)

    print(f"\n{'Strategy':<32} {'N':>3} {'Avg Score':>10} {'Pass%':>7}")
    print("-" * 56)
    all_scores: list[float] = []
    for strat in sorted(by_strat):
        grp = by_strat[strat]
        scores = [r["score"] for r in grp if r["score"] is not None]
        avg = sum(scores) / len(scores) if scores else 0.0
        pct = 100 * len([s for s in scores if s >= pass_threshold]) / len(scores) if scores else 0.0
        print(f"  {strat:<30} {len(grp):>3} {avg:>9.1f} {pct:>6.0f}%")
        all_scores.extend(scores)

    total_avg = sum(all_scores) / len(all_scores) if all_scores else 0.0
    print("-" * 56)
    print(f"  {'OVERALL':<30} {len(results):>3} {total_avg:>9.1f}")

    scored = sorted(
        [r for r in results if r["score"] is not None],
        key=lambda r: r["score"], reverse=True
    )
    if scored:
        print("\nTop 3:")
        for r in scored[:3]:
            print(f"  [{r['score']}/10] {r['label']}")
        print("Bottom 3:")
        for r in scored[-3:]:
            print(f"  [{r['score']}/10] {r['label']}")

    errors = [r for r in results if r["status"] == "ERROR"]
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for r in errors:
            print(f"  {r['id']}: {r['error']}")

    print("=" * 70)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Stress-test Data360 viz engine across all chart strategies."
    )
    parser.add_argument("--count",     type=int,   default=26,
        help="Number of scenarios to generate. Default 26 = 2 per strategy.")
    parser.add_argument("--seed",      type=int,   default=None,
        help="Random seed (omit for truly random).")
    parser.add_argument("--strategy",  choices=STRATEGY_NAMES, default=None,
        help="Limit to one strategy.")
    parser.add_argument("--threshold", type=float, default=7.0,
        help="Pass threshold (default 7.0).")
    parser.add_argument("--list",      action="store_true",
        help="List strategies and exit.")
    args = parser.parse_args()

    if args.list:
        for s in STRATEGY_NAMES:
            print(f"  {s}")
        return

    if not SERVER_UP:
        print(f"ERROR: MCP server not reachable at {MCP_BASE_URL}")
        print("Start with: uv run poe serve")
        sys.exit(1)
    if not OPENAI_KEY_SET:
        print("ERROR: OPENAI_API_KEY not set in .env.evals")
        sys.exit(1)

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\nData360 Chart Type Exploration")
    print(f"  Date      : {now}")
    print(f"  Count     : {args.count} scenarios")
    print(f"  Seed      : {args.seed if args.seed is not None else 'random'}")
    print(f"  Strategy  : {args.strategy or 'all'}")
    print(f"  Pass @    : {args.threshold}/10")

    scenarios = generate_scenarios(args.count, args.seed, args.strategy)

    print(f"\nGenerated {len(scenarios)} scenarios:")
    for i, s in enumerate(scenarios, 1):
        print(f"  {i:2}. [{s['id']}] {s['label']}")

    results = asyncio.run(run_exploration(scenarios, args.threshold))
    print_summary(results, args.threshold)


if __name__ == "__main__":
    main()
