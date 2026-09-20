"""Allow-list validation for tool names proposed by the planner."""
from __future__ import annotations

from loguru import logger


ALLOWED_TOOLS = {
    "data_loader",
    "aggregation",
    "eda",
    "feature_engineering",
    "rule_engine",
    "statistical",
    "ml_engine",
    "graph_tool",
    "risk_scorer",
    "escalation",
    "explanation",
}


def validate_plan(tool_list: list[str]) -> list[str]:
    """Return allowed tool names, dropping duplicates and unknown names."""
    clean: list[str] = []
    for tool in tool_list:
        if tool not in ALLOWED_TOOLS:
            logger.warning(
                "[validator] Dropping unknown tool '{}' from plan",
                tool,
            )
        elif tool not in clean:
            clean.append(tool)
    return clean
