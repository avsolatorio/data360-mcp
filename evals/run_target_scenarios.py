import asyncio
import os
import sys
from explore_chart_types import run_exploration, print_summary, SERVER_UP, OPENAI_KEY_SET, MCP_BASE_URL

SCENARIOS = [
    {
        "id": "target_g7_1",
        "label": "G7 WWBI employment, 7c (2010-2022)",
        "description": "Faceted chart of WWBI public employment (WB_WWBI, with sector breakdown) across 7 countries from 2010 to 2022. Expect: small_multiples faceted panels.",
        "database_id": "WB_WWBI",
        "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "USA;GBR;DEU;FRA;JPN;CAN;ITA",
        "start_year": 2010,
        "end_year": 2022,
        "mode": "viz"
    },
    {
        "id": "target_g7_2",
        "label": "G7 WWBI employment, 7c (2005-2020)",
        "description": "Faceted chart of WWBI public employment (WB_WWBI, with sector breakdown) across 7 countries from 2005 to 2020. Expect: small_multiples faceted panels.",
        "database_id": "WB_WWBI",
        "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "USA;GBR;DEU;FRA;JPN;CAN;ITA",
        "start_year": 2005,
        "end_year": 2020,
        "mode": "viz"
    },
    {
        "id": "target_g7_3",
        "label": "G7 WWBI employment, 7c (2012-2022)",
        "description": "Faceted chart of WWBI public employment (WB_WWBI, with sector breakdown) across 7 countries from 2012 to 2022. Expect: small_multiples faceted panels.",
        "database_id": "WB_WWBI",
        "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "USA;GBR;DEU;FRA;JPN;CAN;ITA",
        "start_year": 2012,
        "end_year": 2022,
        "mode": "viz"
    },
    {
        "id": "target_ea_1",
        "label": "East Africa WWBI employment, 6c (2010-2022)",
        "description": "Faceted chart of WWBI public employment (WB_WWBI, with sector breakdown) across 6 countries from 2010 to 2022. Expect: small_multiples faceted panels.",
        "database_id": "WB_WWBI",
        "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "KEN;ETH;TZA;UGA;RWA;MOZ",
        "start_year": 2010,
        "end_year": 2022,
        "mode": "viz"
    },
    {
        "id": "target_ea_2",
        "label": "East Africa WWBI employment, 6c (2005-2020)",
        "description": "Faceted chart of WWBI public employment (WB_WWBI, with sector breakdown) across 6 countries from 2005 to 2020. Expect: small_multiples faceted panels.",
        "database_id": "WB_WWBI",
        "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "KEN;ETH;TZA;UGA;RWA;MOZ",
        "start_year": 2005,
        "end_year": 2020,
        "mode": "viz"
    },
    {
        "id": "target_ea_3",
        "label": "East Africa WWBI employment, 6c (2012-2022)",
        "description": "Faceted chart of WWBI public employment (WB_WWBI, with sector breakdown) across 6 countries from 2012 to 2022. Expect: small_multiples faceted panels.",
        "database_id": "WB_WWBI",
        "indicator_id": "WB_WWBI_BI_EMP_TOTL_PB",
        "country_code": "KEN;ETH;TZA;UGA;RWA;MOZ",
        "start_year": 2012,
        "end_year": 2022,
        "mode": "viz"
    }
]

async def main():
    if not SERVER_UP:
        print(f"ERROR: MCP server not reachable at {MCP_BASE_URL}")
        sys.exit(1)
    if not OPENAI_KEY_SET:
        print("ERROR: OPENAI_API_KEY not set in .env.evals")
        sys.exit(1)

    print(f"Running targeted evaluation for {len(SCENARIOS)} scenarios...")
    results = await run_exploration(SCENARIOS, pass_threshold=7.0)

    print("\nTargeted Run Completed!")
    print_summary(results, pass_threshold=7.0)

if __name__ == "__main__":
    # Add parent dir to python path
    sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    asyncio.run(main())
