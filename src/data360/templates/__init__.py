"""Jinja2 template rendering helpers for Data360 MCP server HTML resources."""

from typing import Any
from jinja2 import Environment, PackageLoader, select_autoescape

_env = Environment(
    loader=PackageLoader("data360", "templates"),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_template(template_name: str, **context: Any) -> str:
    """Render a Jinja2 template file from src/data360/templates/."""
    template = _env.get_template(template_name)
    return template.render(**context)
