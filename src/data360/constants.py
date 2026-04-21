"""Shared constants for the data360 package.

This module is intentionally dependency-free (no MCP server imports, no FastMCP)
so it can be safely imported from both ``api.py`` and ``mcp_server/resources.py``
without triggering circular import errors.
"""

# Registry of all known Data360 databases.
# Each entry: {"id": "<database_id>", "name": "<human-readable name>"}
#
# IMPORTANT: Keep this list in sync with the databases actually available via the
# Data360 API. The ``name`` value here is the authoritative label that the MCP
# server surfaces to LLMs. An incorrect name leads directly to hallucinations in
# user-facing output (e.g. "WB_GS" being described as "Global Statistics" instead
# of "Gender Statistics").
DATABASES: dict = {
    "databases": [
        {"id": "WB_WDI", "name": "World Development Indicators"},
        {"id": "WB_GS", "name": "Gender Statistics"},
        {"id": "WB_HNP", "name": "Health, Nutrition & Population"},
        {"id": "WB_HCP", "name": "Human Capital Project"},
        {"id": "WB_SSGD", "name": "Social Sustainability Global Database"},
        {"id": "WB_ESG", "name": "Environment, Social & Governance"},
        {"id": "WB_SE4ALL", "name": "Sustainable Energy for All"},
        {"id": "WB_RISE", "name": "RISE Regulatory Indicators"},
        {"id": "WB_WITS", "name": "World Integrated Trade Solution"},
        {"id": "IPC_IPC", "name": "IPC Acute Food Insecurity"},
        {"id": "OECD_BROADBAND", "name": "OECD Broadband Statistics"},
        {"id": "OECD_IDD", "name": "OECD Income Distribution"},
        {"id": "ITU_DH", "name": "ITU Digital Development"},
        {"id": "WJP_ROL", "name": "World Justice Project Rule of Law"},
        {"id": "WEF_TTDI", "name": "WEF Travel & Tourism Development"},
        {"id": "IMF_FAS", "name": "IMF Financial Access Survey"},
    ],
    "note": (
        "Use 'database_id' returned by data360_search_indicators. "
        "Call data360_list_indicators(database_id) to see available indicators."
    ),
}

# Pre-built lookup: database_id → human-readable name.
# Derived from DATABASES above; avoids repeated list traversal at call sites.
DB_NAME_LOOKUP: dict[str, str] = {
    db["id"]: db["name"] for db in DATABASES["databases"]
}
