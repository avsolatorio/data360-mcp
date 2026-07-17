"""
explore_v2.py
=============

Comprehensive open exploration of the Data360 visualization engine.
52 hand-curated scenarios in 8 difficulty tiers:

  TRIVIAL   - single country, single indicator, short timespan
  EASY      - 2-5 countries, common indicators, standard date ranges
  MODERATE  - multi-country comparisons, cross-sectional ranking, heatmap
  HARD      - scale-incompatible multi-indicator (regression case), dual-db
  STRESS    - 3-4 indicators, very long ranges, 15+ countries
  CHAINED   - rank > viz, compare > viz, summarize > viz
  BOUNDARY  - edge cases: 1 year, single country scatter, max-country choropleth
  SPECIAL   - breakdown disaggregation, explicit chart-type overrides

Usage
-----
    uv run python evals/explore_v2.py
    uv run python evals/explore_v2.py --tier hard
    uv run python evals/explore_v2.py --dry-run      # list scenarios, no API calls
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path
from collections import defaultdict

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

SCENARIOS: list[dict] = [

    # =========================================================================
    # TIER 1: TRIVIAL
    # =========================================================================
    {
        "id": "t01_trivial_gdp_usa_5yr", "tier": "trivial", "mode": "viz",
        "label": "TRIVIAL: GDP growth - USA, 5 years (line)",
        "description": "GDP growth (annual %) for the United States from 2018 to 2022. "
                       "Simple single-country temporal line. Expect: temporal_single.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG",
        "country_code": "USA", "start_year": 2018, "end_year": 2022,
    },
    {
        "id": "t02_trivial_life_exp_jpn_3yr", "tier": "trivial", "mode": "viz",
        "label": "TRIVIAL: Life expectancy - Japan, 3 years (line)",
        "description": "Life expectancy at birth for Japan 2020-2022. Minimal data, single country. Expect: temporal_single.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
        "country_code": "JPN", "start_year": 2020, "end_year": 2022,
    },
    {
        "id": "t03_trivial_internet_deu_1yr", "tier": "trivial", "mode": "viz",
        "label": "TRIVIAL: Internet users - Germany, single year bar",
        "description": "Internet users (% population) in Germany in 2022. Single year, single country. Expect: cross_sectional bar.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_IT_NET_USER_ZS",
        "country_code": "DEU", "start_year": 2022, "end_year": 2022,
    },
    {
        "id": "t04_trivial_poverty_2cntry", "tier": "trivial", "mode": "viz",
        "label": "TRIVIAL: Poverty headcount - India vs Pakistan, 5 years",
        "description": "Poverty headcount at $2.15/day for India and Pakistan 2015-2019. Simple 2-country time series. Expect: temporal_single.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_SI_POV_DDAY",
        "country_code": "IND;PAK", "start_year": 2015, "end_year": 2019,
    },

    # =========================================================================
    # TIER 2: EASY
    # =========================================================================
    {
        "id": "e01_easy_gdp_brics_10yr", "tier": "easy", "mode": "viz",
        "label": "EASY: GDP per capita - BRICS, 10 years (multi-line)",
        "description": "GDP per capita (constant 2015 USD) for Brazil, Russia, India, China, South Africa 2012-2022. Expect: temporal_single multi-series line.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
        "country_code": "BRA;RUS;IND;CHN;ZAF", "start_year": 2012, "end_year": 2022,
    },
    {
        "id": "e02_easy_inflation_latam_10yr", "tier": "easy", "mode": "viz",
        "label": "EASY: Inflation - Latin America 5 countries, 10 years",
        "description": "CPI inflation for Brazil, Mexico, Colombia, Argentina, Chile 2012-2022. Expect: temporal_single multi-series line.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG",
        "country_code": "BRA;MEX;COL;ARG;CHL", "start_year": 2012, "end_year": 2022,
    },
    {
        "id": "e03_easy_renewable_nordics", "tier": "easy", "mode": "viz",
        "label": "EASY: Renewable energy - Nordic 5, 2010-2022",
        "description": "Renewable energy share for Sweden, Norway, Finland, Denmark, Iceland 2010-2022. Expect: temporal_single.",
        "database_id": "WB_ESG", "indicator_id": "WB_ESG_EG_FEC_RNEW_ZS",
        "country_code": "SWE;NOR;FIN;DNK;ISL", "start_year": 2010, "end_year": 2022,
    },
    {
        "id": "e04_easy_schoolenroll_sea_2022", "tier": "easy", "mode": "viz",
        "label": "EASY: School enrollment - SE Asia 6 countries, 2022 bar",
        "description": "Primary school enrollment gross % for Indonesia, Malaysia, Thailand, Philippines, Vietnam, Singapore in 2022. Expect: cross_sectional bar.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_PRM_ENRR",
        "country_code": "IDN;MYS;THA;PHL;VNM;SGP", "start_year": 2022, "end_year": 2022,
    },
    {
        "id": "e05_easy_co2_g7_longterm", "tier": "easy", "mode": "viz",
        "label": "EASY: CO2 per capita - G7, 1990-2022 long run",
        "description": "CO2 emissions per capita for the G7 nations from 1990 to 2022. Long historical trend, 7 countries. Expect: temporal_single.",
        "database_id": "WB_ESG", "indicator_id": "WB_ESG_EN_ATM_CO2E_PC",
        "country_code": "USA;GBR;DEU;FRA;JPN;CAN;ITA", "start_year": 1990, "end_year": 2022,
    },
    {
        "id": "e06_easy_access_electricity_africa", "tier": "easy", "mode": "viz",
        "label": "EASY: Electricity access - East Africa 5, 2010-2022",
        "description": "Access to electricity for Kenya, Ethiopia, Tanzania, Uganda, Rwanda 2010-2022. Expect: temporal_single.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_ELC_ACCS_ZS",
        "country_code": "KEN;ETH;TZA;UGA;RWA", "start_year": 2010, "end_year": 2022,
    },

    # =========================================================================
    # TIER 3: MODERATE
    # =========================================================================
    {
        "id": "m01_moderate_gdp_crosssection_g20_2022", "tier": "moderate", "mode": "viz",
        "label": "MODERATE: GDP per capita - G20 cross-section 2022 (bar)",
        "description": "Bar chart of GDP per capita for 18 G20 economies in 2022. 19 countries cross-section. Expect: cross_sectional or distribution.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
        "country_code": "USA;CHN;DEU;GBR;JPN;FRA;ITA;CAN;AUS;KOR;MEX;BRA;IND;IDN;ZAF;TUR;SAU;ARG;RUS",
        "start_year": 2022, "end_year": 2022,
    },
    {
        "id": "m02_moderate_heatmap_gdpgrowth_latam", "tier": "moderate", "mode": "viz",
        "label": "MODERATE: Heatmap - GDP growth, 12 LatAm x 10 years",
        "description": "Country x year heatmap of GDP growth for 12 Latin American countries 2012-2022. Expect: heatmap.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG",
        "country_code": "BRA;MEX;COL;ARG;CHL;PER;VEN;ECU;BOL;PRY;URY;GTM",
        "start_year": 2012, "end_year": 2022, "chart_type": "heatmap",
    },
    {
        "id": "m03_moderate_choropleth_lifeexp_africa", "tier": "moderate", "mode": "viz",
        "label": "MODERATE: Choropleth - Life expectancy, 20 African countries 2020",
        "description": "Geographic map of life expectancy across 20 African nations in 2020. Expect: choropleth.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
        "country_code": "NGA;ZAF;KEN;ETH;TZA;GHA;UGA;DZA;AGO;MOZ;CMR;CIV;MDG;MLI;BFA;NER;SEN;ZMB;ZWE;RWA",
        "start_year": 2020, "end_year": 2020, "chart_type": "map",
    },
    {
        "id": "m04_moderate_corr_scatter_gdp_life_2020", "tier": "moderate", "mode": "viz",
        "label": "MODERATE: Scatter - GDP per capita vs Life expectancy, 20 countries 2020",
        "description": "Scatter of GDP per capita vs life expectancy across 20 diverse countries in 2020. Expect: correlation scatter.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NY_GDP_PCAP_KD", "WB_WDI_SP_DYN_LE00_IN"],
        "country_code": "USA;CHN;IND;BRA;DEU;NGA;KEN;ETH;JPN;FRA;IDN;ZAF;MEX;COL;ARG;GBR;TUR;EGY;PHL;VNM",
        "start_year": 2020, "end_year": 2020,
    },
    {
        "id": "m05_moderate_fdi_asia_heatmap", "tier": "moderate", "mode": "viz",
        "label": "MODERATE: Heatmap - FDI inflows, Asian 14 x 8 years",
        "description": "Heatmap of FDI net inflows for 14 Asian economies 2015-2022. Expect: heatmap.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_BX_KLT_DINV_WD_GD_ZS",
        "country_code": "CHN;JPN;KOR;IND;IDN;THA;MYS;PHL;VNM;BGD;PAK;SGP;MNG;AUS",
        "start_year": 2015, "end_year": 2022, "chart_type": "heatmap",
    },
    {
        "id": "m06_moderate_imf_gdp_sea_line", "tier": "moderate", "mode": "viz",
        "label": "MODERATE: IMF real GDP growth - SE Asia 5, 2018-2024",
        "description": "IMF WEO real GDP growth for Indonesia, Malaysia, Philippines, Thailand, Vietnam 2018-2024. Expect: temporal_single.",
        "database_id": "IMF_WEO", "indicator_id": "IMF_WEO_NGDP_RPCH",
        "country_code": "IDN;MYS;PHL;THA;VNM", "start_year": 2018, "end_year": 2024,
    },

    # =========================================================================
    # TIER 4: HARD
    # =========================================================================
    {
        "id": "h01_hard_gdp_pcap_vs_growth_ken_uga_tza", "tier": "hard", "mode": "viz",
        "label": "HARD [REGRESSION]: GDP per capita vs GDP growth - Kenya/Uganda/Tanzania, 15yr",
        "description": "Compare GDP per capita (constant 2015 USD) and GDP growth (annual %) for Kenya, Uganda, Tanzania 2010-2024. Scale-incompatible (~1000 vs ~5%), 3 countries, 15 years. Expected: small_multiples (facet=indicator, color=country) - 2 panels, shared legend. This is the exact regression case fixed Jul 2026.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NY_GDP_PCAP_KD", "WB_WDI_NY_GDP_MKTP_KD_ZG"],
        "country_code": "KEN;UGA;TZA", "start_year": 2010, "end_year": 2024,
    },
    {
        "id": "h02_hard_inflation_vs_gdpgrowth_brics_15yr", "tier": "hard", "mode": "viz",
        "label": "HARD: Inflation vs GDP growth - BRICS, 15 years",
        "description": "CPI inflation vs GDP growth for BRICS 2008-2022. Both percentages but ranges differ. Expect: small_multiples or temporal_multi_indicator.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_FP_CPI_TOTL_ZG", "WB_WDI_NY_GDP_MKTP_KD_ZG"],
        "country_code": "BRA;RUS;IND;CHN;ZAF", "start_year": 2008, "end_year": 2022,
    },
    {
        "id": "h03_hard_lifeexp_vs_gdppcap_scatter_temporal", "tier": "hard", "mode": "viz",
        "label": "HARD: Connected scatter - Life exp vs GDP per capita, 5 countries 2015-2020",
        "description": "Connected scatter (trajectory) of life expectancy vs GDP per capita for USA, CHN, IND, BRA, NGA from 2015 to 2020. Expect: correlation_temporal.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_SP_DYN_LE00_IN", "WB_WDI_NY_GDP_PCAP_KD"],
        "country_code": "USA;CHN;IND;BRA;NGA", "start_year": 2015, "end_year": 2020,
        "chart_type": "scatter",
    },
    {
        "id": "h04_hard_co2_vs_renewable_g7_20yr", "tier": "hard", "mode": "viz",
        "label": "HARD: CO2 vs Renewable energy - G7, 20 years",
        "description": "CO2 per capita vs renewable energy share for G7 from 2000-2020. Scale-incompatible (tons vs %), 7 countries, 21 years. Expect: small_multiples 2 panels.",
        "database_ids": ["WB_ESG", "WB_ESG"],
        "indicator_ids": ["WB_ESG_EN_ATM_CO2E_PC", "WB_ESG_EG_FEC_RNEW_ZS"],
        "country_code": "USA;GBR;DEU;FRA;JPN;CAN;ITA", "start_year": 2000, "end_year": 2020,
    },
    {
        "id": "h05_hard_trade_vs_fdi_sea_10yr", "tier": "hard", "mode": "viz",
        "label": "HARD: Trade openness vs FDI - SE Asia 6, 10 years",
        "description": "Trade vs FDI net inflows for Indonesia, Malaysia, Thailand, Philippines, Vietnam, Singapore 2012-2022. Expect: small_multiples or scatter.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NE_TRD_GNFS_ZS", "WB_WDI_BX_KLT_DINV_WD_GD_ZS"],
        "country_code": "IDN;MYS;THA;PHL;VNM;SGP", "start_year": 2012, "end_year": 2022,
    },
    {
        "id": "h06_hard_gdp_pcap_vs_growth_usa_dualaxis", "tier": "hard", "mode": "viz",
        "label": "HARD: GDP per capita vs GDP growth - USA only, 20 years (dual-axis)",
        "description": "GDP per capita (constant USD) and GDP growth for USA 2000-2020. Single country, scale-incompatible. Expect: temporal_multi_indicator layered separate Y-axes.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NY_GDP_PCAP_KD", "WB_WDI_NY_GDP_MKTP_KD_ZG"],
        "country_code": "USA", "start_year": 2000, "end_year": 2020,
    },
    {
        "id": "h07_hard_school_vs_poverty_africa_scatter", "tier": "hard", "mode": "viz",
        "label": "HARD: School enrollment vs Poverty - 19 African countries scatter 2018",
        "description": "Scatter of primary school enrollment vs poverty headcount across 19 African countries in 2018. Expect: correlation scatter.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_SE_PRM_ENRR", "WB_WDI_SI_POV_DDAY"],
        "country_code": "NGA;ZAF;KEN;ETH;TZA;GHA;UGA;DZA;AGO;MOZ;CMR;CIV;MDG;MLI;BFA;NER;SEN;ZMB;RWA",
        "start_year": 2018, "end_year": 2018,
    },

    # =========================================================================
    # TIER 5: STRESS
    # =========================================================================
    {
        "id": "s01_stress_3ind_usa_longrun", "tier": "stress", "mode": "viz",
        "label": "STRESS: 3 indicators - USA: GDP growth + Inflation + Trade, 1995-2022",
        "description": "Three-indicator comparison for USA from 1995 to 2022: GDP growth, CPI inflation, and trade openness. 3 indicators, 28 years. Expect: temporal_multi_indicator or small_multiples.",
        "database_ids": ["WB_WDI", "WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NY_GDP_MKTP_KD_ZG", "WB_WDI_FP_CPI_TOTL_ZG", "WB_WDI_NE_TRD_GNFS_ZS"],
        "country_code": "USA", "start_year": 1995, "end_year": 2022,
    },
    {
        "id": "s02_stress_choropleth_africa_20cntry", "tier": "stress", "mode": "viz",
        "label": "STRESS: Choropleth - 20 African countries GDP growth 2010 map",
        "description": "Geographic choropleth of GDP growth for 20 African countries in 2010. Expect: choropleth.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG",
        "country_code": "NGA;ZAF;KEN;ETH;TZA;GHA;UGA;DZA;AGO;MOZ;CMR;CIV;MDG;MLI;BFA;NER;SEN;ZMB;ZWE;RWA",
        "start_year": 2010, "end_year": 2010, "chart_type": "map",
    },
    {
        "id": "s03_stress_heatmap_lifeexp_europe_16x12", "tier": "stress", "mode": "viz",
        "label": "STRESS: Heatmap - Life expectancy, 16 European x 12 years",
        "description": "Country x year heatmap of life expectancy for 16 European countries 2010-2022. Dense grid. Expect: heatmap.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
        "country_code": "DEU;FRA;GBR;ITA;ESP;POL;ROU;NLD;BEL;SWE;CZE;HUN;AUT;CHE;PRT;GRC",
        "start_year": 2010, "end_year": 2022, "chart_type": "heatmap",
    },
    {
        "id": "s04_stress_3ind_india_scale_mix", "tier": "stress", "mode": "viz",
        "label": "STRESS: 3 indicators - India: Life exp + Under-5 mortality + GDP pcap, 2000-2022",
        "description": "India 2000-2022: life expectancy (years), under-5 mortality (per 1000), GDP per capita (USD). Extreme scale mix. Expect: small_multiples 3 panels.",
        "database_ids": ["WB_WDI", "WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_SP_DYN_LE00_IN", "WB_WDI_SH_DYN_MORT", "WB_WDI_NY_GDP_PCAP_KD"],
        "country_code": "IND", "start_year": 2000, "end_year": 2022,
    },
    {
        "id": "s05_stress_distribution_co2_europe_20", "tier": "stress", "mode": "viz",
        "label": "STRESS: Distribution - CO2 per capita, 20 European countries 2019",
        "description": "Distribution/strip chart of CO2 per capita across 20 European countries in 2019. Large N, single year. Expect: distribution.",
        "database_id": "WB_ESG", "indicator_id": "WB_ESG_EN_ATM_CO2E_PC",
        "country_code": "DEU;FRA;GBR;ITA;ESP;POL;ROU;NLD;BEL;SWE;RUS;UKR;KAZ;UZB;TUR;AZE;ARM;GEO;MDA;BLR",
        "start_year": 2019, "end_year": 2019, "chart_type": "distribution",
    },

    # =========================================================================
    # TIER 6: CHAINED
    # =========================================================================
    {
        "id": "c01_chained_rank_gdppcap_top10_g20_2022", "tier": "chained",
        "mode": "chained_viz", "data_tool": "rank",
        "label": "CHAINED: Rank - Top 10 GDP per capita (G20) 2022",
        "description": "Rank 19 G20 economies by GDP per capita in 2022; chart top 10 highest as sorted bar.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
        "country_code": "USA;CHN;DEU;GBR;JPN;FRA;ITA;CAN;AUS;KOR;MEX;BRA;IND;IDN;ZAF;TUR;SAU;ARG;RUS",
        "order": "desc", "top_n": 10, "rank_year": 2022,
        "chart_title": "Top 10 GDP per Capita (G20 Economies, 2022)",
    },
    {
        "id": "c02_chained_rank_under5mort_bottom10_africa", "tier": "chained",
        "mode": "chained_viz", "data_tool": "rank",
        "label": "CHAINED: Rank - Bottom 10 under-5 mortality (Africa) 2020",
        "description": "Rank 20 African countries by under-5 mortality in 2020; chart bottom 10 (best performers).",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_SH_DYN_MORT",
        "country_code": "NGA;ZAF;KEN;ETH;TZA;GHA;UGA;DZA;AGO;MOZ;CMR;CIV;MDG;MLI;BFA;NER;SEN;ZMB;ZWE;RWA",
        "order": "asc", "top_n": 10, "rank_year": 2020,
        "chart_title": "10 Best Under-5 Mortality Rates in Africa (2020)",
    },
    {
        "id": "c03_chained_compare_renewables_nordics", "tier": "chained",
        "mode": "chained_viz", "data_tool": "compare",
        "label": "CHAINED: Compare - Renewable energy, Nordic 5, 2010-2022",
        "description": "Compare renewable energy share for Sweden, Norway, Finland, Denmark, Iceland 2010-2022 then chart as multi-line.",
        "database_id": "WB_ESG", "indicator_id": "WB_ESG_EG_FEC_RNEW_ZS",
        "country_code": "SWE;NOR;FIN;DNK;ISL",
        "start_year": 2010, "end_year": 2022, "include_time_series": True,
        "chart_title": "Renewable Energy Share: Nordic Countries (2010-2022)",
    },
    {
        "id": "c04_chained_compare_inflation_g7", "tier": "chained",
        "mode": "chained_viz", "data_tool": "compare",
        "label": "CHAINED: Compare - Inflation, G7 2018-2023",
        "description": "Compare CPI inflation for G7 countries from 2018 to 2023; chart as multi-line time series.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG",
        "country_code": "USA;GBR;DEU;FRA;JPN;CAN;ITA",
        "start_year": 2018, "end_year": 2023, "include_time_series": True,
        "chart_title": "G7 Inflation Rates (2018-2023)",
    },
    {
        "id": "c05_chained_summarize_co2_brics", "tier": "chained",
        "mode": "chained_viz", "data_tool": "summarize",
        "label": "CHAINED: Summarize - CO2 BRICS trend 2010-2022",
        "description": "Summarize CO2 per capita trend for BRICS nations from 2010 to 2022, then visualize.",
        "database_id": "WB_ESG", "indicator_id": "WB_ESG_EN_ATM_CO2E_PC",
        "country_code": "BRA;RUS;IND;CHN;ZAF",
        "start_year": 2010, "end_year": 2022,
        "chart_title": "CO2 Emissions per Capita: BRICS (2010-2022)",
    },
    {
        "id": "c06_chained_rank_internet_asia_top12", "tier": "chained",
        "mode": "chained_viz", "data_tool": "rank",
        "label": "CHAINED: Rank - Top 12 internet users, Asia 2021",
        "description": "Rank 15 Asian countries by internet users in 2021; chart top 12 as sorted bar.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_IT_NET_USER_ZS",
        "country_code": "CHN;JPN;KOR;IND;IDN;THA;MYS;PHL;VNM;BGD;PAK;AUS;NZL;SGP;MNG",
        "order": "desc", "top_n": 12, "rank_year": 2021,
        "chart_title": "Top 12 Internet Access in Asia (2021)",
    },

    # =========================================================================
    # TIER 7: BOUNDARY
    # =========================================================================
    {
        "id": "b01_boundary_single_year_single_country", "tier": "boundary", "mode": "viz",
        "label": "BOUNDARY: Single point - USA GDP growth 2020 only",
        "description": "GDP growth for USA in 2020 only. Single data point. Expect: cross_sectional bar.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG",
        "country_code": "USA", "start_year": 2020, "end_year": 2020,
    },
    {
        "id": "b02_boundary_2country_1year_bar", "tier": "boundary", "mode": "viz",
        "label": "BOUNDARY: 2 countries, 1 year - India vs China GDP per capita 2022",
        "description": "GDP per capita for India and China in 2022. Minimal: 2 countries, single year. Expect: cross_sectional bar.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
        "country_code": "IND;CHN", "start_year": 2022, "end_year": 2022,
    },
    {
        "id": "b03_boundary_2ind_1country_1year", "tier": "boundary", "mode": "viz",
        "label": "BOUNDARY: 2 indicators, 1 country, 1 year - Germany GDP growth + Inflation 2022",
        "description": "GDP growth and CPI inflation for Germany in 2022 only. 2 indicators, single point. Expect: temporal_multi_indicator bar.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NY_GDP_MKTP_KD_ZG", "WB_WDI_FP_CPI_TOTL_ZG"],
        "country_code": "DEU", "start_year": 2022, "end_year": 2022,
    },
    {
        "id": "b04_boundary_very_long_range_60yr", "tier": "boundary", "mode": "viz",
        "label": "BOUNDARY: Very long range - Life expectancy USA 1960-2022 (60 years)",
        "description": "Life expectancy for USA from 1960 to 2022. 62 data points, single country. Expect: temporal_single line.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
        "country_code": "USA", "start_year": 1960, "end_year": 2022,
    },
    {
        "id": "b05_boundary_max_countries_choropleth", "tier": "boundary", "mode": "viz",
        "label": "BOUNDARY: Max-country choropleth - Internet access, 20 Americas 2021",
        "description": "Internet users for 20 countries across the Americas in 2021. Large N for a geographic map. Expect: choropleth.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_IT_NET_USER_ZS",
        "country_code": "USA;CAN;MEX;BRA;COL;ARG;CHL;PER;VEN;ECU;BOL;PRY;URY;GTM;CUB;DOM;HND;SLV;NIC;CRI",
        "start_year": 2021, "end_year": 2021, "chart_type": "map",
    },
    {
        "id": "b06_boundary_corr_temporal_2cntry_8yr", "tier": "boundary", "mode": "viz",
        "label": "BOUNDARY: Connected scatter - 2 countries, exactly 8 years (threshold edge)",
        "description": "Connected scatter of GDP growth vs inflation for USA and DEU 2015-2022 (exactly 8 years). Tests CORRELATION_TEMPORAL threshold boundary.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_NY_GDP_MKTP_KD_ZG", "WB_WDI_FP_CPI_TOTL_ZG"],
        "country_code": "USA;DEU", "start_year": 2015, "end_year": 2022,
        "chart_type": "scatter",
    },
    {
        "id": "b07_boundary_crossdb_imf_vs_wdi", "tier": "boundary", "mode": "viz",
        "label": "BOUNDARY: Cross-database - IMF real GDP growth vs WDI CPI, USA 2010-2022",
        "description": "IMF WEO real GDP growth rate and WDI CPI inflation for USA 2010-2022. Two different source databases (IMF_WEO + WB_WDI). Expect: temporal_multi_indicator.",
        "database_ids": ["IMF_WEO", "WB_WDI"],
        "indicator_ids": ["IMF_WEO_NGDP_RPCH", "WB_WDI_FP_CPI_TOTL_ZG"],
        "country_code": "USA", "start_year": 2010, "end_year": 2022,
    },

    # =========================================================================
    # TIER 8: SPECIAL
    # =========================================================================
    {
        "id": "sp01_special_breakdown_wwbi_2countries", "tier": "special", "mode": "viz",
        "label": "SPECIAL: Breakdown - WWBI public employment by sector, USA+GBR 2018-2020",
        "description": "WWBI public employment disaggregated by institutional sector for USA and GBR 2018-2020. Expect: breakdown_comparison grouped bar.",
        "database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "USA;GBR", "start_year": 2018, "end_year": 2020,
    },
    {
        "id": "sp02_special_breakdown_wwbi_latam", "tier": "special", "mode": "viz",
        "label": "SPECIAL: Breakdown - WWBI public employment, Latin America 4 countries",
        "description": "WWBI public employment by sector for Brazil, Mexico, Colombia, Chile 2017-2020. Expect: small_multiples or breakdown_comparison.",
        "database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "BRA;MEX;COL;CHL", "start_year": 2017, "end_year": 2020,
    },
    {
        "id": "sp03_special_explicit_distribution_g20", "tier": "special", "mode": "viz",
        "label": "SPECIAL: Explicit distribution - GDP per capita, 19 G20 countries 2022",
        "description": "Explicitly request distribution chart of GDP per capita across 19 G20 economies in 2022. Expect: distribution strip/beeswarm.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
        "country_code": "USA;CHN;DEU;GBR;JPN;FRA;ITA;CAN;AUS;KOR;MEX;BRA;IND;IDN;ZAF;TUR;SAU;ARG;RUS",
        "start_year": 2022, "end_year": 2022, "chart_type": "distribution",
    },
    {
        "id": "sp04_special_explicit_heatmap_override", "tier": "special", "mode": "viz",
        "label": "SPECIAL: Explicit heatmap - inflation, 8 countries x 8 years (override)",
        "description": "Force heatmap of CPI inflation for BRICS+Turkey+Egypt+Morocco 2015-2022. Expect: heatmap.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG",
        "country_code": "BRA;RUS;IND;CHN;ZAF;TUR;EGY;MAR",
        "start_year": 2015, "end_year": 2022, "chart_type": "heatmap",
    },
    {
        "id": "sp05_special_explicit_map_asia", "tier": "special", "mode": "viz",
        "label": "SPECIAL: Explicit map - renewable energy, 14 Asian countries 2021",
        "description": "Force choropleth map of renewable energy share for 14 Asian countries in 2021. Expect: choropleth.",
        "database_id": "WB_ESG", "indicator_id": "WB_ESG_EG_FEC_RNEW_ZS",
        "country_code": "CHN;JPN;KOR;IND;IDN;THA;MYS;PHL;VNM;BGD;PAK;SGP;AUS;NZL",
        "start_year": 2021, "end_year": 2021, "chart_type": "map",
    },
    {
        "id": "sp06_special_3ind_africa_scale_stress", "tier": "special", "mode": "viz",
        "label": "SPECIAL: 3 indicators - Life exp + Under-5 mortality + GDP growth, Africa 5",
        "description": "Life expectancy, under-5 mortality, and GDP growth for Kenya, Nigeria, Ethiopia, Ghana, Tanzania 2010-2022. Three very different scales. Expect: small_multiples 3 panels.",
        "database_ids": ["WB_WDI", "WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_SP_DYN_LE00_IN", "WB_WDI_SH_DYN_MORT", "WB_WDI_NY_GDP_MKTP_KD_ZG"],
        "country_code": "KEN;NGA;ETH;GHA;TZA", "start_year": 2010, "end_year": 2022,
    },
    {
        "id": "sp07_special_internet_vs_gdppcap_developing", "tier": "special", "mode": "viz",
        "label": "SPECIAL: Scatter - Internet users vs GDP per capita, 20 developing 2020",
        "description": "Correlation scatter of internet penetration vs GDP per capita for 20 developing economies in 2020. Expect: correlation scatter.",
        "database_ids": ["WB_WDI", "WB_WDI"],
        "indicator_ids": ["WB_WDI_IT_NET_USER_ZS", "WB_WDI_NY_GDP_PCAP_KD"],
        "country_code": "IND;BGD;PAK;NGA;ETH;KEN;TZA;GHA;UGA;MOZ;MDG;MLI;BFA;NER;SEN;ZMB;ZWE;RWA;CMR;CIV",
        "start_year": 2020, "end_year": 2020,
    },
    {
        "id": "sp08_special_crossdb_imf_vs_wdi_china", "tier": "special", "mode": "viz",
        "label": "SPECIAL: IMF vs WDI GDP growth comparison - China, 2010-2022",
        "description": "Compare IMF WEO real GDP growth and WDI GDP growth for China 2010-2022. Cross-database, single country. Expect: temporal_multi_indicator layered.",
        "database_ids": ["IMF_WEO", "WB_WDI"],
        "indicator_ids": ["IMF_WEO_NGDP_RPCH", "WB_WDI_NY_GDP_MKTP_KD_ZG"],
        "country_code": "CHN", "start_year": 2010, "end_year": 2022,
    },

    # =========================================================================
    # EXTRA
    # =========================================================================
    {
        "id": "x01_extra_gdp_south_asia_line", "tier": "easy", "mode": "viz",
        "label": "EXTRA: GDP per capita - South Asia 5, 2010-2022",
        "description": "GDP per capita for India, Bangladesh, Pakistan, Sri Lanka, Nepal 2010-2022. Standard multi-line. Expect: temporal_single.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
        "country_code": "IND;BGD;PAK;LKA;NPL", "start_year": 2010, "end_year": 2022,
    },
    {
        "id": "x02_extra_mortality_under5_sea_longtrend", "tier": "easy", "mode": "viz",
        "label": "EXTRA: Under-5 mortality - SE Asia 6, 2000-2022",
        "description": "Under-5 mortality rate for Indonesia, Malaysia, Thailand, Philippines, Vietnam, Cambodia 2000-2022. Expect: temporal_single.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_SH_DYN_MORT",
        "country_code": "IDN;MYS;THA;PHL;VNM;KHM", "start_year": 2000, "end_year": 2022,
    },
    {
        "id": "x03_extra_trade_mena_2022_bar", "tier": "moderate", "mode": "viz",
        "label": "EXTRA: Cross-section - Trade openness, MENA 6 countries 2022",
        "description": "Trade (% GDP) for Saudi Arabia, UAE, Egypt, Iran, Israel, Morocco in 2022. Single year bar. Expect: cross_sectional.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_NE_TRD_GNFS_ZS",
        "country_code": "SAU;ARE;EGY;IRN;ISR;MAR", "start_year": 2022, "end_year": 2022,
    },
    {
        "id": "x04_extra_fdi_africa_choropleth_2019", "tier": "moderate", "mode": "viz",
        "label": "EXTRA: Choropleth - FDI inflows, 20 African countries 2019",
        "description": "Geographic map of FDI net inflows for 20 African countries in 2019. Expect: choropleth.",
        "database_id": "WB_WDI", "indicator_id": "WB_WDI_BX_KLT_DINV_WD_GD_ZS",
        "country_code": "NGA;ZAF;KEN;ETH;TZA;GHA;UGA;DZA;AGO;MOZ;CMR;CIV;MDG;MLI;BFA;NER;SEN;ZMB;ZWE;RWA",
        "start_year": 2019, "end_year": 2019, "chart_type": "map",
    },
    {
        "id": "x05_extra_corr_co2_vs_gdp_latin", "tier": "hard", "mode": "viz",
        "label": "EXTRA: Scatter - CO2 per capita vs GDP per capita, 10 LatAm 2019",
        "description": "Correlation scatter of CO2 per capita and GDP per capita for 10 Latin American countries in 2019. Cross-database (WB_ESG + WB_WDI). Expect: correlation scatter.",
        "database_ids": ["WB_ESG", "WB_WDI"],
        "indicator_ids": ["WB_ESG_EN_ATM_CO2E_PC", "WB_WDI_NY_GDP_PCAP_KD"],
        "country_code": "BRA;MEX;COL;ARG;CHL;PER;ECU;BOL;PRY;URY",
        "start_year": 2019, "end_year": 2019,
    },
    {
        "id": "x06_extra_wwbi_small_multiples_sea", "tier": "special", "mode": "viz",
        "label": "EXTRA: Small multiples - WWBI employment breakdown, 5 Asian countries",
        "description": "WWBI public employment disaggregated by sector for Indonesia, Malaysia, Thailand, Philippines, Vietnam 2016-2019. Expect: small_multiples or breakdown_comparison.",
        "database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "IDN;MYS;THA;PHL;VNM", "start_year": 2016, "end_year": 2019,
    },
]

assert len(SCENARIOS) == 55, f"Expected 55 scenarios, got {len(SCENARIOS)}"


async def run_exploration(scenarios, pass_threshold, tier_filter):
    filtered = [s for s in scenarios if tier_filter is None or s["tier"] == tier_filter]
    results = []

    for i, scen in enumerate(filtered, 1):
        sid = scen["id"]
        tier = scen.get("tier", "?")
        print(f"\n({i}/{len(filtered)}) [{tier.upper()}] [{sid}]")
        print(f"  {scen['label']}")

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

            status = "PASS" if (score or 0) >= pass_threshold else ("WARN" if (score or 0) >= 5.0 else "FAIL")
            icon = "+" if status == "PASS" else ("~" if status == "WARN" else "x")
            print(f"  [{icon}] Score: {score}/10 [{status}] | Strategy: {res.get('strategy','N/A')}")
            if err:
                print(f"  Error: {err}")
            if critique:
                print(f"  Critique: {critique.replace(chr(10),' ')[:120]}...")

            results.append({
                "id": sid, "label": scen["label"], "tier": tier,
                "mode": scen.get("mode", "viz"),
                "actual_strategy": res.get("strategy"),
                "score": score, "status": status, "error": err,
            })
        except Exception as exc:
            exc_type = type(exc).__name__
            exc_msg = str(exc) or f"<empty - {exc_type}>"
            print(f"  EXCEPTION ({exc_type}): {exc_msg}")
            results.append({
                "id": sid, "label": scen["label"], "tier": tier,
                "mode": scen.get("mode", "viz"),
                "actual_strategy": None,
                "score": None, "status": "ERROR", "error": exc_msg,
            })

    return results


def print_summary(results, pass_threshold):
    print("\n" + "=" * 70)
    print("EXPLORATION v2 SUMMARY")
    print("=" * 70)

    by_tier = defaultdict(list)
    for r in results:
        by_tier[r.get("tier", "?")].append(r)

    tier_order = ["trivial", "easy", "moderate", "hard", "stress", "chained", "boundary", "special"]
    print(f"\n{'Tier':<12} {'N':>3} {'Avg':>6} {'Pass%':>7}")
    print("-" * 34)
    all_scores = []
    for tier in tier_order:
        grp = by_tier.get(tier, [])
        if not grp:
            continue
        scores = [r["score"] for r in grp if r["score"] is not None]
        avg = sum(scores) / len(scores) if scores else 0.0
        pct = 100 * sum(1 for s in scores if s >= pass_threshold) / len(scores) if scores else 0.0
        print(f"  {tier:<10} {len(grp):>3} {avg:>5.1f} {pct:>6.0f}%")
        all_scores.extend(scores)

    total_avg = sum(all_scores) / len(all_scores) if all_scores else 0.0
    print("-" * 34)
    print(f"  {'OVERALL':<10} {len(results):>3} {total_avg:>5.1f}")

    by_strat = defaultdict(list)
    for r in results:
        by_strat[r.get("actual_strategy") or "unknown"].append(r)

    print(f"\n{'Strategy':<34} {'N':>3} {'Avg':>6}")
    print("-" * 46)
    for strat in sorted(by_strat):
        grp = by_strat[strat]
        scores = [r["score"] for r in grp if r["score"] is not None]
        avg = sum(scores) / len(scores) if scores else 0.0
        print(f"  {strat:<32} {len(grp):>3} {avg:>5.1f}")

    scored = sorted([r for r in results if r["score"] is not None], key=lambda r: r["score"], reverse=True)
    if scored:
        print("\nTop 5 scores:")
        for r in scored[:5]:
            print(f"  [{r['score']}/10] [{r['tier']}] {r['label'][:65]}")
        print("Bottom 5 scores:")
        for r in scored[-5:]:
            print(f"  [{r['score']}/10] [{r['tier']}] {r['label'][:65]}")

    errors = [r for r in results if r["status"] == "ERROR"]
    if errors:
        print(f"\nErrors ({len(errors)}):")
        for r in errors:
            print(f"  {r['id']}: {r['error'][:100]}")

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    summary_path = REPORTS_DIR / f"explore_v2_summary_{ts}.json"
    summary_path.write_text(json.dumps({
        "run_at": ts, "total": len(results),
        "pass_threshold": pass_threshold, "overall_avg": total_avg,
        "results": results,
    }, indent=2))
    print(f"\nSummary saved -> {summary_path}")
    print("=" * 70)


TIER_NAMES = ["trivial", "easy", "moderate", "hard", "stress", "chained", "boundary", "special"]


def main():
    parser = argparse.ArgumentParser(description="Data360 viz engine open exploration v2 - 52 curated scenarios.")
    parser.add_argument("--tier", choices=TIER_NAMES, default=None, help="Filter to a single tier.")
    parser.add_argument("--threshold", type=float, default=7.0, help="Pass score threshold (default 7.0).")
    parser.add_argument("--dry-run", action="store_true", help="List scenarios without making API calls.")
    args = parser.parse_args()

    filtered = [s for s in SCENARIOS if args.tier is None or s["tier"] == args.tier]

    print(f"\nData360 Viz Engine - Open Exploration v2")
    print(f"  Scenarios : {len(filtered)}/{len(SCENARIOS)}")
    print(f"  Tier      : {args.tier or 'all'}")
    print(f"  Pass @    : {args.threshold}/10")
    print(f"  Server    : {MCP_BASE_URL}")

    if args.dry_run:
        print(f"\n{'#':>3}  {'Tier':<10} {'ID':<44} Label")
        print("-" * 105)
        for i, s in enumerate(filtered, 1):
            print(f"  {i:>2}.  {s['tier']:<10} {s['id']:<44} {s['label'][:50]}")
        return

    if not SERVER_UP:
        print(f"\nERROR: MCP server not reachable at {MCP_BASE_URL}")
        sys.exit(1)
    if not OPENAI_KEY_SET:
        print("ERROR: OPENAI_API_KEY not set in .env.evals")
        sys.exit(1)

    results = asyncio.run(run_exploration(filtered, args.threshold, args.tier))
    print_summary(results, args.threshold)


if __name__ == "__main__":
    main()
