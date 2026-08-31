from __future__ import annotations

import ast

import pytest

from tools import quality_gate


def metric(
    *,
    complexity: int = quality_gate.MAX_COMPLEXITY,
    difficulty: float = quality_gate.MAX_HALSTEAD_DIFFICULTY,
) -> quality_gate.FunctionMetric:
    return quality_gate.FunctionMetric("sample", 1, 1, complexity, difficulty)


def test_physical_line_boundary() -> None:
    assert (
        quality_gate._physical_line_issue(
            "pass.py", "x\n" * quality_gate.MAX_PHYSICAL_LINES
        )
        is None
    )
    issue = quality_gate._physical_line_issue(
        "fail.py", "x\n" * (quality_gate.MAX_PHYSICAL_LINES + 1)
    )
    assert issue is not None
    assert issue.metric == "physical-lines"


def test_static_metric_boundaries() -> None:
    assert quality_gate._static_metric_issues("pass.py", [metric()]) == []
    issues = quality_gate._static_metric_issues(
        "fail.py",
        [
            metric(
                complexity=quality_gate.MAX_COMPLEXITY + 1,
                difficulty=quality_gate.MAX_HALSTEAD_DIFFICULTY + 0.000002,
            )
        ],
    )
    assert [issue.metric for issue in issues] == [
        "cyclomatic-complexity",
        "halstead-difficulty",
    ]


@pytest.mark.parametrize(
    ("annotation", "expected"),
    [
        ("object", []),
        ("dict[str, object]", []),
        ("Any", ["Any"]),
        ("list[Unknown]", ["Unknown"]),
        ("typing.Any", ["Any"]),
    ],
)
def test_dynamic_type_detection(annotation: str, expected: list[str]) -> None:
    tree = ast.parse(f"def value(item: {annotation}) -> None:\n    pass\n")
    assert [
        issue.symbol for issue in quality_gate._forbidden_type_issues("sample.py", tree)
    ] == expected


def test_crap_boundaries() -> None:
    assert quality_gate.crap_score(1, 0.0) == 2.0
    assert quality_gate.crap_score(4, 50.0) == 6.0
    assert (
        quality_gate.crap_score(quality_gate.MAX_COMPLEXITY, 100.0)
        <= quality_gate.MAX_CRAP
    )
