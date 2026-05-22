"""Relevance gate and knowledge-to-data reformulation for the Data360 MCP agent."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel

DEFAULT_REFUSAL_TEXT = (
    "That question is outside Data360’s scope. I focus on World Bank–style "
    "development data, indicators, and country evidence you can retrieve with this assistant."
)

# Keep in sync with MCP ``prompts/get`` → ``gate_classifier`` / ``thematic_to_data``
# (``src/data360/mcp_server/prompts.py``: GATE_CLASSIFIER_PROMPT, THEMATIC_REFORM_SYSTEM).
GATE_SYSTEM_PROMPT = """You are a classifier for a Data360 / World Bank data assistant.

Decide if the user’s latest message should engage the Data360 MCP tool-using agent.

**In scope (relevant = true)** — include ALL of:
1. Direct data questions: indicators, countries/economies, years, comparisons, charts.
2. Development economics and World Bank–aligned operations questions where World Bank / Data360-style **data** can illuminate the answer — macro, fiscal/public spending, poverty, inequality, labor markets, human capital, trade, investment climate, climate-related **development** metrics, etc. — even if the user did not name an indicator code.
3. Country or regional **policy-relevant themes** that can be grounded in measurable series or country metadata (e.g. “main challenges facing Ghana’s growth and public spending”, “structural labor market challenges in Morocco”, “climate change and economic development in Bangladesh”).

**Out of scope (relevant = false)**:
- Pure chit-chat, unrelated trivia, entertainment.
- Homework or tasks with no plausible path through WB-style data.
- Medical, legal, or personal advice.
- Questions with no link to development data (e.g. street-level weather, sports scores, generic coding help unrelated to this data assistant).

**Bias**: When the topic is clearly development- or WB-adjacent and data could support an evidence-based answer, choose **relevant = true**.

When relevant is false, set refusal_text to one short, polite sentence explaining the assistant focuses on WB/Data360 data (optional; a default may be used). When relevant is true, leave refusal_text null or empty."""

REFORM_SYSTEM_PROMPT = """You rewrite user questions into **one** concrete orchestration prompt for a Data360 MCP agent that will search indicators, fetch series, and build charts.

Given the user’s message (often thematic or knowledge-style), output:
- data_question: A single clear instruction naming **economy/ies** (ISO codes or standard country names), **indicator themes or concrete search terms**, a **reasonable year range**, and **peer or benchmark** comparisons when useful (e.g. regional peers, world, income group).
- search_hints: Short bullet-style strings the agent can use when searching tools (e.g. “GDP growth annual”, “general government final consumption”, “labor force participation”, “youth unemployment”, “ND-GAIN” or other WB-relevant climate vulnerability metrics if applicable).
- rewritten: true if you materially rewrote/expanded the user request; false if the user request is already an explicit, well-formed data question and should be preserved as-is.

Rules:
- Do not broaden scope for explicit data asks. Example: "Latest GDP growth in Vietnam." should remain focused on Vietnam latest GDP growth.
- Rewrite when the immediate question is thematic, underspecified, or depends on prior context.
- Do not answer the question yourself; only produce the reformulated task. Stay within evidence the World Bank / Data360 tools could retrieve."""


class Data360GateResult(BaseModel):
    """Structured output for the relevance gate."""

    relevant: bool = Field(description="True if the Data360 MCP agent should run.")
    confidence: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Classifier confidence between 0 and 1.",
    )
    reason: str = Field(
        default="",
        description="Brief rationale for the classification (internal quality).",
    )
    refusal_text: str | None = Field(
        default=None,
        description="Short user-facing refusal when relevant is false; optional.",
    )


class Data360ReformulationResult(BaseModel):
    """Structured output for knowledge → data task reformulation."""

    data_question: str = Field(
        description="Single orchestration prompt for the MCP agent (countries, themes, years, comparisons).",
    )
    search_hints: list[str] = Field(
        default_factory=list,
        description="Optional hints for indicator/search tool calls.",
    )
    rewritten: bool = Field(
        default=True,
        description="True if data_question is a rewritten/expanded version of the prompt.",
    )


def _human_message_text(msg: HumanMessage) -> str:
    content = msg.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        chunks: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                chunks.append(str(block.get("text", "")))
            else:
                chunks.append(str(block))
        return "".join(chunks).strip()
    return str(content).strip()


def last_user_text(messages: list[BaseMessage]) -> str | None:
    """Return the latest human message text, or None."""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            text = _human_message_text(msg)
            return text or None
    return None


def build_augmented_messages(
    messages: list[BaseMessage],
    reformulation: Data360ReformulationResult,
) -> list[BaseMessage]:
    """Append orchestration focus to the last HumanMessage; copy list."""
    out = list(messages)
    for i in range(len(out) - 1, -1, -1):
        cur = out[i]
        if isinstance(cur, HumanMessage):
            original = _human_message_text(cur)
            hints_lines = "\n".join(
                f"- {h}" for h in (reformulation.search_hints or []) if h.strip()
            )
            augmented = (
                f"{original}\n\n---\n"
                "Orchestration focus (use Data360 MCP tools for evidence and charts):\n"
                f"{reformulation.data_question.strip()}\n"
            )
            if hints_lines:
                augmented += f"\nSearch / indicator hints:\n{hints_lines}\n"
            out[i] = HumanMessage(content=augmented)
            break
    return out


async def classify_data360_relevance(
    llm: BaseChatModel,
    user_text: str,
    *,
    gate_system_prompt: str | None = None,
) -> Data360GateResult:
    """Single structured LLM call: should the Data360 agent run?

    When ``gate_system_prompt`` is set (e.g. from MCP ``prompts/get`` →
    ``gate_classifier``), it replaces the embedded :data:`GATE_SYSTEM_PROMPT`.
    """
    structured = llm.with_structured_output(Data360GateResult)
    system = (
        gate_system_prompt.strip()
        if gate_system_prompt and gate_system_prompt.strip()
        else GATE_SYSTEM_PROMPT
    )
    prompt = [
        SystemMessage(content=system),
        HumanMessage(content=user_text),
    ]
    result = await structured.ainvoke(prompt)
    if not isinstance(result, Data360GateResult):
        msg = "Gate structured output returned unexpected type"
        raise TypeError(msg)
    return result


async def reformulate_for_data360(
    llm: BaseChatModel,
    user_text: str,
    *,
    prompt_messages: Sequence[BaseMessage] | None = None,
) -> Data360ReformulationResult:
    """Single structured LLM call: thematic → concrete data task.

    When ``prompt_messages`` is set (e.g. from MCP ``prompts/get`` →
    ``thematic_to_data``), it replaces the default system + user pair; ``user_text``
    is ignored for that invocation (the MCP template usually embeds the user turn).
    """
    structured = llm.with_structured_output(Data360ReformulationResult)
    if prompt_messages is not None:
        prompt = list(prompt_messages)
    else:
        prompt = [
            SystemMessage(content=REFORM_SYSTEM_PROMPT),
            HumanMessage(content=user_text),
        ]
    result = await structured.ainvoke(prompt)
    if not isinstance(result, Data360ReformulationResult):
        msg = "Reformulation structured output returned unexpected type"
        raise TypeError(msg)
    return result


__all__ = [
    "DEFAULT_REFUSAL_TEXT",
    "Data360GateResult",
    "Data360ReformulationResult",
    "build_augmented_messages",
    "classify_data360_relevance",
    "last_user_text",
    "reformulate_for_data360",
]
