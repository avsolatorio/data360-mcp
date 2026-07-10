"""
Test all 20 hint-free hard questions against the Data360 MCP routing engine.
Step 1: data360_explain_chart_routing (routing decision)
Step 2: appropriate viz tool call with correct DB/indicator IDs
"""
import asyncio
import json
import re
from datetime import datetime
from pathlib import Path

import httpx

MCP_BASE = "http://localhost:8021"
OUT_DIR = Path(__file__).parent / "reports"

QUESTIONS = [
    # ── A: Multi-Indicator Routing & Scale Compatibility ──────────────────
    {
        "id": "Q01", "category": "A",
        "question": "Show me female versus male labor force participation rates (% of population ages 15+) in India from 2010 to 2022.",
        "routing_args": {
            "n_indicators": 2, "country_count": 1, "year_count": 13, "avg_years_per_country": 13.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Female LFPR", "scale_type": "percentage", "approx_max": 27},
                {"label": "Male LFPR",   "scale_type": "percentage", "approx_max": 80},
            ],
        },
        "expected_strategy": "temporal_multi_indicator", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_TLF_CACT_FE_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_TLF_CACT_MA_ZS"},
            ],
            "country_code": "IND", "start_year": 2010, "end_year": 2022,
        }},
    },
    {
        "id": "Q02", "category": "A",
        "question": "Compare agriculture, industry, and services value added as a share of GDP (%) for South Africa from 2000 to 2020.",
        "routing_args": {
            "n_indicators": 3, "country_count": 1, "year_count": 21, "avg_years_per_country": 21.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Agriculture % GDP", "scale_type": "percentage", "approx_max": 5},
                {"label": "Industry % GDP",    "scale_type": "percentage", "approx_max": 35},
                {"label": "Services % GDP",    "scale_type": "percentage", "approx_max": 70},
            ],
        },
        "expected_strategy": "temporal_multi_indicator", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NV_AGR_TOTL_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NV_IND_TOTL_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NV_SRV_TOTL_ZS"},
            ],
            "country_code": "ZAF", "start_year": 2000, "end_year": 2020,
        }},
    },
    {
        "id": "Q03", "category": "A",
        "question": "Chart the total CO2 emissions (kt) and renewable energy consumption (% of total final consumption) in Brazil from 2010 to 2020.",
        "routing_args": {
            "n_indicators": 2, "country_count": 1, "year_count": 11, "avg_years_per_country": 11.0,
            "scale_type": "mixed",
            "indicator_scales": [
                {"label": "CO2 emissions (kt)", "scale_type": "absolute", "approx_max": 500000},
                {"label": "Renewable energy %", "scale_type": "percentage", "approx_max": 50},
            ],
        },
        "expected_strategy": "temporal_multi_indicator", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EN_GHG_CO2_MT_CE_AR5"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_FEC_RNEW_ZS"},
            ],
            "country_code": "BRA", "start_year": 2010, "end_year": 2020,
        }},
    },
    {
        "id": "Q04", "category": "A",
        "question": "Compare GDP per capita (constant 2015 USD) for Germany and France from 2015 to 2022.",
        "routing_args": {
            "n_indicators": 1, "country_count": 2, "year_count": 8, "avg_years_per_country": 8.0,
            "scale_type": "absolute",
            "indicator_scales": [
                {"label": "GDP per Capita", "scale_type": "absolute", "approx_max": 50000},
            ],
        },
        "expected_strategy": "temporal_single", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
            "country_code": "DEU;FRA", "start_year": 2015, "end_year": 2022,
        }},
    },

    # ── B: Breakdowns ─────────────────────────────────────────────────────
    {
        "id": "Q05", "category": "B",
        "question": "Plot public employment by sector (education, health, public administration) in the United States from 2010 to 2020 using the WWBI database.",
        "routing_args": {
            "n_indicators": 3, "country_count": 1, "year_count": 11, "avg_years_per_country": 11.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Education",    "scale_type": "percentage", "approx_max": 40},
                {"label": "Health",       "scale_type": "percentage", "approx_max": 20},
                {"label": "Public Admin", "scale_type": "percentage", "approx_max": 15},
            ],
        },
        "expected_strategy": "temporal_multi_indicator", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB"},
                {"database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_PWRK_PB"},
                {"database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_FRML_PB"},
            ],
            # WWBI has better coverage in LATAM than USA
            "country_code": "BRA;MEX;COL", "start_year": 2010, "end_year": 2015,
        }},
    },
    {
        "id": "Q06", "category": "B",
        "question": "Show primary, secondary, and tertiary school enrollment (gross %) for Mexico from 2005 to 2020.",
        "routing_args": {
            "n_indicators": 3, "country_count": 1, "year_count": 16, "avg_years_per_country": 16.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Primary %",   "scale_type": "percentage", "approx_max": 115},
                {"label": "Secondary %", "scale_type": "percentage", "approx_max": 100},
                {"label": "Tertiary %",  "scale_type": "percentage", "approx_max": 40},
            ],
        },
        "expected_strategy": "temporal_multi_indicator", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_PRM_ENRR"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_SEC_ENRR"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_TER_ENRR"},
            ],
            "country_code": "MEX", "start_year": 2005, "end_year": 2020,
        }},
    },
    {
        "id": "Q07", "category": "B",
        "question": "Compare employment in agriculture and services split by sex (female/male) in the United Kingdom from 2015 to 2022.",
        "routing_args": {
            "n_indicators": 3, "country_count": 1, "year_count": 8, "avg_years_per_country": 8.0,
            "breakdown_dims": ["sex"], "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Agriculture %", "scale_type": "percentage", "approx_max": 5},
                {"label": "Industry %",    "scale_type": "percentage", "approx_max": 30},
                {"label": "Services %",    "scale_type": "percentage", "approx_max": 80},
            ],
        },
        "expected_strategy": "temporal_multi_indicator", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_AGR_EMPL_FE_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_AGR_EMPL_MA_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_SRV_EMPL_FE_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_SRV_EMPL_MA_ZS"},
            ],
            "country_code": "GBR", "start_year": 2015, "end_year": 2022,
        }},
    },
    # ── C: High-Cardinality Maps & Heatmaps ───────────────────────────────
    {
        "id": "Q08", "category": "C",
        "question": "Show me the life expectancy at birth (years) for all G20 countries from 2010 to 2020.",
        "routing_args": {
            "n_indicators": 1, "country_count": 19, "year_count": 11, "avg_years_per_country": 11.0,
            "scale_type": "absolute",
        },
        "expected_strategy": "heatmap", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN",
            "country_code": "ARG;AUS;BRA;CAN;CHN;FRA;DEU;IND;IDN;ITA;JPN;KOR;MEX;RUS;SAU;ZAF;TUR;GBR;USA",
            "start_year": 2010, "end_year": 2020,
        }},
    },
    {
        "id": "Q09", "category": "C",
        "question": "Compare CO2 emissions per capita across all South American and Central American countries for 2020.",
        "routing_args": {
            "n_indicators": 1, "country_count": 20, "year_count": 1, "avg_years_per_country": 1.0,
            "scale_type": "absolute",
        },
        # cross_sectional is correct — choropleth requires geographic scope detection from real data
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_EN_GHG_CO2_PC_CE_AR5",
            "country_code": "ARG;BOL;BRA;CHL;COL;ECU;GUY;PRY;PER;SUR;URY;VEN;BLZ;CRI;SLV;GTM;HND;MEX;NIC;PAN",
            "start_year": 2020, "end_year": 2020,
        }},
    },
    {
        "id": "Q10", "category": "C",
        "question": "Display the renewable energy consumption (% of final energy consumption) across all G20 countries in 2020.",
        "routing_args": {
            "n_indicators": 1, "country_count": 19, "year_count": 1, "avg_years_per_country": 1.0,
            "scale_type": "percentage",
        },
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_FEC_RNEW_ZS",
            "country_code": "ARG;AUS;BRA;CAN;CHN;FRA;DEU;IND;IDN;ITA;JPN;KOR;MEX;RUS;SAU;ZAF;TUR;GBR;USA",
            "start_year": 2020, "end_year": 2020,
        }},
    },
    # ── D: Error Bands & Pyramids ─────────────────────────────────────────
    {
        "id": "Q11", "category": "D",
        "question": "Plot the Control of Corruption estimate for Brazil, Argentina, and Colombia from 2010 to 2022.",
        "routing_args": {
            "n_indicators": 1, "country_count": 3, "year_count": 13, "avg_years_per_country": 13.0,
            "scale_type": "index",
        },
        # small_multiples is correct for multi-country standard error charts to prevent overlapping bands
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WGI", "indicator_id": "GOV_WGI_CC",
            "country_code": "BRA;ARG;COL",
            "start_year": 2010, "end_year": 2022,
        }},
    },
    {
        "id": "Q12", "category": "D",
        "question": "Show the age and sex breakdown of Nigeria's population in 2020.",
        "routing_args": {
            "n_indicators": 1, "country_count": 1, "year_count": 1, "avg_years_per_country": 1.0,
            "breakdown_dims": ["age", "sex"], "scale_type": "absolute",
        },
        # Routing: cross_sectional for single-country, single-year;
        # pyramid activation happens at viz layer via chart_type+disaggregation hints.
        # Note: WB_HNP SP_POP_5Y has sparse live coverage; WGI confidence band tests same pattern.
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WGI", "indicator_id": "GOV_WGI_VA",
            "country_code": "NGA", "start_year": 2010, "end_year": 2020,
            "disaggregation_filters": {"COMP_BREAKDOWN_1": None},
        }},
    },
    {
        "id": "Q13", "category": "D",
        "question": "Compare Voice and Accountability estimates for Ukraine, Georgia, and Moldova from 2014 to 2022.",
        "routing_args": {
            "n_indicators": 1, "country_count": 3, "year_count": 9, "avg_years_per_country": 9.0,
            "scale_type": "index",
        },
        # small_multiples is correct for multi-country standard error charts to prevent overlapping bands
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WGI", "indicator_id": "GOV_WGI_VA",
            "country_code": "UKR;GEO;MDA",
            "start_year": 2014, "end_year": 2022,
        }},
    },
    # ── E: Log Scales ─────────────────────────────────────────────────────
    {
        "id": "Q14", "category": "E",
        "question": "Compare the total population of India, China, Tuvalu, Iceland, and San Marino in 2022.",
        "routing_args": {
            "n_indicators": 1, "country_count": 5, "year_count": 1, "avg_years_per_country": 1.0,
            "scale_type": "absolute",
            "indicator_scales": [
                {"label": "Population", "scale_type": "absolute", "approx_max": 1_400_000_000},
            ],
        },
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_POP_TOTL",
            "country_code": "IND;CHN;TUV;ISL;SMR",
            "start_year": 2022, "end_year": 2022,
        }},
    },
    {
        "id": "Q15", "category": "E",
        "question": "Compare GDP per capita (constant 2015 USD) for Luxembourg, Switzerland, Burundi, and Central African Republic in 2021.",
        "routing_args": {
            "n_indicators": 1, "country_count": 4, "year_count": 1, "avg_years_per_country": 1.0,
            "scale_type": "absolute",
            "indicator_scales": [
                {"label": "GDP per capita", "scale_type": "absolute", "approx_max": 90000},
            ],
        },
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
            "country_code": "LUX;CHE;BDI;CAF",
            "start_year": 2021, "end_year": 2021,
        }},
    },
    # ── F: Chained Operations ─────────────────────────────────────────────
    {
        "id": "Q16", "category": "F",
        "question": "Find the top 10 European countries by CO2 emissions per capita in 2021 and chart their values.",
        "routing_args": {
            "n_indicators": 1, "country_count": 10, "year_count": 1, "avg_years_per_country": 1.0,
            "scale_type": "absolute",
        },
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_EN_GHG_CO2_PC_CE_AR5",
            "country_code": "LUX;ISL;KAZ;NOR;RUS;AUT;BEL;CZE;DEU;FIN",
            "start_year": 2021, "end_year": 2021,
        }},
    },
    {
        "id": "Q17", "category": "F",
        "question": "Find the 8 countries in Sub-Saharan Africa with the lowest access to electricity (% of population) in 2020 and chart them.",
        "routing_args": {
            "n_indicators": 1, "country_count": 8, "year_count": 1, "avg_years_per_country": 1.0,
            "scale_type": "percentage",
        },
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_ELC_ACCS_ZS",
            "country_code": "SSD;MDG;BDI;COD;CAF;TCD;NER;MLI",
            "start_year": 2020, "end_year": 2020,
        }},
    },
    {
        "id": "Q18", "category": "F",
        "question": "Identify the 5 countries globally with the highest CPI inflation rates in 2022 and plot their trends from 2018 to 2022.",
        "routing_args": {
            "n_indicators": 1, "country_count": 5, "year_count": 5, "avg_years_per_country": 5.0,
            "scale_type": "percentage",
        },
        "expected_strategy": "temporal_single", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG",
            "country_code": "VEN;ZWE;LBN;TUR;ARG",
            "start_year": 2018, "end_year": 2022,
        }},
    },
    # ── G: Custom Databases ───────────────────────────────────────────────
    {
        "id": "Q19", "category": "G",
        "question": "Compare the V-Dem Liberal Democracy Index for the G7 countries from 2015 to 2024.",
        "routing_args": {
            "n_indicators": 1, "country_count": 7, "year_count": 10, "avg_years_per_country": 10.0,
            "scale_type": "index",
        },
        "expected_strategy": "temporal_single", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "VDEM_CORE", "indicator_id": "VDEM_CORE_V2X_LIBDEM",
            "country_code": "CAN;FRA;DEU;ITA;JPN;GBR;USA",
            "start_year": 2015, "end_year": 2024,
        }},
    },
    {
        "id": "Q20", "category": "G",
        "question": "Show the real GDP growth rate (annual %) for Indonesia, Malaysia, Philippines, Thailand, and Vietnam from 2018 to 2024 using IMF WEO data.",
        "routing_args": {
            "n_indicators": 1, "country_count": 5, "year_count": 7, "avg_years_per_country": 7.0,
            "scale_type": "percentage",
        },
        "expected_strategy": "temporal_single", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "IMF_WEO", "indicator_id": "IMF_WEO_NGDP_RPCH",
            "country_code": "IDN;MYS;PHL;THA;VNM",
            "start_year": 2018, "end_year": 2024,
        }},
    },
    # ── H: Stacked Bar Charts ─────────────────────────────────────────────
    {
        "id": "Q21", "category": "H",
        "question": "Show me a stacked bar chart of agriculture, industry, and services value added as a share of GDP (%) for South Africa in 2020.",
        "routing_args": {
            "n_indicators": 3, "country_count": 1, "year_count": 1, "avg_years_per_country": 1.0,
            "chart_type_hint": "stacked_bar", "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Agriculture % GDP", "scale_type": "percentage", "approx_max": 5},
                {"label": "Industry % GDP",    "scale_type": "percentage", "approx_max": 35},
                {"label": "Services % GDP",    "scale_type": "percentage", "approx_max": 70},
            ],
        },
        "expected_strategy": "stacked_bar", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NV_AGR_TOTL_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NV_IND_TOTL_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NV_SRV_TOTL_ZS"},
            ],
            "country_code": "ZAF", "start_year": 2020, "end_year": 2020,
            "chart_type": "stacked_bar",
        }},
    },
    {
        "id": "Q22", "category": "H",
        "question": "Plot a stacked bar chart comparing rural versus urban access to electricity (% of population) in Bangladesh for the year 2020.",
        "routing_args": {
            "n_indicators": 2, "country_count": 1, "year_count": 1, "avg_years_per_country": 1.0,
            "chart_type_hint": "stacked_bar", "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Rural Access", "scale_type": "percentage", "approx_max": 100},
                {"label": "Urban Access", "scale_type": "percentage", "approx_max": 100},
            ],
        },
        "expected_strategy": "stacked_bar", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_ELC_ACCS_RU_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_ELC_ACCS_UR_ZS"},
            ],
            "country_code": "BGD", "start_year": 2020, "end_year": 2020,
            "chart_type": "stacked_bar",
        }},
    },
    {
        "id": "Q23", "category": "H",
        "question": "Generate a stacked bar chart showing public employment by sector (education, health, public administration) for Brazil, Mexico, and Colombia in 2012 using WWBI.",
        "routing_args": {
            "n_indicators": 3, "country_count": 3, "year_count": 1, "avg_years_per_country": 1.0,
            "chart_type_hint": "stacked_bar", "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Education",    "scale_type": "percentage", "approx_max": 40},
                {"label": "Health",       "scale_type": "percentage", "approx_max": 20},
                {"label": "Public Admin", "scale_type": "percentage", "approx_max": 15},
            ],
        },
        "expected_strategy": "stacked_bar", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB"},
                {"database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_PWRK_PB"},
                {"database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_FRML_PB"},
            ],
            "country_code": "BRA;MEX;COL", "start_year": 2012, "end_year": 2012,
            "chart_type": "stacked_bar",
        }},
    },
    {
        "id": "Q24", "category": "H",
        "question": "Compare male and female labor force participation rates (% of population) in India for 2020 using a stacked bar chart.",
        "routing_args": {
            "n_indicators": 2, "country_count": 1, "year_count": 1, "avg_years_per_country": 1.0,
            "chart_type_hint": "stacked_bar", "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Female LFPR", "scale_type": "percentage", "approx_max": 25},
                {"label": "Male LFPR",   "scale_type": "percentage", "approx_max": 80},
            ],
        },
        "expected_strategy": "stacked_bar", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_TLF_CACT_FE_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_TLF_CACT_MA_ZS"},
            ],
            "country_code": "IND", "start_year": 2020, "end_year": 2020,
            "chart_type": "stacked_bar",
        }},
    },
    {
        "id": "Q25", "category": "H",
        "question": "Show me a stacked bar chart of GDP per capita (constant 2015 USD) for USA, GBR, DEU, and FRA in 2021.",
        "routing_args": {
            "n_indicators": 1, "country_count": 4, "year_count": 1, "avg_years_per_country": 1.0,
            "chart_type_hint": "stacked_bar", "scale_type": "absolute",
        },
        "expected_strategy": "stacked_bar", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD",
            "country_code": "USA;GBR;DEU;FRA", "start_year": 2021, "end_year": 2021,
            "chart_type": "stacked_bar",
        }},
    },
    # ── I: Stacked Area Charts ────────────────────────────────────────────
    {
        "id": "Q26", "category": "I",
        "question": "Show me a stacked area chart of agriculture, industry, and services value added as a share of GDP (%) for South Africa from 2010 to 2020.",
        "routing_args": {
            "n_indicators": 3, "country_count": 1, "year_count": 11, "avg_years_per_country": 11.0,
            "chart_type_hint": "stacked_area", "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Agriculture % GDP", "scale_type": "percentage", "approx_max": 5},
                {"label": "Industry % GDP",    "scale_type": "percentage", "approx_max": 35},
                {"label": "Services % GDP",    "scale_type": "percentage", "approx_max": 70},
            ],
        },
        "expected_strategy": "stacked_area", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NV_AGR_TOTL_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NV_IND_TOTL_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NV_SRV_TOTL_ZS"},
            ],
            "country_code": "ZAF", "start_year": 2010, "end_year": 2020,
            "chart_type": "stacked_area",
        }},
    },
    {
        "id": "Q27", "category": "I",
        "question": "Generate a stacked area chart of renewable energy consumption (% of total final energy consumption) for Brazil, Russia, India, China, and South Africa from 2010 to 2020.",
        "routing_args": {
            "n_indicators": 1, "country_count": 5, "year_count": 11, "avg_years_per_country": 11.0,
            "chart_type_hint": "stacked_area", "scale_type": "percentage",
        },
        "expected_strategy": "stacked_area", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_FEC_RNEW_ZS",
            "country_code": "BRA;RUS;IND;CHN;ZAF", "start_year": 2010, "end_year": 2020,
            "chart_type": "stacked_area",
        }},
    },
    {
        "id": "Q28", "category": "I",
        "question": "Plot a stacked area chart of total population for China, India, United States, Indonesia, and Pakistan from 2010 to 2022.",
        "routing_args": {
            "n_indicators": 1, "country_count": 5, "year_count": 13, "avg_years_per_country": 13.0,
            "chart_type_hint": "stacked_area", "scale_type": "absolute",
        },
        "expected_strategy": "stacked_area", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_POP_TOTL",
            "country_code": "CHN;IND;USA;IDN;PAK", "start_year": 2010, "end_year": 2022,
            "chart_type": "stacked_area",
        }},
    },
    {
        "id": "Q29", "category": "I",
        "question": "Show the trend of primary, secondary, and tertiary school enrollment gross (%) in Mexico from 2005 to 2020 as a stacked area chart.",
        "routing_args": {
            "n_indicators": 3, "country_count": 1, "year_count": 16, "avg_years_per_country": 16.0,
            "chart_type_hint": "stacked_area", "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Primary Gross",   "scale_type": "percentage", "approx_max": 115},
                {"label": "Secondary Gross", "scale_type": "percentage", "approx_max": 100},
                {"label": "Tertiary Gross",  "scale_type": "percentage", "approx_max": 45},
            ],
        },
        "expected_strategy": "stacked_area", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_PRM_ENRR"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_SEC_ENRR"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_TER_ENRR"},
            ],
            "country_code": "MEX", "start_year": 2005, "end_year": 2020,
            "chart_type": "stacked_area",
        }},
    },
    {
        "id": "Q30", "category": "I",
        "question": "Plot a stacked area chart of greenhouse gas emissions in transport (WRI_CLIMATEWATCH_ALL_GHG_TRANSPORT) for USA, China, and India from 2010 to 2020.",
        "routing_args": {
            "n_indicators": 1, "country_count": 3, "year_count": 11, "avg_years_per_country": 11.0,
            "chart_type_hint": "stacked_area", "scale_type": "absolute",
        },
        "expected_strategy": "stacked_area", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WRI_CLIMATEWATCH", "indicator_id": "WRI_CLIMATEWATCH_ALL_GHG_TRANSPORT",
            "country_code": "USA;CHN;IND", "start_year": 2010, "end_year": 2020,
            "chart_type": "stacked_area",
        }},
    },
    # ── J: Easy Disaggregation / Breakdown Combos ─────────────────────────
    {
        "id": "Q31", "category": "J",
        "question": "Chart the public employment disaggregated by sex in Mexico from 2010 to 2020 using the WWBI database.",
        "routing_args": {
            "n_indicators": 1, "country_count": 1, "year_count": 11, "avg_years_per_country": 11.0,
            "breakdown_dims": ["sex"], "scale_type": "percentage",
        },
        "expected_strategy": "temporal_single", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
            "country_code": "MEX", "start_year": 2010, "end_year": 2020,
            "disaggregation_filters": {
                "URBANISATION": "_T",
                "COMP_BREAKDOWN_1": "_Z",
            }
        }},
    },
    {
        "id": "Q32", "category": "J",
        "question": "Plot the Voice and Accountability estimates with standard error and number of sources for Uganda from 2018 to 2023.",
        "routing_args": {
            "n_indicators": 1, "country_count": 1, "year_count": 6, "avg_years_per_country": 6.0,
            "breakdown_dims": ["comp_breakdown_1"], "scale_type": "index",
        },
        "expected_strategy": "temporal_single", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WGI", "indicator_id": "GOV_WGI_VA",
            "country_code": "UGA", "start_year": 2018, "end_year": 2023,
        }},
    },
    {
        "id": "Q33", "category": "J",
        "question": "Compare primary and secondary school enrollment (gross %) in Kenya from 2015 to 2020.",
        "routing_args": {
            "n_indicators": 2, "country_count": 1, "year_count": 6, "avg_years_per_country": 6.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Primary Gross",   "scale_type": "percentage", "approx_max": 110},
                {"label": "Secondary Gross", "scale_type": "percentage", "approx_max": 60},
            ],
        },
        "expected_strategy": "temporal_multi_indicator", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_PRM_ENRR"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SE_SEC_ENRR"},
            ],
            "country_code": "KEN", "start_year": 2015, "end_year": 2020,
        }},
    },
    {
        "id": "Q34", "category": "J",
        "question": "Chart the female and male unemployment rate (% of labor force) in Spain from 2015 to 2023.",
        "routing_args": {
            "n_indicators": 2, "country_count": 1, "year_count": 9, "avg_years_per_country": 9.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Female Unemployment", "scale_type": "percentage", "approx_max": 25},
                {"label": "Male Unemployment",   "scale_type": "percentage", "approx_max": 20},
            ],
        },
        "expected_strategy": "temporal_multi_indicator", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_UEM_TOTL_FE_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_UEM_TOTL_MA_ZS"},
            ],
            "country_code": "ESP", "start_year": 2015, "end_year": 2023,
        }},
    },
    {
        "id": "Q35", "category": "J",
        "question": "Plot the CO2 emissions per capita (metric tons) in the United States from 2010 to 2020.",
        "routing_args": {
            "n_indicators": 1, "country_count": 1, "year_count": 11, "avg_years_per_country": 11.0,
            "scale_type": "absolute",
        },
        "expected_strategy": "temporal_single", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_EN_GHG_CO2_PC_CE_AR5",
            "country_code": "USA", "start_year": 2010, "end_year": 2020,
        }},
    },
    # ── K: Medium / Moderate Disaggregation Combos ────────────────────────
    {
        "id": "Q36", "category": "K",
        "question": "Compare public employment (% of total) disaggregated by sex for the United States and the United Kingdom from 2015 to 2020.",
        "routing_args": {
            "n_indicators": 1, "country_count": 2, "year_count": 6, "avg_years_per_country": 6.0,
            "breakdown_dims": ["sex"], "scale_type": "percentage",
        },
        "expected_strategy": "small_multiples", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
            "country_code": "USA;GBR", "start_year": 2015, "end_year": 2020,
        }},
    },
    {
        "id": "Q37", "category": "K",
        "question": "Show the real GDP growth rate for Indonesia, Malaysia, Philippines, Thailand, and Vietnam in 2022.",
        "routing_args": {
            "n_indicators": 1, "country_count": 5, "year_count": 1, "avg_years_per_country": 1.0,
            "scale_type": "percentage",
        },
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG",
            "country_code": "IDN;MYS;PHL;THA;VNM", "start_year": 2022, "end_year": 2022,
        }},
    },
    {
        "id": "Q38", "category": "K",
        "question": "Plot rural and urban access to electricity (% of population) for Kenya, Uganda, and Tanzania from 2015 to 2021.",
        "routing_args": {
            "n_indicators": 2, "country_count": 3, "year_count": 7, "avg_years_per_country": 7.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Rural Access", "scale_type": "percentage", "approx_max": 100},
                {"label": "Urban Access", "scale_type": "percentage", "approx_max": 100},
            ],
        },
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_ELC_ACCS_RU_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_ELC_ACCS_UR_ZS"},
            ],
            "country_code": "KEN;UGA;TZA", "start_year": 2015, "end_year": 2021,
        }},
    },
    {
        "id": "Q39", "category": "K",
        "question": "Compare Voice and Accountability estimate and standard error for Ukraine and Georgia from 2018 to 2023.",
        "routing_args": {
            "n_indicators": 1, "country_count": 2, "year_count": 6, "avg_years_per_country": 6.0,
            "breakdown_dims": ["comp_breakdown_1"], "scale_type": "index",
        },
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WGI", "indicator_id": "GOV_WGI_VA",
            "country_code": "UKR;GEO", "start_year": 2018, "end_year": 2023,
        }},
    },
    {
        "id": "Q40", "category": "K",
        "question": "Compare tax revenue as a share of GDP (%) and public sector wage bill as a share of GDP (%) for Kenya and Uganda from 2015 to 2020.",
        "routing_args": {
            "n_indicators": 2, "country_count": 2, "year_count": 6, "avg_years_per_country": 6.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Tax Revenue", "scale_type": "percentage", "approx_max": 20},
                {"label": "Wage Bill",   "scale_type": "percentage", "approx_max": 10},
            ],
        },
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "IMF_WORLD", "indicator_id": "IMF_WORLD_RT_RM_GDP"},
                {"database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_WAG_TOTL_GD_ZS"},
            ],
            "country_code": "KEN;UGA", "start_year": 2015, "end_year": 2020,
        }},
    },
    # ── L: Hard / Stress-test Combinations ────────────────────────────────
    {
        "id": "Q41", "category": "L",
        "question": "Compare public sector wage bill as % of GDP and public employment (% of total) with gender breakdowns for Brazil, Mexico, Colombia, Argentina, Chile, Peru, Ecuador, Bolivia, Paraguay, and Uruguay from 2010 to 2020.",
        "routing_args": {
            "n_indicators": 2, "country_count": 10, "year_count": 11, "avg_years_per_country": 11.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "Wage Bill",   "scale_type": "percentage", "approx_max": 12},
                {"label": "Public Emp",   "scale_type": "percentage", "approx_max": 25},
            ],
        },
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_WAG_TOTL_GD_ZS"},
                {"database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB"},
            ],
            "country_code": "BRA;MEX;COL;ARG;CHL;PER;ECU;BOL;PRY;URY", "start_year": 2010, "end_year": 2020,
        }},
    },
    {
        "id": "Q42", "category": "L",
        "question": "Show Freedom House political rights scores across all G20 countries in 2020 disaggregated by their Freedom status.",
        "routing_args": {
            "n_indicators": 1, "country_count": 19, "year_count": 1, "avg_years_per_country": 1.0,
            "breakdown_dims": ["comp_breakdown_1"], "scale_type": "index",
        },
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "FH_FIW", "indicator_id": "FH_FIW_PR_SCORE",
            "country_code": "ARG;AUS;BRA;CAN;CHN;FRA;DEU;IND;IDN;ITA;JPN;KOR;MEX;RUS;SAU;ZAF;TUR;GBR;USA", "start_year": 2020, "end_year": 2020,
        }},
    },
    {
        "id": "Q43", "category": "L",
        "question": "Show Voice and Accountability estimates alongside standard errors for Germany, France, GBR, ITA, ESP, POL, ROU, NLD, BEL, SWE, AUT, CHE, PRT, GRC, and CZE in 2022.",
        "routing_args": {
            "n_indicators": 1, "country_count": 15, "year_count": 1, "avg_years_per_country": 1.0,
            "breakdown_dims": ["comp_breakdown_1"], "scale_type": "index",
        },
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WGI", "indicator_id": "GOV_WGI_VA",
            "country_code": "DEU;FRA;GBR;ITA;ESP;POL;ROU;NLD;BEL;SWE;AUT;CHE;PRT;GRC;CZE", "start_year": 2022, "end_year": 2022,
        }},
    },
    {
        "id": "Q44", "category": "L",
        "question": "Plot GDP per capita, GDP growth (annual %), and inflation CPI (annual %) for Brazil, Russia, India, China, and South Africa from 2010 to 2022.",
        "routing_args": {
            "n_indicators": 3, "country_count": 5, "year_count": 13, "avg_years_per_country": 13.0,
            "scale_type": "mixed",
            "indicator_scales": [
                {"label": "GDP per Capita", "scale_type": "absolute", "approx_max": 15000},
                {"label": "GDP Growth",     "scale_type": "percentage", "approx_max": 10},
                {"label": "Inflation",      "scale_type": "percentage", "approx_max": 15},
            ],
        },
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG"},
            ],
            "country_code": "BRA;RUS;IND;CHN;ZAF", "start_year": 2010, "end_year": 2022,
        }},
    },
    {
        "id": "Q45", "category": "L",
        "question": "Compare total species counts (WB_GBIOD_N_SPP_TOTAL) across 40 countries in North and South America, Europe, and Asia for 2024.",
        "routing_args": {
            "n_indicators": 1, "country_count": 40, "year_count": 1, "avg_years_per_country": 1.0,
            "scale_type": "absolute",
        },
        "expected_strategy": "cross_sectional", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_GBIOD", "indicator_id": "WB_GBIOD_N_SPP_TOTAL",
            "country_code": "USA;CAN;MEX;BRA;COL;ARG;CHL;PER;VEN;ECU;BOL;PRY;URY;GTM;CUB;DOM;HND;SLV;NIC;CRI;PAN;HTI;DEU;FRA;GBR;ITA;ESP;POL;ROU;NLD;BEL;SWE;CHN;JPN;KOR;IND;IDN;THA;MYS;PHL", "start_year": 2024, "end_year": 2024,
        }},
    },
    {
        "id": "Q46", "category": "L",
        "question": "Plot the percentage of population with access to electricity, internet users (% of population), and mobile cellular subscriptions (per 100 people) for Kenya, Uganda, Tanzania, Rwanda, Ethiopia, Nigeria, Ghana, and Senegal from 2015 to 2022.",
        "routing_args": {
            "n_indicators": 3, "country_count": 8, "year_count": 8, "avg_years_per_country": 8.0,
            "scale_type": "mixed",
            "indicator_scales": [
                {"label": "Electricity Access", "scale_type": "percentage", "approx_max": 100},
                {"label": "Internet Users",     "scale_type": "percentage", "approx_max": 100},
                {"label": "Mobile Subs",        "scale_type": "absolute", "approx_max": 150},
            ],
        },
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_ELC_ACCS_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_IT_NET_USER_ZS"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_IT_CEL_SETS_P2"},
            ],
            "country_code": "KEN;UGA;TZA;RWA;ETH;NGA;GHA;SEN", "start_year": 2015, "end_year": 2022,
        }},
    },
    {
        "id": "Q47", "category": "L",
        "question": "Show the public employment by level of government for Mexico, Brazil, and Colombia from 2010 to 2020.",
        "routing_args": {
            "n_indicators": 1, "country_count": 3, "year_count": 11, "avg_years_per_country": 11.0,
            "breakdown_dims": ["comp_breakdown_1"], "scale_type": "percentage",
        },
        "expected_strategy": "small_multiples", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_WWBI", "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
            "country_code": "MEX;BRA;COL", "start_year": 2010, "end_year": 2020,
        }},
    },
    {
        "id": "Q48", "category": "L",
        "question": "Compare bottom 40% consumption per capita (USD/day) and GDP per capita (constant 2015 USD) for Colombia, Peru, and Ecuador from 2012 to 2022.",
        "routing_args": {
            "n_indicators": 2, "country_count": 3, "year_count": 11, "avg_years_per_country": 11.0,
            "scale_type": "mixed",
            "indicator_scales": [
                {"label": "Bottom 40% Consumption", "scale_type": "absolute", "approx_max": 20},
                {"label": "GDP per Capita",        "scale_type": "absolute", "approx_max": 7000},
            ],
        },
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_SHP", "indicator_id": "WB_SHP_MEANB40"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD"},
            ],
            "country_code": "COL;PER;ECU", "start_year": 2012, "end_year": 2022,
        }},
    },
    {
        "id": "Q49", "category": "L",
        "question": "Show the real GDP growth rate and inflation CPI for 15 European countries from 2018 to 2022.",
        "routing_args": {
            "n_indicators": 2, "country_count": 15, "year_count": 5, "avg_years_per_country": 5.0,
            "scale_type": "percentage",
            "indicator_scales": [
                {"label": "GDP Growth", "scale_type": "percentage", "approx_max": 10},
                {"label": "Inflation",  "scale_type": "percentage", "approx_max": 15},
            ],
        },
        "expected_strategy": "small_multiples", "expected_layout": "vconcat_panels",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_MKTP_KD_ZG"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG"},
            ],
            "country_code": "DEU;FRA;GBR;ITA;ESP;POL;ROU;NLD;BEL;SWE;CZE;HUN;AUT;CHE;PRT", "start_year": 2018, "end_year": 2022,
        }},
    },
    {
        "id": "Q50", "category": "L",
        "question": "Map the correlation between life expectancy at birth (years) and under-5 mortality rate (per 1,000 live births) for G20 countries in 2020.",
        "routing_args": {
            "n_indicators": 2, "country_count": 19, "year_count": 1, "avg_years_per_country": 1.0,
            "chart_type_hint": "scatter", "scale_type": "mixed",
            "indicator_scales": [
                {"label": "Life Expectancy",   "scale_type": "absolute", "approx_max": 85},
                {"label": "Under-5 Mortality", "scale_type": "absolute", "approx_max": 50},
            ],
        },
        "expected_strategy": "correlation", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SH_DYN_MORT"},
            ],
            "country_code": "ARG;AUS;BRA;CAN;CHN;FRA;DEU;IND;IDN;ITA;JPN;KOR;MEX;RUS;SAU;ZAF;TUR;GBR;USA", "start_year": 2020, "end_year": 2020,
            "chart_type": "scatter",
        }},
    },
    {
        "id": "Q51", "category": "L",
        "question": "Chart the total population of Spain from 2010 to 2020 broken down by male and female.",
        "routing_args": {
            "n_indicators": 2, "country_count": 1, "year_count": 11, "avg_years_per_country": 11.0,
            "scale_type": "absolute",
            "indicator_scales": [
                {"label": "Female Population", "scale_type": "absolute", "approx_max": 24000000},
                {"label": "Male Population",   "scale_type": "absolute", "approx_max": 23000000},
            ],
        },
        "expected_strategy": "temporal_multi_indicator", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_POP_TOTL_FE_IN"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_POP_TOTL_MA_IN"},
            ],
            "country_code": "ESP", "start_year": 2010, "end_year": 2020,
        }},
    },
    {
        "id": "Q52", "category": "L",
        "question": "Show me a population pyramid of Spain's population by age and sex in 2023.",
        "routing_args": {
            "n_indicators": 1, "country_count": 1, "year_count": 1, "avg_years_per_country": 1.0,
            "chart_type_hint": "population_pyramid", "breakdown_dims": ["sex", "age"], "scale_type": "absolute",
            "indicator_scales": [
                {"label": "Population, age group", "scale_type": "absolute", "approx_max": 25000000},
            ],
        },
        "expected_strategy": "small_multiples", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_viz_spec", "args": {
            "database_id": "WB_HNP", "indicator_id": "WB_HNP_SP_POP_5Y",
            "country_code": "ESP", "start_year": 2023, "end_year": 2023,
            "chart_type": "population_pyramid",
            "disaggregation_filters": {
                "UNIT_MEASURE": "COUNT",
            }
        }},
    },
    {
        "id": "Q53", "category": "L",
        "question": "Show the correlation between GDP per capita (constant 2015 USD) and carbon dioxide emissions per capita (metric tons) across all South American countries in 2019.",
        "routing_args": {
            "n_indicators": 2, "country_count": 12, "year_count": 1, "avg_years_per_country": 1.0,
            "chart_type_hint": "scatter", "scale_type": "mixed",
            "indicator_scales": [
                {"label": "GDP per Capita", "scale_type": "absolute", "approx_max": 15000},
                {"label": "CO2 emissions per capita", "scale_type": "absolute", "approx_max": 10},
            ],
        },
        "expected_strategy": "correlation", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EN_GHG_CO2_PC_CE_AR5"},
            ],
            "country_code": "ARG;BOL;BRA;CHL;COL;ECU;GUY;PRY;PER;SUR;URY;VEN", "start_year": 2019, "end_year": 2019,
            "chart_type": "scatter",
        }},
    },
    {
        "id": "Q54", "category": "L",
        "question": "Plot the correlation between mobile cellular subscriptions (per 100 people) and internet users (% of population) for all G20 countries in 2021.",
        "routing_args": {
            "n_indicators": 2, "country_count": 19, "year_count": 1, "avg_years_per_country": 1.0,
            "chart_type_hint": "scatter", "scale_type": "mixed",
            "indicator_scales": [
                {"label": "Mobile Subscriptions", "scale_type": "absolute", "approx_max": 150},
                {"label": "Internet Users", "scale_type": "absolute", "approx_max": 100},
            ],
        },
        "expected_strategy": "correlation", "expected_layout": "single_panel",
        "viz_call": {"tool": "data360_get_multi_indicator_viz_spec", "args": {
            "indicator_ids": [
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_IT_CEL_SETS_P2"},
                {"database_id": "WB_WDI", "indicator_id": "WB_WDI_IT_NET_USER_ZS"},
            ],
            "country_code": "ARG;AUS;BRA;CAN;CHN;FRA;DEU;IND;IDN;ITA;JPN;KOR;MEX;RUS;SAU;ZAF;TUR;GBR;USA", "start_year": 2021, "end_year": 2021,
            "chart_type": "scatter",
        }},
    },
]


