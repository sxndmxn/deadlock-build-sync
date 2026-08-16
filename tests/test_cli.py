from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import deadlock_build_sync.cli as cli_module
import deadlock_build_sync.offline.cli as offline_cli_module
from deadlock_build_sync.api import Patch
from deadlock_build_sync.cache import CacheError, CacheLocation
from deadlock_build_sync.cli import DEFAULT_NARRATIVE_PATH, build_parser
from deadlock_build_sync.freshness import FreshnessError
from deadlock_build_sync.narratives import (
    DEFAULT_KIT_MODEL,
    DEFAULT_SYNTHESIS_MODEL,
    NarrativeCatalog,
)
from deadlock_build_sync.purchase_guide import PurchaseGuide
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE, RankCatalog
from deadlock_build_sync.service import GeneratedGuides
from deadlock_build_sync.snapshot import (
    EpochBoundary,
    EpochSet,
    EvidenceRecord,
    EvidenceUnit,
    MatchMode,
    OutcomePolicy,
    SnapshotManifest,
)
from scripts.generate_narratives import DEFAULT_GENERATION_CONCURRENCY


def test_sync_defaults_to_every_eligible_hero_and_staged_models() -> None:
    args = build_parser().parse_args(["sync"])

    assert args.hero is None
    assert not args.all
    assert args.kit_model == DEFAULT_KIT_MODEL
    assert args.model == DEFAULT_SYNTHESIS_MODEL
    assert args.max_attempts == 3
    assert args.concurrency == DEFAULT_GENERATION_CONCURRENCY


def test_status_is_read_only_and_supports_json() -> None:
    args = build_parser().parse_args(["status", "--json"])

    assert args.command == "status"
    assert args.json


def test_refresh_evidence_handoff_exports_and_admits_one_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    forwarded: list[str] = []
    loaded: list[Path] = []

    def refresh(arguments: list[str]) -> int:
        forwarded.extend(arguments)
        return 0

    def load(path: Path) -> SimpleNamespace:
        loaded.append(path)
        return SimpleNamespace(artifact_id="a" * 64)

    monkeypatch.setattr(offline_cli_module, "main", refresh)
    monkeypatch.setattr(cli_module, "load_build_evidence", load)
    args = build_parser().parse_args([
        "refresh-evidence",
        "--artifacts",
        str(tmp_path),
        "--run-id",
        "frozen",
    ])

    assert cli_module._run_refresh_evidence(args) == 0
    assert forwarded[0] == "all"
    assert forwarded[forwarded.index("--output") + 1] == str(
        tmp_path / "build-evidence.json"
    )
    assert "--run-id" in forwarded
    assert loaded == [tmp_path / "build-evidence.json"]


def test_recommend_parser_requires_a_decision_state() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["recommend"])

    args = build_parser().parse_args(["recommend", "--state", "state.json"])
    assert args.state == Path("state.json")


