"""Enforce the repository's numeric Python quality limits."""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from radon.complexity import cc_visit
from radon.metrics import h_visit
from radon.visitors import Class, Function

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

MAX_COMPLEXITY = 21
MAX_HALSTEAD_DIFFICULTY = 79.999999
MAX_PHYSICAL_LINES = 499
MIN_LINE_COVERAGE = 90.0
MIN_BRANCH_COVERAGE = 90.0
MAX_CRAP = 24.999999
PRODUCT_PREFIXES = ("scripts/", "src/")
FORBIDDEN_TYPE_NAMES = frozenset({"Any", "Unknown"})


@dataclass(frozen=True, order=True)
class QualityIssue:
    """One deterministic quality-gate failure."""

    path: str
    line: int
    metric: str
    symbol: str
    actual: str
    limit: str

    def render(self) -> str:
        """Render an issue in compiler-style text.

        Returns:
            The rendered issue.

        """
        return (
            f"{self.path}:{self.line}: {self.metric}: {self.symbol} "
            f"is {self.actual}; required {self.limit}"
        )


@dataclass(frozen=True)
class FunctionMetric:
    """Static metrics for one Python function or method."""

    name: str
    line: int
    coverage_line: int
    complexity: int
    halstead_difficulty: float


def _object_mapping(value: object, label: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be an object")
    if not all(isinstance(key, str) for key in value):
        raise TypeError(f"{label} has a non-string key")
    return cast("Mapping[str, object]", value)


def _number(value: object, label: str) -> float:
    if not isinstance(value, int | float):
        raise TypeError(f"{label} must be numeric")
    return float(value)


def _tracked_python_files(root: Path) -> tuple[Path, ...]:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("git executable is required")
    result = subprocess.run(
        [
            git,
            "ls-files",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.py",
        ],
        cwd=root,
        check=True,
        capture_output=True,
        shell=False,
        text=True,
    )
    return tuple(
        root / line
        for line in sorted(result.stdout.splitlines())
        if line and (root / line).is_file()
    )


def _physical_line_issue(path: str, source: str) -> QualityIssue | None:
    lines = len(source.splitlines())
    if lines <= MAX_PHYSICAL_LINES:
        return None
    return QualityIssue(
        path=path,
        line=1,
        metric="physical-lines",
        symbol=path,
        actual=str(lines),
        limit=f"<= {MAX_PHYSICAL_LINES}",
    )


def _annotation_roots(tree: ast.AST) -> Iterable[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) or (
            isinstance(node, ast.arg) and node.annotation is not None
        ):
            yield node.annotation
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            if node.returns is not None:
                yield node.returns
        elif isinstance(node, ast.TypeAlias):
            yield node.value


def _forbidden_type_issues(path: str, tree: ast.AST) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    seen: set[tuple[int, str]] = set()
    for annotation in _annotation_roots(tree):
        for node in ast.walk(annotation):
            name: str | None = None
            if isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            if name not in FORBIDDEN_TYPE_NAMES:
                continue
            identity = (node.lineno, name)
            if identity in seen:
                continue
            seen.add(identity)
            issues.append(
                QualityIssue(
                    path=path,
                    line=node.lineno,
                    metric="dynamic-type",
                    symbol=name,
                    actual="present",
                    limit="absent",
                )
            )
    return issues


def _function_nodes(tree: ast.AST) -> Iterable[ast.FunctionDef | ast.AsyncFunctionDef]:
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            yield node


def _radon_functions(source: str) -> dict[tuple[int, str], Function]:
    functions: dict[tuple[int, str], Function] = {}

    def collect(function: Function) -> None:
        functions[function.lineno, function.name] = function
        for closure in function.closures:
            collect(closure)

    def collect_class(class_block: Class) -> None:
        for method in class_block.methods:
            collect(method)
        for nested_class in class_block.inner_classes:
            collect_class(nested_class)

    for block in cc_visit(source):
        if isinstance(block, Function):
            collect(block)
        elif isinstance(block, Class):
            collect_class(block)
    return functions


def _halstead_difficulty(source: str, node: ast.AST) -> float:
    segment = ast.get_source_segment(source, node)
    if segment is None:
        return 0.0
    report = h_visit(textwrap.dedent(segment))
    if not report.functions:
        return 0.0
    return float(report.functions[0][1].difficulty)


def _function_metrics(source: str, tree: ast.AST) -> tuple[FunctionMetric, ...]:
    radon_functions = _radon_functions(source)
    metrics: list[FunctionMetric] = []
    for node in _function_nodes(tree):
        block = radon_functions.get((node.lineno, node.name))
        if block is None:
            continue
        coverage_line = min(
            (decorator.lineno for decorator in node.decorator_list),
            default=node.lineno,
        )
        metrics.append(
            FunctionMetric(
                name=block.fullname,
                line=node.lineno,
                coverage_line=coverage_line,
                complexity=block.complexity,
                halstead_difficulty=_halstead_difficulty(source, node),
            )
        )
    return tuple(metrics)


def _static_metric_issues(
    path: str,
    metrics: Sequence[FunctionMetric],
) -> list[QualityIssue]:
    issues: list[QualityIssue] = []
    for metric in metrics:
        if metric.complexity > MAX_COMPLEXITY:
            issues.append(
                QualityIssue(
                    path,
                    metric.line,
                    "cyclomatic-complexity",
                    metric.name,
                    str(metric.complexity),
                    f"<= {MAX_COMPLEXITY}",
                )
            )
        if metric.halstead_difficulty > MAX_HALSTEAD_DIFFICULTY:
            issues.append(
                QualityIssue(
                    path,
                    metric.line,
                    "halstead-difficulty",
                    metric.name,
                    f"{metric.halstead_difficulty:.2f}",
                    "< 80",
                )
            )
    return issues


def _coverage_function_map(
    file_coverage: Mapping[str, object],
) -> dict[int, Mapping[str, object]]:
    functions = _object_mapping(file_coverage.get("functions"), "coverage functions")
    by_line: dict[int, Mapping[str, object]] = {}
    for value in functions.values():
        region = _object_mapping(value, "coverage function")
        start_line = region.get("start_line")
        if isinstance(start_line, int):
            by_line[start_line] = region
    return by_line


def crap_score(complexity: int, line_coverage: float) -> float:
    """Calculate the Change Risk Anti-Patterns score.

    Returns:
        The CRAP score.

    """
    uncovered = 1.0 - (line_coverage / 100.0)
    return complexity**2 * uncovered**3 + complexity


def _crap_issues(
    path: str,
    metrics: Sequence[FunctionMetric],
    file_coverage: Mapping[str, object],
) -> list[QualityIssue]:
    regions = _coverage_function_map(file_coverage)
    issues: list[QualityIssue] = []
    for metric in metrics:
        region = regions.get(metric.coverage_line)
        line_coverage = 0.0
        if region is not None:
            summary = _object_mapping(region.get("summary"), "function summary")
            line_coverage = _number(
                summary.get("percent_statements_covered"),
                "function line coverage",
            )
        score = crap_score(metric.complexity, line_coverage)
        if score <= MAX_CRAP:
            continue
        issues.append(
            QualityIssue(
                path,
                metric.line,
                "crap",
                metric.name,
                f"{score:.2f}",
                "< 25",
            )
        )
    return issues


def _total_coverage_issues(coverage: Mapping[str, object]) -> list[QualityIssue]:
    totals = _object_mapping(coverage.get("totals"), "coverage totals")
    measurements = (
        (
            "line-coverage",
            _number(totals.get("percent_statements_covered"), "line coverage"),
            MIN_LINE_COVERAGE,
        ),
        (
            "branch-coverage",
            _number(totals.get("percent_branches_covered"), "branch coverage"),
            MIN_BRANCH_COVERAGE,
        ),
    )
    return [
        QualityIssue(
            "coverage.json",
            1,
            name,
            "repository",
            f"{actual:.2f}%",
            f">= {minimum:.2f}%",
        )
        for name, actual, minimum in measurements
        if actual < minimum
    ]


def _load_coverage(path: Path) -> Mapping[str, object]:
    return _object_mapping(json.loads(path.read_text(encoding="utf-8")), "coverage")


def check_repository(root: Path, coverage_path: Path) -> tuple[QualityIssue, ...]:
    """Return every quality-gate issue in deterministic order.

    Returns:
        The sorted quality issues.

    """
    coverage = _load_coverage(coverage_path)
    coverage_files = _object_mapping(coverage.get("files"), "coverage files")
    issues = _total_coverage_issues(coverage)
    for file_path in _tracked_python_files(root):
        relative = file_path.relative_to(root).as_posix()
        source = file_path.read_text(encoding="utf-8")
        line_issue = _physical_line_issue(relative, source)
        if line_issue is not None:
            issues.append(line_issue)
        tree = ast.parse(source, filename=relative)
        issues.extend(_forbidden_type_issues(relative, tree))
        metrics = _function_metrics(source, tree)
        issues.extend(_static_metric_issues(relative, metrics))
        if relative.startswith(PRODUCT_PREFIXES):
            file_coverage = coverage_files.get(relative)
            if file_coverage is None:
                file_coverage = {"functions": {}}
            issues.extend(
                _crap_issues(
                    relative,
                    metrics,
                    _object_mapping(file_coverage, f"coverage for {relative}"),
                )
            )
    return tuple(sorted(issues))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--coverage",
        type=Path,
        default=Path("coverage.json"),
        help="Coverage.py JSON report",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the repository quality gate.

    Returns:
        Zero on success and one when an issue exists.

    """
    args = _parser().parse_args(argv)
    root = Path.cwd()
    issues = check_repository(root, args.coverage)
    for issue in issues:
        sys.stdout.write(f"{issue.render()}\n")
    if issues:
        sys.stdout.write(f"quality gate failed with {len(issues)} issue(s)\n")
        return 1
    sys.stdout.write("quality gate passed\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
