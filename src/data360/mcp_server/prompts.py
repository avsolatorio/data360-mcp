"""Prompts for the Data360 MCP Server.

These prompts guide LLMs through common workflows.
"""

from ._server_definition import mcp


@mcp.prompt()
def indicator_search(
    query: str,
    country: str = "",
    required_dimensions: str = "",
) -> str:
    """Guide LLM to find and select the best indicator for a query.
    
    Args:
        query: Search query (e.g., "unemployment rate", "poverty")
        country: Optional country to validate (e.g., "Kenya")
        required_dimensions: Optional comma-separated dimensions (e.g., "SEX,AGE")
    """
    dims_list = required_dimensions.split(",") if required_dimensions else []
    
    return f"""To find the best indicator for '{query}':

1. Use enriched search:
   data360_search_indicators(
       query="{query}",
       limit=5,
       select_fields=["idno", "name", "database_id", "definition_long", "periodicity", "time_periods", "dimensions"]
   )

2. For promising candidates, validate with get_disaggregation:
   - Check TIME_PERIOD for actual years (may have gaps)
   - Check REF_AREA for country coverage{f" - verify '{country}' is available" if country else ""}
   - Check available dimensions{f" - need: {dims_list}" if dims_list else ""}

3. Pick indicator based on: relevance, coverage, dimensions
"""


@mcp.prompt()
def indicator_details(
    indicator_id: str,
    database_id: str,
    question: str = "",
) -> str:
    """Guide LLM to get appropriate metadata based on user question.
    
    Args:
        indicator_id: Indicator ID (e.g., "WB_WDI_SP_POP_TOTL")
        database_id: Database ID (e.g., "WB_WDI")
        question: Optional specific question to answer
    """
    return f"""To answer questions about indicator '{indicator_id}':

1. Read data360://metadata-fields to find which field answers the question

2. Map user question to field(s):
   - "how is it calculated" → ["methodology"]
   - "statistical concept" → ["statistical_concept"]
   - "what is this" → ["definition_long"]
   - "limitations" → ["limitation"]
   - "why important" → ["relevance"]

3. Call data360_get_metadata with select_fields to fetch ONLY needed fields:
   data360_get_metadata(
       database_id="{database_id}",
       indicator_id="{indicator_id}",
       select_fields=["methodology"]  # Only fetch what's needed
   )

User question: {question if question else "(general overview - use definition_long)"}
"""


@mcp.prompt()
def country_data(
    query: str,
    country: str,
    start_year: str = "",
    end_year: str = "",
) -> str:
    """Guide LLM through end-to-end data retrieval for a country.
    
    Args:
        query: Indicator search query
        country: Country name (e.g., "Kenya")
        start_year: Optional start year
        end_year: Optional end year
    """
    return f"""To get {query} data for {country}:

<thinking>
1. Need to find the right indicator
2. Need to convert country name to code
3. Need to validate data availability
4. Then fetch the data
</thinking>

**Step 1: Resolve country code**
data360_find_codelist_value(codelist_type="REF_AREA", query="{country}")

**Step 2: Search for indicator**
data360_search_indicators(
    query="{query}",
    limit=5,
    select_fields=["idno", "name", "database_id", "definition_long", "periodicity"]
)

**Step 3: Validate availability**
For chosen indicator, call:
data360_get_disaggregation(database_id=<db_id>, indicator_id=<ind_id>)
- Confirm country code is in REF_AREA
- Check TIME_PERIOD for available years{f" (looking for {start_year}-{end_year})" if start_year and end_year else ""}

**Step 4: Get data**
data360_get_data(
    database_id=<db_id>,
    indicator_id=<ind_id>,
    disaggregation_filters={{"REF_AREA": "<country_code>"}},
    start_year={start_year if start_year else "None"},
    end_year={end_year if end_year else "None"}
)
"""
