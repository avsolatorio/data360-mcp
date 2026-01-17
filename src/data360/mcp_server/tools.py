"""MCP Tools for the Data360 server.

Optimized for minimal token consumption:
- Search fetches ref_country, time_periods, dimensions in ONE call
- Python processes them to extract has_country, latest_data_point, available dimensions
- No extra API calls needed
"""

from typing import Any

from data360 import api as data360_api
from data360 import providers as data360_providers

from ._server_definition import mcp


async def _resolve_country_code(country_query: str) -> str | None:
    """Resolve country name to code using cached REF_AREA codelist."""
    if not country_query:
        return None
    # Already a 3-letter code
    if len(country_query) == 3 and country_query.isupper():
        return country_query
    # Look up in codelist
    matches = await data360_providers.find_codelist_value("REF_AREA", country_query, limit=1)
    if matches and matches[0].get("score", 0) >= 70:
        return matches[0].get("id")
    return None


async def _search_indicators(
    query: str,
    required_country: str | None = None,
    limit: int = 5,
) -> dict[str, Any]:
    """Search for Data360 indicators with enriched metadata for selection.
    
    Returns top indicators sorted by relevance. If required_country is provided:
    - Results include covers_country flag (True if country has data)
    - Sorted with covers_country=True first, then by latest_data descending
    - First indicator in list is the BEST MATCH - pick that one
    
    Args:
        query: Search query (e.g., "unemployment rate", "poverty")
        required_country: Country name or code (e.g., "Kenya" or "KEN")
        limit: Max results (default 5)
    
    Returns:
        indicators: List with:
            - idno, database_id, name
            - definition_short (max 100 chars)
            - periodicity (Annual/Monthly)
            - latest_data (most recent year)
            - covers_country (True if country has data, only if required_country provided)
            - dimensions (list of available disaggregations like SEX, AGE)
    
    Selection: Pick the FIRST indicator - it's sorted by country coverage and recency.
    """
    # Resolve country code upfront using cached codelist
    country_code = None
    if required_country:
        country_code = await _resolve_country_code(required_country)
    
    # Fetch all needed metadata in ONE search call
    search_result = await data360_api.search(
        query=query,
        limit=limit,
        select_fields=[
            "idno", "name", "database_id", "definition_long",
            "periodicity", "time_periods", "ref_country", "dimensions"
        ]
    )
    
    if search_result.error:
        return {"error": search_result.error, "indicators": []}
    
    if not search_result.items:
        return {"error": f"No indicators found for: '{query}'", "indicators": []}
    
    # Process each indicator
    indicators = []
    for item in search_result.items:
        raw = item.model_dump() if hasattr(item, 'model_dump') else vars(item)
        
        # Build compact indicator
        ind: dict[str, Any] = {
            "idno": raw.get("idno"),
            "database_id": raw.get("database_id"),
            "name": raw.get("name"),
            "definition_short": (raw.get("definition_long") or "")[:100],
            "periodicity": raw.get("periodicity"),
        }
        
        # Extract latest_data from time_periods
        time_periods = raw.get("time_periods", [])
        if time_periods and isinstance(time_periods, list):
            tp = time_periods[0] if isinstance(time_periods[0], dict) else {}
            ind["latest_data"] = tp.get("LATEST_DATA_POINT") or tp.get("end")
        else:
            ind["latest_data"] = None
        
        # Check covers_country from ref_country
        ref_country = raw.get("ref_country", [])
        if country_code and ref_country and isinstance(ref_country, list):
            country_codes = [
                c.get("code") if isinstance(c, dict) else c 
                for c in ref_country
            ]
            ind["covers_country"] = country_code in country_codes
        elif country_code:
            ind["covers_country"] = False
        
        # Extract dimension names from series_description/dimensions
        # The API returns labels like "Sex", "Age", "Residential area" - map to codes
        dimensions = raw.get("dimensions", [])
        
        # Map from human-readable labels to dimension codes
        label_to_code = {
            "sex": "SEX",
            "age": "AGE", 
            "residential area": "URBANISATION",  # API uses "Residential area" for URBANISATION
            "urbanisation": "URBANISATION",
            "education": "EDUCATION",
        }
        
        useful_dims = []
        if dimensions and isinstance(dimensions, list):
            for dim in dimensions:
                if isinstance(dim, dict):
                    label = (dim.get("label") or "").lower()
                    if label in label_to_code:
                        useful_dims.append(label_to_code[label])
        
        ind["dimensions"] = useful_dims if useful_dims else None
        
        indicators.append(ind)
    
    # Sort: covers_country=True first, then by latest_data descending
    if country_code:
        indicators.sort(key=lambda x: (
            not x.get("covers_country", False),
            -(int(x.get("latest_data") or 0) if str(x.get("latest_data", "")).isdigit() else 0)
        ))
    
    result: dict[str, Any] = {
        "indicators": indicators,
        "total_found": search_result.total_count,
    }
    if country_code:
        result["required_country"] = country_code
    
    return result


# Register tools
search_indicators = mcp.tool(
    _search_indicators,
    name="data360_search_indicators",
    description=_search_indicators.__doc__,
)

get_metadata = mcp.tool(
    data360_api.get_metadata,
    name="data360_get_metadata",
    description=data360_api.get_metadata.__doc__,
)

get_data = mcp.tool(
    data360_api.get_data,
    name="data360_get_data",
    description=data360_api.get_data.__doc__,
)

get_disaggregation = mcp.tool(
    data360_api.get_disaggregation,
    name="data360_get_disaggregation",
    description=data360_api.get_disaggregation.__doc__,
)

find_codelist_value = mcp.tool(
    data360_providers.find_codelist_value,
    name="data360_find_codelist_value",
    description=data360_providers.find_codelist_value.__doc__,
)

list_indicators = mcp.tool(
    data360_api.get_indicators,
    name="data360_list_indicators",
    description=data360_api.get_indicators.__doc__,
)
