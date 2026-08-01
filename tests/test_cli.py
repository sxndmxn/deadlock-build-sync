from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import deadlock_build_sync.cli as cli_module
from deadlock_build_sync.api import Patch
from deadlock_build_sync.cache import CacheLocation
from deadlock_build_sync.cli import DEFAULT_NARRATIVE_PATH, build_parser
from deadlock_build_sync.narratives import (
    DEFAULT_KIT_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    NarrativeCatalog,
)
from deadlock_build_sync.purchase_guide import PurchaseGuide
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE
from deadlock_build_sync.service import GeneratedGuides


def test_sync_defaults_to_every_eligible_hero_and_staged_models() -> None:
    args = build_parser().parse_args(["sync"])

    assert args.hero is None
    assert not args.all
    assert args.kit_model == DEFAULT_KIT_MODEL
    assert args.model == DEFAULT_SYNTHESIS_MODEL
    assert args.max_attempts == 3


def test_sync_generates_artifacts_and_installs_without_extra_flags(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "cached_hero_builds.kv3"
    location = CacheLocation(123, cache_path, tmp_path)
    guide = PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: (), 2: (), 3: (), 4: ()},
    )
    context = {
        "hero_id": 12,
        "hero": "Kelvin",
        "kit_basis_sha256": "a" * 64,
        "narrative_basis_sha256": "b" * 64,
        "context_sha256": "c" * 64,
    }
    generated = GeneratedGuides(
        guides=[guide],
        contexts=[context],
        skipped_heroes=(),
        rank_range=DEFAULT_RANK_RANGE,
        persona="Player",
        patch=Patch("Patch", 123, "2026-01-01T00:00:00Z"),
    )
    calls: dict[str, Any] = {}

    monkeypatch.setattr(cli_module, "_location", lambda _args: location)
    monkeypatch.setattr(cli_module, "deadlock_is_running", lambda: False)

    def fake_generate(*_args: object, **kwargs: object) -> GeneratedGuides:
        calls["all_heroes"] = kwargs["all_heroes"]
        return generated

    monkeypatch.setattr(cli_module, "generate_guides", fake_generate)

    def fake_narratives(argv: list[str] | None = None) -> int:
        calls["generation_args"] = argv
        return 0

    monkeypatch.setattr(cli_module, "generate_narratives_main", fake_narratives)
    monkeypatch.setattr(
        cli_module,
        "load_narrative_catalog",
        lambda _path: NarrativeCatalog("2026-01-01T00:00:00Z", {}),
    )
    monkeypatch.setattr(
        cli_module,
        "apply_narrative",
        lambda live_guide, *_args: live_guide,
    )
    monkeypatch.setattr(
        cli_module,
        "install_guides",
        lambda *_args, **_kwargs: SimpleNamespace(
            build_ids={12: 2},
            created=1,
            updated=0,
            cache_path=cache_path,
            backup_directory=tmp_path / "backup",
        ),
    )

    args = build_parser().parse_args([
        "sync",
        "--artifacts",
        str(tmp_path / "artifacts"),
    ])
    assert cli_module._run_sync(args) == 0  # ruff: ignore[private-member-access]
    assert calls["all_heroes"] is True
    assert (tmp_path / "artifacts/strategy-context.json").is_file()
    generation_args = calls["generation_args"]
    assert isinstance(generation_args, list)
    assert "--kit-model" in generation_args
    assert DEFAULT_KIT_MODEL in generation_args
    assert "--model" in generation_args
    assert DEFAULT_SYNTHESIS_MODEL in generation_args


@pytest.mark.parametrize("command", ["preview", "install"])
def test_guide_commands_default_to_reviewed_narratives(command: str) -> None:
    args = build_parser().parse_args([command, "--all"])

    assert args.narratives == DEFAULT_NARRATIVE_PATH


@pytest.mark.parametrize("command", ["preview", "install"])
def test_guide_commands_allow_explicit_analytics_only_output(command: str) -> None:
    args = build_parser().parse_args([command, "--all", "--without-narratives"])

    assert args.narratives is None


def test_guide_commands_accept_an_alternate_narrative_artifact() -> None:
    args = build_parser().parse_args([
        "install",
        "--all",
        "--narratives",
        "reviewed/narratives.json",
    ])

    assert args.narratives == Path("reviewed/narratives.json")
