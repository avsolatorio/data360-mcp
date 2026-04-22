import logging

import os
import dotenv
from fastmcp import FastMCP
from fastmcp.client.sampling.handlers.openai import OpenAISamplingHandler

_logger = logging.getLogger(__name__)

# Load .env so OPENAI_API_KEY is available
dotenv.load_dotenv()

# Only instantiate the OpenAI handler if an API key actually exists.
# Otherwise, AsyncOpenAI() will immediately crash the server on startup.
sampling_handler = None
if os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY_MCP"):
    try:
        sampling_handler = OpenAISamplingHandler(default_model="gpt-4o-mini")
    except Exception:
        _logger.warning(
            "Failed to initialize OpenAISamplingHandler; server-side sampling disabled.",
            exc_info=True,
        )

# NOTE: base definition to allow for mounting of resources, prompts, tools, independently
mcp = FastMCP(
    "Data360 MCP Server",
    sampling_handler=sampling_handler,
    sampling_handler_behavior="fallback",
)
