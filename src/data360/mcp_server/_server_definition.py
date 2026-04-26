import logging

import dotenv
from fastmcp import FastMCP

from .sampling import has_llm_credentials, litellm_sampling_handler

_logger = logging.getLogger(__name__)

# Load .env so provider credentials (OPENAI_API_KEY, ANTHROPIC_API_KEY, etc.)
# and LITELLM_MODEL are available before the handler check below.
dotenv.load_dotenv()

# Only wire up the server-side sampling handler when at least one LLM
# provider credential is available. Without credentials, the handler would
# fail on every invocation, so it is better to leave it unset and let
# FastMCP skip straight to the client (Tier 1) or rule-based (Tier 3) path.
sampling_handler = None
if has_llm_credentials():
    sampling_handler = litellm_sampling_handler
    _logger.info("Server-side LiteLLM sampling handler enabled.")
else:
    _logger.info(
        "No LLM credentials found; server-side sampling handler disabled. "
        "Set LITELLM_MODEL and one of: OPENAI_API_KEY, ANTHROPIC_API_KEY, "
        "GEMINI_API_KEY, MISTRAL_API_KEY, or AWS_ACCESS_KEY_ID."
    )

# NOTE: base definition to allow for mounting of resources, prompts, tools, independently
mcp = FastMCP(
    "Data360 MCP Server",
    sampling_handler=sampling_handler,
    sampling_handler_behavior="fallback",
)
