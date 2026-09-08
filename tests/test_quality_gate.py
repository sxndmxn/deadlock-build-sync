from __future__ import annotations

import ast
import tomllib
from pathlib import Path

import pytest

from tools import quality_gate

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def metric(
    *,
    complexity: int = quality_gate.MAX_COMPLEXITY,
    difficulty: float = quality_gate.MAX_HALSTEAD_DIFFICULTY,
) -> quality_gate.FunctionMetric:
    return quality_gate.FunctionMetric("sample", 1, 1, complexity, difficulty)


def test_physical_line_boundary() -> None:
    assert (
        quality_gate._check_physical_line_limit(
            "pass.py", "x\n" * quality_gate.MAX_PHYSICAL_LINES
        )
        is None
    )
    issue = quality_gate._check_physical_line_limit(
        "fail.py", "x\n" * (quality_gate.MAX_PHYSICAL_LINES + 1)
    )
    assert issue is not None
    assert issue.metric == "physical-lines"


def test_static_metric_boundaries() -> None:
    assert quality_gate._check_static_metric_limits("pass.py", [metric()]) == []
    issues = quality_gate._check_static_metric_limits(
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


def test_decorated_function_uses_definition_line_for_coverage() -> None:
    source = "@staticmethod\ndef sample(value: int) -> bool:\n    return value > 0\n"

    metrics = quality_gate._calculate_function_metrics(source, ast.parse(source))

    assert len(metrics) == 1
    assert metrics[0].coverage_line == 2


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
        issue.symbol
        for issue in quality_gate._find_forbidden_type_annotations("sample.py", tree)
    ] == expected


def test_crap_boundaries() -> None:
    assert quality_gate.crap_score(1, 0.0) == 2.0
    assert quality_gate.crap_score(4, 50.0) == 6.0
    assert (
        quality_gate.crap_score(quality_gate.MAX_COMPLEXITY, 100.0)
        <= quality_gate.MAX_CRAP
    )


def test_static_analysis_paths_contain_python_files() -> None:
    configuration = tomllib.loads((PROJECT_ROOT / "pyproject.toml").read_text())
    tools = configuration["tool"]
    configured_paths = {
        *tools["complexipy"]["paths"],
        *tools["vulture"]["paths"],
        *tools["ty"]["src"]["include"],
    }

    for relative_path in configured_paths:
        assert next((PROJECT_ROOT / relative_path).rglob("*.py"), None), relative_path
