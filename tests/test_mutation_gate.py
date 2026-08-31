from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from tools.mutation_gate import COUNT_KEYS, main, mutation_issues

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.capture import CaptureFixture


def _summary(**changes: int) -> dict[str, object]:
    summary: dict[str, object] = dict.fromkeys(("total", *COUNT_KEYS), 0)
    summary.update({"total": 3, "killed": 3})
    summary.update(changes)
    return summary


def test_mutation_gate_accepts_only_a_complete_kill() -> None:
    assert mutation_issues(_summary()) == ()

    issues = mutation_issues(_summary(killed=1, survived=1, no_tests=1))

    assert issues == (
        "survived is 1; required 0",
        "no_tests is 1; required 0",
        "detected mutants are 1; required total 3",
    )


def test_mutation_gate_rejects_empty_unclassified_and_bad_counts() -> None:
    assert mutation_issues(_summary(total=0, killed=0)) == (
        "no mutants were generated",
    )
    assert mutation_issues(_summary(killed=2)) == (
        "classified mutants are 2; required total 3",
        "detected mutants are 2; required total 3",
    )
    assert mutation_issues(_summary(killed=2, timeout=1)) == ()

    for value in (True, -1, "1"):
        summary = _summary()
        summary["total"] = value
        with pytest.raises(TypeError, match="non-negative integer"):
            mutation_issues(summary)


def test_mutation_gate_cli_reads_summary_and_reports_errors(
    tmp_path: Path,
    capsys: CaptureFixture[str],
) -> None:
    summary_path = tmp_path / "summary.json"
    summary_path.write_text(json.dumps(_summary()), encoding="utf-8")

    assert main([str(summary_path)]) == 0
    assert "3 mutants detected" in capsys.readouterr().out

    summary_path.write_text("[]", encoding="utf-8")
    assert main([str(summary_path)]) == 1
    assert "must be an object" in capsys.readouterr().out
