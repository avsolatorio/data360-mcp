"""MCP Apps for the Data360 server.

Registers ui:// resources so hosts that support the MCP Apps extension
can render charts, search results, and the QR example inline. Tools are
linked to these resources via AppConfig in tools.py.
"""

from .apps_resources import (
    CHART_VIEW_URI,
    QR_VIEW_URI,
    SEARCH_VIEW_URI,
    chart_view_resource,
    qr_view_resource,
    search_view_resource,
)

# Register UI resources (must run before tools that reference them are used)
chart_view_resource()
search_view_resource()
qr_view_resource()

__all__ = [
    "CHART_VIEW_URI",
    "QR_VIEW_URI",
    "SEARCH_VIEW_URI",
    "chart_view_resource",
    "qr_view_resource",
    "search_view_resource",
]