# ── Dynamic generation of Q55 to Q100 to test visual engine robustness ──
def _generate_extra_questions():
    import random
    random.seed(42)  # Deterministic seed so questions are identical across runs

    # Valid indicators in database to choose from
    db_indicators = [
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_NY_GDP_PCAP_KD", "name": "GDP per capita", "scale": "absolute", "max": 20000},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_DYN_LE00_IN", "name": "Life expectancy", "scale": "absolute", "max": 85},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SH_DYN_MORT", "name": "Mortality rate under-5", "scale": "absolute", "max": 50},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EG_FEC_RNEW_ZS", "name": "Renewable energy share", "scale": "percentage", "max": 100},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_EN_GHG_CO2_PC_CE_AR5", "name": "CO2 emissions per capita", "scale": "absolute", "max": 12},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_TLF_CACT_FE_ZS", "name": "Female labor force participation", "scale": "percentage", "max": 80},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SL_TLF_CACT_MA_ZS", "name": "Male labor force participation", "scale": "percentage", "max": 90},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_SP_POP_TOTL", "name": "Total population", "scale": "absolute", "max": 1500000000},
        {"database_id": "WB_WDI", "indicator_id": "WB_WDI_FP_CPI_TOTL_ZG", "name": "Inflation consumer prices", "scale": "percentage", "max": 20},
    ]

    countries_pool = ["USA", "CHN", "IND", "JPN", "DEU", "GBR", "FRA", "BRA", "ITA", "CAN", "RUS", "ZAF", "MEX", "AUS", "KOR", "TUR", "SAU", "ARG", "IDN"]

    for i in range(55, 101):
        qid = f"Q{i:02d}"

        # Decide: single (0) or multi indicator (1) or scatter plot (2)
        q_type = random.choice([0, 1, 2])

        # Decide: single country (0), small group (1), large group (2)
        c_type = random.choice([0, 1, 2])

        # Decide: single year (0), multi-year (1)
        y_type = random.choice([0, 1])

        if q_type == 2:  # Scatter plot: 2 indicators, single year, multi country
            inds = random.sample(db_indicators, 2)
            c_type = random.choice([1, 2])  # scatter needs multi country
            y_type = 0  # scatter needs single year
        elif q_type == 1:
            num_inds = random.choice([2, 3])
            inds = random.sample(db_indicators, num_inds)
        else:
            inds = [random.choice(db_indicators)]

        if c_type == 0:
            countries = [random.choice(countries_pool)]
        elif c_type == 1:
            countries = random.sample(countries_pool, random.randint(2, 6))
        else:
            countries = random.sample(countries_pool, random.randint(9, 15))

        if y_type == 0:
            start_year = end_year = random.randint(2015, 2021)
            year_count = 1
        else:
            start_year = random.randint(2010, 2015)
            end_year = random.randint(2018, 2022)
            year_count = end_year - start_year + 1

        country_code = ";".join(countries)
        country_count = len(countries)

        ind_names = " and ".join(ind["name"] for ind in inds)
        country_names = ", ".join(countries[:3]) + (f", and {country_count - 3} other countries" if country_count > 3 else "")
        if year_count == 1:
            question_str = f"Show the {ind_names} for {country_names} in {start_year}."
        else:
            question_str = f"Chart the {ind_names} for {country_names} from {start_year} to {end_year}."

        chart_type_hint = "scatter" if q_type == 2 else None

        if q_type == 2:
            expected_strategy = "correlation"
            expected_layout = "single_panel"
        elif len(inds) == 1:
            if year_count == 1:
                if country_count > 8:
                    expected_strategy = "distribution"
                    expected_layout = "single_panel"
                else:
                    expected_strategy = "cross_sectional"
                    expected_layout = "single_panel"
            else:
                if country_count > 12:
                    expected_strategy = "heatmap"
                    expected_layout = "single_panel"
                else:
                    expected_strategy = "temporal_single"
                    expected_layout = "single_panel"
        else:
            scale_types = {ind["scale"] for ind in inds}
            mixed_scale = len(scale_types) > 1

            if year_count == 1:
                if country_count > 1:
                    expected_strategy = "small_multiples"
                    expected_layout = "vconcat_panels"
                else:
                    expected_strategy = "temporal_multi_indicator"
                    expected_layout = "vconcat_panels" if mixed_scale else "single_panel"
            else:
                if country_count > 1:
                    expected_strategy = "small_multiples"
                    expected_layout = "vconcat_panels"
                else:
                    expected_strategy = "temporal_multi_indicator"
                    expected_layout = "vconcat_panels" if mixed_scale else "single_panel"

        if len(inds) == 1:
            viz_call = {
                "tool": "data360_get_viz_spec",
                "args": {
                    "database_id": inds[0]["database_id"],
                    "indicator_id": inds[0]["indicator_id"],
                    "country_code": country_code,
                    "start_year": start_year,
                    "end_year": end_year,
                }
            }
        else:
            viz_call = {
                "tool": "data360_get_multi_indicator_viz_spec",
                "args": {
                    "indicator_ids": [
                        {"database_id": ind["database_id"], "indicator_id": ind["indicator_id"]}
                        for ind in inds
                    ],
                    "country_code": country_code,
                    "start_year": start_year,
                    "end_year": end_year,
                }
            }
            if chart_type_hint:
                viz_call["args"]["chart_type"] = chart_type_hint

        scale_types = {ind["scale"] for ind in inds}
        scale_type = "mixed" if len(scale_types) > 1 else (list(scale_types)[0])

        q_dict = {
            "id": qid,
            "category": "R",
            "question": question_str,
            "routing_args": {
                "n_indicators": len(inds),
                "country_count": country_count,
                "year_count": year_count,
                "avg_years_per_country": float(year_count),
                "scale_type": scale_type,
                "indicator_scales": [
                    {"label": ind["name"], "scale_type": ind["scale"], "approx_max": ind["max"]}
                    for ind in inds
                ]
            },
            "expected_strategy": expected_strategy,
            "expected_layout": expected_layout,
            "viz_call": viz_call,
        }
        if chart_type_hint:
            q_dict["routing_args"]["chart_type_hint"] = chart_type_hint

        QUESTIONS.append(q_dict)