def test_stale_sync_stops_before_cache_discovery(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        cli_module,
        "require_current_build_evidence",
        lambda *_args: (_ for _ in ()).throw(
            FreshnessError("STALE — regeneration required")
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "_location",
        lambda _args: calls.append("cache"),
    )
    args = build_parser().parse_args([
        "sync",
        "--artifacts",
        str(tmp_path),
    ])

    with pytest.raises(FreshnessError, match="STALE"):
        cli_module._run_sync(args)
    assert calls == []
    assert args.match_mode == MatchMode.RANKED
    assert args.client_version is None


def test_install_artifacts_defaults_to_the_state_artifact_directory() -> None:
    args = build_parser().parse_args(["install-artifacts"])

    assert args.artifacts is None
    assert args.persona is None


def test_install_artifacts_refuses_before_loading_when_deadlock_is_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = CacheLocation(123, tmp_path / "cached_hero_builds.kv3", tmp_path)
    monkeypatch.setattr(cli_module, "_location", lambda _args: location)
    monkeypatch.setattr(cli_module, "deadlock_is_running", lambda: True)
    monkeypatch.setattr(
        cli_module,
        "load_artifact_guide_bundle",
        lambda *_args: pytest.fail("bundle must not load while Deadlock is running"),
    )

    with pytest.raises(CacheError, match="Deadlock is running"):
        cli_module._run_install_artifacts(
            build_parser().parse_args(["install-artifacts"])
        )


def test_install_artifacts_loads_frozen_build_evidence_from_the_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact_directory = tmp_path / "artifacts"
    cache_path = tmp_path / "cached_hero_builds.kv3"
    location = CacheLocation(123, cache_path, tmp_path)
    patch = Patch("Patch", 123, "2026-01-01T00:00:00Z")
    seen: dict[str, object] = {}
    monkeypatch.setattr(cli_module, "_location", lambda _args: location)
    monkeypatch.setattr(cli_module, "deadlock_is_running", lambda: False)
    monkeypatch.setattr(cli_module, "local_steam_persona", lambda _account_id: "XMLJDX")

    def load_bundle(*paths: Path) -> SimpleNamespace:
        seen["paths"] = paths
        return SimpleNamespace(
            guides=[],
            exclusions=(),
            patch=patch,
            rank_range=DEFAULT_RANK_RANGE,
            snapshot_manifest={
                "snapshot_id": "s" * 64,
                "match_mode": "ranked",
                "client_version": 123,
                "as_of_timestamp": 999,
            },
            expected_hero_ids=frozenset(),
        )

    monkeypatch.setattr(cli_module, "load_artifact_guide_bundle", load_bundle)

    def install_guides(*_args: object, **kwargs: object) -> SimpleNamespace:
        seen["persona"] = kwargs["persona"]
        return SimpleNamespace(
            build_ids={},
            created=0,
            updated=0,
            cache_path=cache_path,
            backup_directory=tmp_path / "backup",
            snapshot_id="s" * 64,
            policy_ids={},
        )

    monkeypatch.setattr(cli_module, "install_guides", install_guides)

    assert (
        cli_module._run_install_artifacts(
            build_parser().parse_args([
                "install-artifacts",
                "--artifacts",
                str(artifact_directory),
            ])
        )
        == 0
    )
    assert seen["paths"] == (
        artifact_directory / "strategy-context.json",
        artifact_directory / "policies.json",
        artifact_directory / "narratives.json",
        artifact_directory / "build-evidence.json",
    )
    assert seen["persona"] == "XMLJDX"


def snapshot() -> SnapshotManifest:
    boundary = EpochBoundary("patch", 123)
    return SnapshotManifest(
        client_version=123,
        as_of_timestamp=999,
        created_at=datetime.now(UTC).isoformat(),
        match_mode=MatchMode.RANKED,
        game_mode="normal",
        rank_range=DEFAULT_RANK_RANGE.as_dict(),
        rank_labels_sha256="ranks",
        build_tags_sha256="b" * 64,
        patch={"identity": "patch"},
        epochs=EpochSet(boundary, boundary, boundary, boundary),
        outcome_policy=OutcomePolicy(),
        outcome_policy_enforced=False,
        records=(
            EvidenceRecord(
                "fixture",
                {},
                datetime.now(UTC).isoformat(),
                "0" * 64,
                1,
                EvidenceUnit.ASSET,
                "fixture",
                "none",
            ),
        ),
    )


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
        policies=[],
        contexts=[context],
        item_mechanics={},
        skipped_heroes=(),
        exclusions=(),
        eligible_hero_ids=frozenset({12}),
        subset_selected=False,
        rank_range=DEFAULT_RANK_RANGE,
        rank_catalog=RankCatalog({tier: f"Tier {tier}" for tier in range(1, 12)}),
        persona="Player",
        patch=Patch("Patch", 123, "2026-01-01T00:00:00Z"),
        manifest=snapshot(),
    )
    calls: dict[str, Any] = {}

    monkeypatch.setattr(cli_module, "_location", lambda _args: location)
    monkeypatch.setattr(cli_module, "deadlock_is_running", lambda: False)
    monkeypatch.setattr(
        cli_module,
        "require_current_build_evidence",
        lambda *_args: SimpleNamespace(artifact_id="e" * 64),
    )
    monkeypatch.setattr(cli_module, "_api", lambda *_args: object())

    def fake_generate(*_args: object, **kwargs: object) -> GeneratedGuides:
        calls["all_heroes"] = kwargs["all_heroes"]
        return generated

    monkeypatch.setattr(cli_module, "generate_guides", fake_generate)

    def fake_write_context(path: Path, _generated: GeneratedGuides) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(cli_module, "_write_strategy_context", fake_write_context)

    def fake_write_policies(path: Path, _generated: GeneratedGuides) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(cli_module, "_write_policy_artifact", fake_write_policies)

    def fake_narratives(argv: list[str] | None = None) -> int:
        calls["generation_args"] = argv
        return 0

    monkeypatch.setattr(cli_module, "generate_narratives_main", fake_narratives)
    monkeypatch.setattr(
        cli_module,
        "load_narrative_catalog",
        lambda _path: NarrativeCatalog(
            snapshot_id=generated.manifest.snapshot_id,
            patch_identity=generated.patch.identity,
            client_version=123,
            match_mode="ranked",
            game_mode="normal",
            source_context_sha256="0" * 64,
            requested_hero_ids=frozenset({12}),
            exclusions={},
            heroes={},
        ),
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
            snapshot_id=generated.manifest.snapshot_id,
            policy_ids={12: "policy"},
        ),
    )

    args = build_parser().parse_args([
        "sync",
        "--artifacts",
        str(tmp_path / "artifacts"),
    ])
    assert cli_module._run_sync(args) == 0
    assert calls["all_heroes"] is True
    assert (tmp_path / "artifacts/strategy-context.json").is_file()
    assert (tmp_path / "artifacts/policies.json").is_file()
    generation_args = calls["generation_args"]
    assert isinstance(generation_args, list)
    assert "--kit-model" in generation_args
    assert DEFAULT_KIT_MODEL in generation_args
    assert "--model" in generation_args
    assert DEFAULT_SYNTHESIS_MODEL in generation_args
    assert "--concurrency" in generation_args
    assert str(DEFAULT_GENERATION_CONCURRENCY) in generation_args


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
