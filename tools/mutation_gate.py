"""Fail unless Mutmut reports that every generated mutant was killed."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

COUNT_KEYS = (
    "killed",
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "timeout",
    "check_was_interrupted_by_user",
    "segfault",
)
REJECTED_KEYS = (
    "survived",
    "no_tests",
    "skipped",
    "suspicious",
    "check_was_interrupted_by_user",
    "segfault",
)


def _read_mutation_counts(document: object) -> Mapping[str, int]:
    if not isinstance(document, dict):
        raise TypeError("mutation summary must be an object")
    if not all(isinstance(key, str) for key in document):
        raise TypeError("mutation summary has a non-string key")
    summary = cast("Mapping[str, object]", document)
    values: dict[str, int] = {}
    for key in ("total", *COUNT_KEYS):
        value = summary.get(key)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise TypeError(f"mutation summary {key} must be a non-negative integer")
        values[key] = value
    return values


def collect_mutation_issues(document: object) -> tuple[str, ...]:
    """Return all failures in a Mutmut CI summary.

    Returns:
        The mutation-gate failures.

    """
    counts = _read_mutation_counts(document)
    total = counts["total"]
    issues = ["no mutants were generated"] if total == 0 else []
    issues.extend(
        f"{key} is {counts[key]}; required 0"
        for key in REJECTED_KEYS
        if counts[key] != 0
    )
    classified = sum(counts[key] for key in COUNT_KEYS)
    if classified != total:
        issues.append(f"classified mutants are {classified}; required total {total}")
    detected = counts["killed"] + counts["timeout"]
    if detected != total:
        issues.append(f"detected mutants are {detected}; required total {total}")
    return tuple(issues)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "summary",
        nargs="?",
        type=Path,
        default=Path("mutants/mutmut-cicd-stats.json"),
        help="Mutmut CI summary JSON",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Check the Mutmut CI summary.

    Returns:
        Zero when all mutants were killed, or one otherwise.

    """
    summary_path = _build_parser().parse_args(argv).summary
    try:
        document = json.loads(summary_path.read_text(encoding="utf-8"))
        issues = collect_mutation_issues(document)
    except (OSError, json.JSONDecodeError, TypeError) as error:
        sys.stdout.write(f"mutation gate failed: {error}\n")
        return 1
    for issue in issues:
        sys.stdout.write(f"mutation gate failed: {issue}\n")
    if issues:
        return 1
    counts = _read_mutation_counts(document)
    sys.stdout.write(f"mutation gate passed: {counts['total']} mutants detected\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
