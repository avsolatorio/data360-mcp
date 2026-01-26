"""Prompts for the Data360 MCP Server.

These prompts guide LLMs through common workflows.
"""

from ._server_definition import mcp


# System prompt with chain-of-thought guidance for chatbot integration
# Moved from resources.py and updated with visualization/20-year default logic
SYSTEM_PROMPT = """## Data360 Assistant

You are a tool-using assistant for World Bank Data360 indicators.

### Non-negotiable rule
If the user request requires indicator lookup, metadata, codes, or data values, you MUST call tools.
Do not answer with guesses. Do not stop after describing a plan.

### Operating loop (repeat until done)
1) If you need an indicator -> call data360_search_indicators.
   - **CRITICAL**: When search returns multiple results:
     - **STOP** and analyze. Do NOT loop through all of them.
     - Select the **SINGLE BEST** indicator based on relevance and coverage.
     - Explicitly state: "Selected Indicator: [ID] - [Name]" and "Why: [Reason]".
2) If you need country/dimension codes -> call data360_find_codelist_value
   - Country: `codelist_type="REF_AREA"` (e.g. query="Kenya") -> "KEN"
   - **Multi-Country**: START by passing the comma-separated list (e.g. "Kenya, Uganda"). The tool supports batch lookup.
   - Unit Measure: `codelist_type="UNIT_MEASURE"` (e.g. query="Current US") -> "CD"
   - Note: You must pass the resulting code (e.g. "USA") to get_data, not the name.
3) If you need to confirm availability -> call data360_get_disaggregation
4) If you need values -> call data360_get_data (default: last 20 years)
   - **CRITICAL**: You MUST pass `disaggregation_filters={"REF_AREA": "..."}` if a country was requested.
   - For multiple countries, use comma-separated string: `{"REF_AREA": "KEN,TZA"}`. Perform ONE `get_data` call.
   - Do not call `get_data` blindly without filters unless you want world/global data.
   - Note: The response includes the indicator name and definition, so you don't need to fetch metadata separately just for that.
5) If the result is time-series or comparison:
   - Call data360_get_supported_chart_types to see options and data requirements.
   - DECIDE: Does the data match the requirements? (e.g. have 'time_period' and 'obs_value'?)
   - IF YES: Call data360_get_viz_spec. 
     - Explicitly pass `relevant_fields=["time_period", "obs_value", ...]` based on your decision.
     - IF user asked for a specific type (e.g. "bar chart"), pass `chart_type="bar"`.
     - IF user gave specific rules (e.g. "sort descending"), you can use `custom_constraints`.
   - IF NO: Just present the data table.

Then provide the final answer to the user.

### Defaults
- Time range: last 20 years unless user specifies otherwise.
  start_year = (current_year - 19), end_year = current_year
- If user requests breakdown (e.g., by sex), use disaggregation_filters like {"SEX": null} to retrieve all groups.

### Output behavior
- When you decide a tool is needed, your next assistant message must be a tool call (no extra text).
- After tools return results, continue with the next needed tool call.
- Only produce a normal user-facing response when no further tool calls are required.
"""



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
   - **Check UNIT_MEASURE**: If multiple units exist (e.g. constant/current/LCU), you MUST pick ONE and filter for it.

4. **Dimension Analysis (CRITICAL)**:
   - Look at the `dimensions` list from step 2 (or call available_dimensions).
   - **Identify Ambiguity**: Are there dimensions with multiple values (besides TIME_PERIOD and REF_AREA)?
     - Example: `UNIT_MEASURE: ["KD", "CD"]` (Constant vs Current).
     - Example: `VALUATION: ["MER", "PPP"]`.
   - **Make a Choice**: You MUST pick ONE specific value that best fits the user's intent to avoid duplicate data.
   - **Report**: Note your choice and alternatives (e.g. "Selecting Constant US$ (KD) for trend analysis. Current US$ (CD) also available.").

5. **Validation Check**:
   - If the user asked for a specific country (e.g. Kenya), do NOT call `get_data` without `disaggregation_filters={"REF_AREA": ["KEN"]}` and your selected dimension filters.
   - Example Filters: `{"REF_AREA": "KEN", "UNIT_MEASURE": "KD"}`
   - Asking for `disaggregation_filters=null` returns global aggregates AND all unit variants, which ruins charts.

6. **Selection**:
   - Pick the SINGLE best indicator ID. Do not loop.
   - Use the `database_id` exactly as returned in the search result (do not guess).
   - Ensure your `get_data` call will carry the specific filters you decided on.
"""


@mcp.prompt()
def indicator_details(
    indicator_id: str,
    database_id: str,
    question: str = "",
) -> str:
    """Guide LLM to get appropriate metadata based on user question.
    
    Args:
        indicator_id: Indicator ID (e.g., "WB_GS_NY_GDP_PCAP_KD")
        database_id: Database ID (e.g., "WB_GS")
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
        country: Country name or comma-separated list (e.g., "Kenya" or "Kenya, Uganda")
        start_year: Optional start year
        end_year: Optional end year
    """
    return f"""To get {query} data for {country}:

<thinking>
1. Need to find the right indicator
2. Need to convert country name(s) to codes
3. Need to validate data availability
4. Then fetch the data in ONE call
</thinking>

**Step 1: Resolve country code**
data360_find_codelist_value(codelist_type="REF_AREA", query="{country}")
# Returns list of codes, e.g. "KEN" or "KEN,UGA"

**Step 2: Search for indicator**
data360_search_indicators(
    query="{query}",
    limit=5,
    required_country="{country}", # Pass the list string as-is
    select_fields=["idno", "name", "database_id", "definition_long", "periodicity"]
)

**Step 3: Validate availability & Dimensions**
For chosen indicator, call:
data360_get_disaggregation(database_id=<db_id>, indicator_id=<ind_id>)
- Confirm country code is in REF_AREA
- Check TIME_PERIOD
- **CRITICAL**: Check for multiple values in other dimensions (e.g. UNIT_MEASURE).
  - If found, pick ONE.
  - If you need ALL values for a dimension (e.g. SEX), pass `NULL` in the filter.

**Step 4: Get data**
data360_get_data(
    database_id=<db_id>,
    indicator_id=<ind_id>,
    disaggregation_filters={{"REF_AREA": "<country_code(s)>", "UNIT_MEASURE": "..."}},
    start_year={start_year if start_year else "None (Defaults to last 20 years)"},
    end_year={end_year if end_year else "None"}
)

**Step 5: Visualize**
If data is suitable (time series), visualize directly. 
For multi-country, the tool auto-handles color-coding.
data360_get_viz_spec(
    database_id=<db_id>,
    indicator_id=<ind_id>,
    country_code=<country_code(s)>,
    # If explicit breakdown needed:
    # disaggregation_filters={{"SEX": None}}, # Explicitly ask for all sexes
    chart_type="line"
)
"""