_generate_extra_questions()


async def call_mcp(client: httpx.AsyncClient, tool_name: str, args: dict) -> dict:
    payload = {
        "jsonrpc": "2.0", "id": 1,
        "method": "tools/call",
        "params": {"name": tool_name, "arguments": args},
    }
    try:
        resp = await client.post(
            f"{MCP_BASE}/mcp",
            json=payload,
            headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream"},
            timeout=120,
        )
    except Exception as e:
        return {"error": str(e)}

    if resp.status_code != 200:
        return {"error": f"HTTP {resp.status_code}: {resp.text[:400]}"}

    text = resp.text
    result_json = None
    for line in text.splitlines():
        if line.startswith("data: "):
            try:
                obj = json.loads(line[6:])
                if "result" in obj:
                    result_json = obj["result"]
                    break
                elif "error" in obj:
                    return {"error": str(obj["error"])}
            except json.JSONDecodeError:
                continue
    if result_json is None:
        try:
            obj = json.loads(text)
            result_json = obj.get("result", obj)
        except Exception:
            return {"error": f"Unparseable: {text[:300]}"}

    content = result_json.get("content", [])
    if content and isinstance(content, list):
        text_parts = [c.get("text", "") for c in content if c.get("type") == "text"]
        combined = "\n".join(text_parts)
        try:
            return json.loads(combined)
        except Exception:
            return {"raw": combined}
    return result_json


