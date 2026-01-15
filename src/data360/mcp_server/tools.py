from data360 import api as data360_api
from data360 import providers as data360_providers

from ._server_definition import mcp

# directly wrap function as tool
# can redefine with decorator if implementation override required
# can add more metadata like description, etc as parameters to tool decorator call
search_indicators = mcp.tool(
    data360_api.search,
    name="data360_search_indicators",
    description=data360_api.search.__doc__,
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

# Reference area lookup tool
find_reference_area = mcp.tool(
    data360_providers.find_reference_areas,
    name="data360_find_reference_area",
    description="""Find reference areas (countries, regions) matching a query.

This tool validates that the geographic context needed to respond to the prompt
is valid based on the available reference areas from the Data360 codelist.

Args:
    query: The geographic entity to search for (e.g., "Kenya", "East Africa", "Sub-Saharan")
    limit: Maximum number of matches to return (default: 5)

Returns:
    A list of matching reference areas with id, name, and match score.

Example:
    find_reference_area("Kenya") → [{"id": "KEN", "name": "Kenya", "score": 100}]
    find_reference_area("Kanya") → [{"id": "KEN", "name": "Kenya", "score": 91}]  # handles typos
""",
)

# Primary search and validate tool
search_and_validate = mcp.tool(
    data360_api.search_and_validate,
    name="data360_search_and_validate",
    description="""Search for indicators and validate their capabilities (PRIMARY TOOL).

This is the recommended primary tool that combines:
1. Search for top K indicators matching the query
2. Fetch metadata for all K indicators in parallel
3. Cross-check capabilities (countries, dimensions available)
4. Return condensed, validated results sorted by relevance

Use this tool when you need to find the best indicator for a user query,
especially when the user specifies a country or demographic filters.

Args:
    query: Search query string (e.g., "unemployment rate", "poverty")
    required_country: Country name or code to validate (e.g., "Kenya" or "KEN")
    required_dimensions: List of required disaggregations (e.g., ["SEX", "AGE"])
    limit: Maximum number of indicators to search and validate (default: 5)

Returns:
    Dict with indicators list, each containing:
    - indicator_id, database_id, name, definition_short
    - has_country: Whether the indicator has data for the requested country
    - available_dimensions: List of available disaggregations
    - has_required_dimensions: Whether all required dimensions are available
    - time_range: {start, end} of available data

Example:
    search_and_validate("unemployment rate", required_country="Kenya", required_dimensions=["SEX"])
""",
)
