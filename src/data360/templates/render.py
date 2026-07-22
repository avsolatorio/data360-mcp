import os
from typing import Any
from jinja2 import Environment, FileSystemLoader, PackageLoader, select_autoescape

TEMPLATES_DIR = os.path.dirname(os.path.abspath(__file__))

try:
    _env = Environment(
        loader=PackageLoader("data360", "templates"),
        autoescape=select_autoescape(["html", "xml"]),
    )
except Exception:
    _env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        autoescape=select_autoescape(["html", "xml"]),
    )


def render_template(template_name: str, **context: Any) -> str:
    """Render a Jinja2 template file from src/data360/templates/."""
    template = _env.get_template(template_name)
    return template.render(**context)