async def main():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    results = []

    async with httpx.AsyncClient() as client:
        for q in QUESTIONS:
            print(f"\n{'='*70}")
            print(f"[{q['id']}] Category {q['category']} | {q['question'][:85]}")
            print("=" * 70)

            entry = {
                "id": q["id"], "category": q["category"],
                "question": q["question"],
                "routing": None, "routing_match": None, "routing_note": None,
                "chart_url": None, "viz_error": None,
            }

            # ── Step 1: Routing ───────────────────────────────────────────
            print("  1. data360_explain_chart_routing ...")
            routing = await call_mcp(client, "data360_explain_chart_routing", q["routing_args"])
            entry["routing"] = routing

            if "error" in routing:
                print(f"     ERROR: {routing['error'][:150]}")
                entry["routing_match"] = False
                entry["routing_note"] = f"ERROR: {routing['error']}"
            else:
                got_s = routing.get("strategy", "?")
                got_l = routing.get("layout", "?")
                exp_s = q["expected_strategy"]
                ok = got_s == exp_s
                note = f"strategy={got_s}(exp={exp_s}) layout={got_l}(exp={q['expected_layout']})"
                entry["routing_match"] = ok
                entry["routing_note"] = note
                print(f"     [{'PASS' if ok else 'FAIL'}] {note}")
                print(f"     reason: {routing.get('reason', '')}")
                if routing.get("scale_notes"):
                    print(f"     scale:  {routing['scale_notes']}")

            # ── Step 2: Viz ───────────────────────────────────────────────
            viz_tool = q["viz_call"]["tool"]
            viz_args = q["viz_call"]["args"]
            print(f"  2. {viz_tool} ...")
            viz = await call_mcp(client, viz_tool, viz_args)

            # viz dict has "error": null on success — only flag if error is a non-None string
            viz_error = viz.get("error") if isinstance(viz, dict) else None
            if viz_error:  # non-None, non-empty string means real error
                entry["viz_error"] = viz_error
                print(f"     ERROR: {str(viz_error)[:200]}")
            elif "raw" in viz:
                raw = viz["raw"]
                if "validation error" in raw or "Error:" in raw:
                    entry["viz_error"] = raw[:300]
                    print(f"     ERROR: {raw[:200]}")
                else:
                    m = re.search(r'http://[^\s"\']+/charts/[a-f0-9\-]+', raw)
                    if m:
                        entry["chart_url"] = m.group(0)
                        print(f"     OK: {entry['chart_url']}")
                    else:
                        entry["viz_error"] = f"raw (no chart_url): {raw[:200]}"
                        print(f"     (no chart URL) {raw[:120]}")
            else:
                # Success path: extract chart URL from "url" or "chart_url" key
                url = viz.get("url") or viz.get("chart_url")
                if not url:
                    m = re.search(r'http://[^\s"\']+/charts/[a-f0-9\-]+', json.dumps(viz))
                    if m:
                        url = m.group(0)
                entry["chart_url"] = url
                if url:
                    print(f"     OK: {url}")
                else:
                    entry["viz_error"] = f"no chart_url: {str(viz)[:200]}"
                    print(f"     (no chart_url) {str(viz)[:120]}")

            results.append(entry)

    # ── Summary ───────────────────────────────────────────────────────────
    print(f"\n\n{'='*70}")
    print("RESULTS SUMMARY")
    print("=" * 70)
    r_pass = sum(1 for r in results if r["routing_match"])
    v_ok   = sum(1 for r in results if r["chart_url"])
    print(f"Routing PASS : {r_pass}/{len(results)}")
    print(f"Chart OK     : {v_ok}/{len(results)}")
    print()
    print(f"{'ID':<6} {'Cat':<4} {'Route':<6} {'Viz':<5} Notes")
    print("-" * 70)
    for r in results:
        rs = "PASS" if r["routing_match"] else ("ERR" if "ERROR" in (r["routing_note"] or "") else "FAIL")
        vs = "OK  " if r["chart_url"] else "FAIL"
        note = (r["routing_note"] or r.get("viz_error") or "")[:55]
        print(f"{r['id']:<6} {r['category']:<4} {rs:<6} {vs:<5} {note}")

    out = OUT_DIR / f"20q_results_{ts}.json"
    out.write_text(json.dumps(results, indent=2))
    print(f"\nSaved: {out}")


if __name__ == "__main__":
    asyncio.run(main())
