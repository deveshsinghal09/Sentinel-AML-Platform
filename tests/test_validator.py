from __future__ import annotations

from agent.validator import ALLOWED_TOOLS, validate_plan


def test_valid_plan_passes_through_unchanged():
    plan = ["data_loader", "rule_engine", "explanation"]
    assert validate_plan(plan) == plan


def test_unknown_tool_is_dropped():
    assert validate_plan(["data_loader", "shell_exec", "explanation"]) == [
        "data_loader",
        "explanation",
    ]


def test_empty_plan_returns_empty_list():
    assert validate_plan([]) == []


def test_all_allowed_tools_pass():
    plan = sorted(ALLOWED_TOOLS)
    assert validate_plan(plan) == plan


def test_duplicate_tools_are_dropped():
    assert validate_plan(["data_loader", "data_loader"]) == ["data_loader"]
