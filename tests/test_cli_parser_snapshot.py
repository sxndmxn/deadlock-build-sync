from __future__ import annotations

from argparse import ArgumentTypeError
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync import cli_parser
from deadlock_build_sync.cli_parser import build_parser, positive_int
from deadlock_build_sync.offline.cli import build_parser as build_offline_parser
from deadlock_build_sync.snapshot import EpochBoundary, sha256_json
from deadlock_build_sync.tracing import TRACE_ENVIRONMENT_VARIABLE

if TYPE_CHECKING:
    from argparse import Namespace


def _namespace_values(namespace: Namespace) -> dict[str, str]:
    return {key: repr(value) for key, value in sorted(vars(namespace).items())}


def test_parser_numeric_and_epoch_values_are_strict() -> None:
    assert positive_int("7") == 7
    assert cli_parser._epoch_boundary(" mechanics @123") == EpochBoundary(
        "mechanics", 123
    )
    for value in ("0", "-1"):
        with pytest.raises(ArgumentTypeError, match="at least 1"):
            positive_int(value)
    for value in ("mechanics", "@123", "mechanics@bad"):
        with pytest.raises(ArgumentTypeError, match="IDENTITY@UNIX_TIMESTAMP"):
            cli_parser._epoch_boundary(value)


def test_public_parser_help_is_stable(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(TRACE_ENVIRONMENT_VARIABLE, raising=False)
    commands = (
        "build",
        "sync",
        "status",
        "refresh-evidence",
        "recommend",
        "preview",
        "install",
        "install-artifacts",
        "export-context",
        "restore",
        "trace-summary",
    )
    help_text: dict[str, str] = {}
    for command in (None, *commands):
        arguments = ["--help"] if command is None else [command, "--help"]
        with pytest.raises(SystemExit) as caught:
            build_parser().parse_args(arguments)
        assert caught.value.code == 0
        help_text[command or "root"] = capsys.readouterr().out

    assert sha256_json(help_text) == (
        "87772c5702fcfe0628042dc9aa92f1abcf12338c06737ae325c48f71b97f898d"
    )


def test_public_parser_defaults_are_stable(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(TRACE_ENVIRONMENT_VARIABLE, raising=False)
    requests = (
        ["build"],
        ["sync"],
        ["status"],
        ["refresh-evidence"],
        ["recommend", "--state", "state.json"],
        ["preview", "--all"],
        ["install", "--all"],
        ["install-artifacts"],
        ["export-context", "--all", "--output", "context.json"],
        ["restore", "--latest"],
        ["trace-summary", "trace"],
    )
    values = [
        _namespace_values(build_parser().parse_args(request)) for request in requests
    ]

    assert sha256_json(values) == (
        "862ee96bf144a3f0208d1023b3b5db6fe3446ceebc1144389102d72440c77b9d"
    )


def test_offline_parser_help_and_defaults_are_stable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as caught:
        build_offline_parser().parse_args(["--help"])
    assert caught.value.code == 0
    help_text = capsys.readouterr().out
    commands = (
        "extract",
        "audit",
        "analyze",
        "report",
        "layout",
        "export-evidence",
        "all",
    )
    values = [
        _namespace_values(build_offline_parser().parse_args([command]))
        for command in commands
    ]

    assert sha256_json({"help": help_text, "values": values}) == (
        "bdab46ea086aab6c175bf8e7e1eb1ee869a5d7fcaf4a2254293bd99c1c4e715d"
    )
