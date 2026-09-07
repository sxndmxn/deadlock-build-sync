from __future__ import annotations

from argparse import Namespace
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from deadlock_build_sync import cli_export, cli_install, cli_support
from deadlock_build_sync.cache import CacheError
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE
from deadlock_build_sync.snapshot import EpochBoundary, EpochSet, MatchMode

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.build_evidence import BuildEvidenceCatalog
    from deadlock_build_sync.purchase_guide import PurchaseGuide
    from deadlock_build_sync.service import GeneratedGuides


def test_run_install_prints_the_complete_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    location = SimpleNamespace(account_id=7)
    evidence_path = tmp_path / "build-evidence.json"
    evidence = SimpleNamespace(artifact_id="artifact")
    catalog = object()
    generated = SimpleNamespace(
        guides=["first", "second"],
        manifest=SimpleNamespace(
            match_mode=MatchMode.RANKED,
            client_version=123,
            as_of_timestamp=456,
        ),
    )
    result = SimpleNamespace(
        build_ids={(12, "default"): 1, (13, "default"): 2},
        created=1,
        updated=1,
        removed=1,
        cache_path=tmp_path / "cache.kv3",
        backup_directory=tmp_path / "backup",
        snapshot_id="snapshot",
        policy_ids={(13, "default"): "policy-b", (12, "default"): "policy-a"},
    )
    monkeypatch.setattr(cli_install, "_location", lambda _args: location)
    monkeypatch.setattr(cli_install, "deadlock_is_running", lambda: False)
    monkeypatch.setattr(
        cli_install, "_build_evidence", lambda _args: (evidence_path, evidence)
    )
    monkeypatch.setattr(cli_install, "_catalog", lambda _args: catalog)

    def generate(*values: object, **options: object) -> object:
        assert values == (args, evidence, 7)
        assert options == {"narrative_catalog": catalog}
        return generated

    monkeypatch.setattr(cli_install, "_generate", generate)
    monkeypatch.setattr(
        cli_install,
        "_install_generated_guides",
        lambda selected_location, guides, value: (
            result
            if (selected_location, guides, value)
            == (location, generated.guides, generated)
            else pytest.fail("wrong installation inputs")
        ),
    )
    args = Namespace(narratives=None)

    assert cli_install._run_install(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "Installed 2 private guide(s): 1 created, 1 updated, 1 stale removed.",
        "Narrative artifact: disabled",
        f"Build evidence: {evidence_path} (artifact)",
        f"Cache: {tmp_path / 'cache.kv3'}",
        f"Backup: {tmp_path / 'backup'}",
        "Snapshot: snapshot",
        "Policies: 12/default=policy-a, 13/default=policy-b",
        "Cohort: ranked, client 123, as-of 456",
        "Launch Deadlock, open the hero's build browser, and check My Builds.",
    ]


def test_run_install_stops_when_deadlock_is_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_install, "_location", lambda _args: object())
    monkeypatch.setattr(cli_install, "deadlock_is_running", lambda: True)

    with pytest.raises(CacheError, match="close it"):
        cli_install._run_install(Namespace())


