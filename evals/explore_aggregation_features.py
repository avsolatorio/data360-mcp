import asyncio
import json
import os
import sys
from pathlib import Path

# Insert project root to path
_REPO = Path(__file__).parent.parent
sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env.evals", override=False)
    load_dotenv(_REPO / ".env", override=False)
except ImportError:
    pass

from evals.test_viz_scorer import _call_mcp

async def test_aggregations():
    print("======================================================================")
    print("🔍 Scouting Data360 Aggregation, Ranking, and Comparison Features")
    print("======================================================================\n")

    # 1. Test data360_summarize_data
    print("--- Testing data360_summarize_data ---")
    summarize_args = {
        "database_id": "IMF_WEO",
        "indicator_id": "IMF_WEO_NGDP_RPCH", # Real GDP Growth
        "country_code": "MEX;COL;CHL",
        "start_year": 2018,
        "end_year": 2023
    }
    try:
        res = await _call_mcp("data360_summarize_data", summarize_args)
        print("✓ Success. Summary output keys:", list(res.keys()) if isinstance(res, dict) else type(res))
        if isinstance(res, dict):
            print("Summary details:")
            print(json.dumps(res, indent=2)[:500] + "\n...")
    except Exception as e:
        print("✗ Fail:", e)

    # 2. Test data360_rank_countries
    print("\n--- Testing data360_rank_countries ---")
    rank_args = {
        "database_id": "IMF_WEO",
        "indicator_id": "IMF_WEO_NGDP_RPCH",
        "country_codes": "DEU;FRA;ITA;ESP;NLD",
        "year": 2022,
        "order": "desc",
        "top_n": 5
    }
    try:
        res = await _call_mcp("data360_rank_countries", rank_args)
        print("✓ Success. Rank output keys:", list(res.keys()) if isinstance(res, dict) else type(res))
        if isinstance(res, dict):
            print("Rankings details:")
            print(json.dumps(res, indent=2)[:500] + "\n...")
    except Exception as e:
        print("✗ Fail:", e)

    # 3. Test data360_compare_countries
    print("\n--- Testing data360_compare_countries ---")
    compare_args = {
        "database_id": "IMF_WEO",
        "indicator_id": "IMF_WEO_NGDP_RPCH",
        "country_codes": "MEX;COL;CHL",
        "year": 2022,
        "include_time_series": True,
        "start_year": 2018,
        "end_year": 2023
    }
    try:
        res = await _call_mcp("data360_compare_countries", compare_args)
        print("✓ Success. Compare output keys:", list(res.keys()) if isinstance(res, dict) else type(res))
        if isinstance(res, dict):
            print("Comparison details:")
            print(json.dumps(res, indent=2)[:500] + "\n...")
    except Exception as e:
        print("✗ Fail:", e)

if __name__ == "__main__":
    asyncio.run(test_aggregations())
