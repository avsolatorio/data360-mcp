"""Generic LiteLLM-based sampling handler for MCP server-side fallback.

Supports any provider through a unified interface. Set the LITELLM_MODEL
environment variable and the corresponding credentials:

  Provider         | LITELLM_MODEL example                          | Credentials
  -----------------|------------------------------------------------|------------------------------
  OpenAI (default) | gpt-4o-mini                                    | OPENAI_API_KEY
  Anthropic        | anthropic/claude-haiku-3-5                     | ANTHROPIC_API_KEY
  Google Gemini    | gemini/gemini-2.0-flash                        | GEMINI_API_KEY
  Mistral AI       | mistral/mistral-small-latest                   | MISTRAL_API_KEY
  AWS Bedrock      | bedrock/mistral.mistral-7b-instruct-v0:2       | AWS_ACCESS_KEY_ID,
  (Mistral SLMs)   | bedrock/mistral.mixtral-8x7b-instruct-v0:1    | AWS_SECRET_ACCESS_KEY,
                   |                                                | AWS_REGION_NAME

When no LITELLM_MODEL is set, defaults to gpt-4o-mini.

LiteLLM infers the provider from the model string prefix (e.g. "anthropic/",
"gemini/", "bedrock/") and picks up credentials automatically from the
environment. No additional configuration is needed.
"""
import logging
import os

from fastmcp.client.sampling import RequestContext, SamplingMessage, SamplingParams

_logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-4o-mini"

# Environment variables whose presence indicates that a supported LLM
# provider is configured. LiteLLM picks these up automatically.
_CREDENTIAL_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    # AWS Bedrock uses standard AWS credentials; check the access key as proxy.
    "AWS_ACCESS_KEY_ID",
)


def has_llm_credentials() -> bool:
    """Return True if at least one supported LLM provider credential is set."""
    return any(os.environ.get(k) for k in _CREDENTIAL_ENV_VARS)


async def litellm_sampling_handler(
    messages: list[SamplingMessage],
    params: SamplingParams,
    context: RequestContext,
) -> str:
    """Async sampling handler that routes requests through LiteLLM.

    The model is resolved from the LITELLM_MODEL environment variable,
    defaulting to gpt-4o-mini. Provider credentials are picked up
    automatically by LiteLLM from the environment.

    Raises on failure so that FastMCP can propagate the error back to the
    caller (who should catch it and fall back to rule-based decomposition).
    """
    import litellm  # noqa: PLC0415 -- lazy import, not required at server startup

    llm_messages: list[dict] = []
    if params.systemPrompt:
        llm_messages.append({"role": "system", "content": params.systemPrompt})

    for msg in messages:
        content = (
            msg.content.text
            if hasattr(msg.content, "text")
            else str(msg.content)
        )
        llm_messages.append({"role": msg.role, "content": content})

    model = os.environ.get("LITELLM_MODEL", DEFAULT_MODEL)

    try:
        response = await litellm.acompletion(
            model=model,
            messages=llm_messages,
            temperature=params.temperature or 0.2,
            max_tokens=params.maxTokens or 512,
        )
        return response.choices[0].message.content
    except Exception:
        _logger.warning(
            "LiteLLM sampling call failed (model=%s). "
            "Check provider credentials and LITELLM_MODEL.",
            model,
            exc_info=True,
        )
        raise  # Re-raise so the caller falls through to rule-based decomposition