def test_export_restore_and_trace_commands_use_exact_inputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    location = SimpleNamespace(
        account_id=7,
        cache_path=tmp_path / "cache.kv3",
    )
    evidence_path = tmp_path / "build-evidence.json"
    evidence = SimpleNamespace(artifact_id="artifact")
    generated = SimpleNamespace(
        contexts=("context",),
        manifest=SimpleNamespace(snapshot_id="snapshot"),
    )
    writes: list[tuple[str, Path, object]] = []
    facts: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(cli_export, "_location", lambda _args: location)
    monkeypatch.setattr(
        cli_export, "_build_evidence", lambda _args: (evidence_path, evidence)
    )
    monkeypatch.setattr(
        cli_export,
        "_generate",
        lambda selected_args, selected_evidence, account_id: (
            generated
            if (selected_args, selected_evidence, account_id) == (args, evidence, 7)
            else pytest.fail("wrong generation inputs")
        ),
    )
    monkeypatch.setattr(
        cli_export,
        "_write_strategy_context",
        lambda path, value: writes.append(("context", path, value)),
    )
    monkeypatch.setattr(
        cli_export,
        "_write_policy_artifact",
        lambda path, value: writes.append(("policy", path, value)),
    )
    monkeypatch.setattr(
        cli_export,
        "record_stage_facts",
        lambda *values, **options: facts.append((values, options)),
    )
    args = Namespace(output=tmp_path / "context.json", policy_output=None)

    assert cli_export._run_export_context(args) == 0
    policy_path = tmp_path / "policies.json"
    assert writes == [
        ("context", args.output, generated),
        ("policy", policy_path, generated),
    ]
    assert facts == [
        (("artifact.write",), {"path": args.output}),
        (("artifact.write",), {"path": policy_path}),
    ]
    assert capsys.readouterr().out.splitlines() == [
        f"Exported 1 hero context(s): {args.output}",
        f"Policies: {policy_path}",
        f"Build evidence: {evidence_path} (artifact)",
        "Snapshot: snapshot",
    ]

    monkeypatch.setattr(
        cli_export,
        "restore_latest",
        lambda selected: (
            tmp_path / "backup"
            if selected is location
            else pytest.fail("wrong restore location")
        ),
    )
    assert cli_export._run_restore(Namespace()) == 0
    assert capsys.readouterr().out.splitlines() == [
        f"Restored cache backup: {tmp_path / 'backup'}",
        f"Cache: {location.cache_path}",
    ]

    trace_path = tmp_path / "trace"
    monkeypatch.setattr(
        cli_export,
        "render_trace_summary",
        lambda path, *, max_nodes: (
            "summary"
            if (path, max_nodes) == (trace_path, 9)
            else pytest.fail("wrong trace inputs")
        ),
    )
    assert cli_export._run_trace_summary(Namespace(path=trace_path, max_nodes=9)) == 0
    assert capsys.readouterr().out == "summary\n"


def test_support_decodes_location_catalog_epochs_and_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    location = object()
    catalog = object()
    calls: list[tuple[object, object]] = []
    monkeypatch.setattr(
        cli_support,
        "discover_cache",
        lambda *, account_id, cache_path: (
            calls.append((account_id, cache_path)) or location
        ),
    )
    monkeypatch.setattr(cli_support, "load_narrative_catalog", lambda _path: catalog)
    location_args = Namespace(account_id=7, cache_path=tmp_path / "cache")
    assert cli_support._location(location_args) is location
    assert calls == [(7, tmp_path / "cache")]
    assert cli_support._catalog(Namespace(narratives=None)) is None
    assert (
        cli_support._catalog(Namespace(narratives=tmp_path / "narratives")) is catalog
    )

    boundary = EpochBoundary("epoch", 1)
    empty_epochs = Namespace(
        mechanics_epoch=None,
        matchmaking_epoch=None,
        map_objectives_epoch=None,
        telemetry_epoch=None,
    )
    assert cli_support._epochs(empty_epochs) is None
    with pytest.raises(ValueError, match="all four"):
        cli_support._epochs(
            Namespace(
                mechanics_epoch=boundary,
                matchmaking_epoch=None,
                map_objectives_epoch=None,
                telemetry_epoch=None,
            )
        )
    complete_epochs = Namespace(
        mechanics_epoch=boundary,
        matchmaking_epoch=boundary,
        map_objectives_epoch=boundary,
        telemetry_epoch=boundary,
    )
    epochs = EpochSet(boundary, boundary, boundary, boundary)
    assert cli_support._epochs(complete_epochs) == epochs

    evidence = cast(
        "BuildEvidenceCatalog",
        SimpleNamespace(
            client_version=123,
            as_of_timestamp=456,
            epochs=epochs,
        ),
    )
    api_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def api_factory(*values: object, **options: object) -> object:
        api_calls.append((values, options))
        return "api"

    monkeypatch.setattr(cli_support, "DeadlockApi", api_factory)
    api_args = Namespace(
        rank_expansion="auto",
        api_base_url="https://example.invalid",
        min_rank=DEFAULT_RANK_RANGE.minimum,
        max_rank=DEFAULT_RANK_RANGE.maximum,
        match_mode=MatchMode.RANKED,
        client_version=None,
        as_of_timestamp=None,
        **vars(empty_epochs),
    )
    assert cli_support._api(api_args, evidence) == "api"
    assert api_calls == [
        (
            ("https://example.invalid",),
            {
                "rank_range": DEFAULT_RANK_RANGE,
                "match_mode": MatchMode.RANKED,
                "client_version": 123,
                "as_of_timestamp": 456,
                "epochs": epochs,
            },
        )
    ]


