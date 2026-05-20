"""Security validation for MCP tool calls to prevent prompt injection attacks."""

import logging
import re
from typing import Any

_logger = logging.getLogger(__name__)

# Prompt injection patterns that indicate malicious intent
PROMPT_INJECTION_PATTERNS = [
    # Tool enumeration attempts
    r"list\s+(all\s+)?(available\s+)?tools",
    r"show\s+me\s+(all\s+)?(available\s+)?tools",
    r"what\s+tools\s+(do\s+you\s+have|are\s+available)",
    r"enumerate\s+tools",
    r"get\s+all\s+tools",
    # Instruction override attempts
    r"ignore\s+(previous|all|your)\s+instructions",
    r"disregard\s+(previous|all|your)\s+instructions",
    r"forget\s+(previous|all|your)\s+instructions",
    r"new\s+instructions?:",
    r"system\s+prompt:",
    r"\byou\s+are\s+now\s+(?:a|an|the)\b",
    # Role manipulation
    r"^\s*act\s+as\s+(?:a|an|the)\b",
    r"pretend\s+to\s+be",
    r"you\s+are\s+(a\s+)?developer",
    r"you\s+are\s+(a\s+)?admin",
    # Multi-tool chaining attempts
    r"\bthen\s+(call|execute|run)\b",
    r"after\s+that,?\s+(call|execute|run)",
    r"next,?\s+(call|execute|run)",
    r"and\s+then\s+(call|execute|run)",
    # System/internal method access
    r"__\w+__",  # Dunder methods
    r"(?:^|[^\w])\.system\b",
    r"(?:^|[^\w])\.internal\b",
    r"(?:^|[^\w])\.admin\b",
]

# Compile patterns for performance
_INJECTION_REGEX = [
    re.compile(pattern, re.IGNORECASE) for pattern in PROMPT_INJECTION_PATTERNS
]


def validate_tool_call(
    tool_name: str, arguments: dict[str, Any]
) -> tuple[bool, str | None]:
    """
    Validate a tool call for security issues.

    Returns:
        (is_valid, error_message)
        - (True, None) if valid
        - (False, "error message") if invalid
    """

    # Check tool name for suspicious patterns
    if not tool_name or not isinstance(tool_name, str):
        return (False, "Invalid tool name")

    # Only allow data360 tools
    if not tool_name.startswith("data360_"):
        return (
            False,
            f"Unauthorized tool: {tool_name}. Only data360_* tools are allowed.",
        )

    # Check arguments for prompt injection
    if arguments:
        for param_name, value in arguments.items():
            if isinstance(value, str):
                # Check for prompt injection patterns
                for pattern in _INJECTION_REGEX:
                    if pattern.search(value):
                        _logger.warning(
                            f"Prompt injection detected in {param_name}: {value[:100]}"
                        )
                        return (
                            False,
                            f"Security violation: Suspicious pattern detected in '{param_name}'. "
                            "Please use specific, factual queries only.",
                        )

                # Check for excessive length (potential attack)
                if len(value) > 5000:
                    return (
                        False,
                        f"Parameter '{param_name}' exceeds maximum length of 5000 characters.",
                    )

    return (True, None)


def validate_search_query(query: str) -> tuple[bool, str | None]:
    """
    Validate search queries to prevent enumeration attacks.

    Returns:
        (is_valid, error_message)
    """
    if not query or not isinstance(query, str):
        return (False, "Search query must be a non-empty string")

    # Minimum query length to prevent enumeration
    if len(query) < 3:
        return (
            False,
            "Search query must be at least 3 characters. "
            "Use specific, meaningful search terms (e.g., 'GDP growth', 'unemployment rate').",
        )

    # Block single character or wildcard queries
    if query.strip() in ["*", "?", "%", "_", ".", ".*"]:
        return (
            False,
            "Wildcard-only queries are not allowed. Please use specific search terms.",
        )

    # Check for prompt injection in query
    for pattern in _INJECTION_REGEX:
        if pattern.search(query):
            _logger.warning(f"Prompt injection detected in search query: {query[:100]}")
            return (
                False,
                "Security violation: Suspicious pattern detected in query. "
                "Please use specific, factual search terms only.",
            )

    return (True, None)


def sanitize_string(value: str, max_length: int = 1000) -> str:
    """
    Sanitize string input by removing potentially dangerous characters.

    Args:
        value: Input string
        max_length: Maximum allowed length

    Returns:
        Sanitized string
    """
    if not isinstance(value, str):
        return str(value)

    # Truncate to max length
    sanitized = value[:max_length]

    # Remove null bytes and other dangerous characters
    sanitized = sanitized.replace("\x00", "")

    # Remove excessive whitespace
    sanitized = " ".join(sanitized.split())

    return sanitized