def test_support_loads_and_writes_complete_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    evidence_path = tmp_path / "build-evidence.json"
    evidence = SimpleNamespace(artifact_id="artifact", heroes={12: {}})
    facts: list[tuple[tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        cli_support, "_build_evidence_path", lambda _args: evidence_path
    )
    monkeypatch.setattr(cli_support, "load_build_evidence", lambda _path: evidence)
    monkeypatch.setattr(
        cli_support,
        "record_stage_facts",
        lambda *values, **options: facts.append((values, options)),
    )
    assert cli_support._build_evidence(Namespace()) == (evidence_path, evidence)
    assert facts == [
        (
            ("evidence.admission",),
            {"path": evidence_path, "artifact_id": "artifact", "hero_count": 1},
        )
    ]

    manifest = SimpleNamespace(as_dict=lambda: {"snapshot_id": "snapshot"})
    generated = cast(
        "GeneratedGuides",
        SimpleNamespace(
            patch="patch",
            contexts=["context"],
            manifest=manifest,
            item_mechanics={"item": {}},
            exclusions=((13, "skip"),),
            policies=["policy"],
            guides=[SimpleNamespace(hero_id=12)],
            eligible_hero_ids=frozenset({12, 13}),
            subset_selected=True,
        ),
    )
    documents: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
    writes: list[tuple[Path, object, dict[str, object]]] = []

    def context_document(*values: object, **options: object) -> object:
        documents.append(("context", values, options))
        return {"kind": "context"}

    def policy_document(*values: object, **options: object) -> object:
        documents.append(("policy", values, options))
        return {"kind": "policy"}

    monkeypatch.setattr(
        cli_support, "build_strategy_context_document", context_document
    )
    monkeypatch.setattr(cli_support, "build_policy_artifact", policy_document)
    monkeypatch.setattr(
        cli_support,
        "atomic_write_json",
        lambda path, value, **options: writes.append((path, value, options)),
    )
    context_path = tmp_path / "context.json"
    policy_path = tmp_path / "policies.json"
    cli_support._write_strategy_context(context_path, generated)
    cli_support._write_policy_artifact(policy_path, generated)

    shared = {
        "requested_hero_ids": {12},
        "exclusions": ((13, "skip"),),
    }
    assert documents == [
        (
            "context",
            ("patch", ["context"]),
            {**shared, "manifest": manifest, "item_mechanics": {"item": {}}},
        ),
        (
            "policy",
            (["policy"],),
            {**shared, "snapshot_manifest": {"snapshot_id": "snapshot"}},
        ),
    ]
    assert writes == [
        (context_path, {"kind": "context"}, {"compact": True}),
        (policy_path, {"kind": "policy"}, {}),
    ]
    full_generation = cast(
        "GeneratedGuides",
        SimpleNamespace(subset_selected=False, eligible_hero_ids=frozenset({12, 13})),
    )
    assert cli_support._requested_hero_ids(full_generation) == {12, 13}


def test_support_preview_uses_the_install_serializer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guide = cast("PurchaseGuide", SimpleNamespace(purchase_guidance=None))
    generated = cast(
        "GeneratedGuides",
        SimpleNamespace(
            persona="Player",
            patch=SimpleNamespace(title="Patch", published_at="2026-01-01"),
            rank_range=DEFAULT_RANK_RANGE,
        ),
    )
    presentation = object()
    calls: list[tuple[str, tuple[object, ...], dict[str, object]]] = []
    monkeypatch.setattr(
        cli_support,
        "build_presentation",
        lambda *values, **options: (
            calls.append(("presentation", values, options)) or presentation
        ),
    )
    monkeypatch.setattr(
        cli_support,
        "encode_hero_build",
        lambda *values, **options: calls.append(("encode", values, options)),
    )
    monkeypatch.setattr(
        cli_support,
        "describe_guide",
        lambda *values, **options: (
            calls.append(("describe", values, options)) or {"guide": True}
        ),
    )

    assert cli_support._describe_preview_guide(guide, generated, account_id=7) == {
        "guide": True,
        "purchase_guidance": None,
    }
    assert calls == [
        (
            "presentation",
            (guide,),
            {
                "persona": "Player",
                "patch_title": "Patch",
                "patch_published_at": "2026-01-01",
                "rank_range": DEFAULT_RANK_RANGE,
            },
        ),
        (
            "encode",
            (presentation,),
            {"build_id": 1, "account_id": 7, "timestamp": 0},
        ),
        ("describe", (guide,), {"presentation": presentation}),
    ]
