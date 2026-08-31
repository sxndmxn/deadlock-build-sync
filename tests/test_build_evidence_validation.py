from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import (
    assert_build_evidence_compatible,
    load_build_evidence,
    select_hero_build,
)
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE
from deadlock_build_sync.snapshot import (
    MatchMode,
)
from deadlock_build_sync.value_validation import (
    integer,
    require_object_list,
)
from tests.build_evidence_fixtures import (
    PATCH_IDENTITY,
    _assets,
    _document,
    _epochs,
    _first_item,
    _rank_catalog,
    _refingerprint,
    _sequence_policy,
    _situational_policy,
    _write,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_loader_rejects_tampering(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    _first_item(document)["wins"] = 999
    _write(path, document)

    with pytest.raises(ArtifactError, match="fingerprint"):
        load_build_evidence(path)


def test_loader_rejects_duplicate_permitting_sequence_policy(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    _sequence_policy(document)["version"] = 2
    _refingerprint(document)
    _write(path, document)

    with pytest.raises(ArtifactError, match="sequence policy"):
        load_build_evidence(path)


def test_loader_rejects_repeated_default_path_item(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    path_items = require_object_list(
        _sequence_policy(document)["component_expanded_default_path"]
    )
    path_items[1] = 101
    _refingerprint(document)
    _write(path, document)

    with pytest.raises(ArtifactError, match="repeats an item"):
        load_build_evidence(path)


def test_selection_rejects_default_path_outside_soul_windows(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    _sequence_policy(document)["component_expanded_default_path"] = [
        102,
        201,
        202,
        301,
        302,
        401,
        402,
        101,
    ]
    _refingerprint(document)
    _write(path, document)

    catalog = load_build_evidence(path)
    hero = catalog.heroes[13]
    assets = _assets()
    with pytest.raises(ArtifactError, match="first-ownership soul windows"):
        select_hero_build(hero, assets)


def test_compatibility_rejects_identity_drift(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    heroes: list[dict[str, object]] = [{"id": 13, "name": "Haze"}]
    _write(path, _document())
    catalog = load_build_evidence(path)
    rank_catalog = _rank_catalog()
    assets = _assets()
    epochs = _epochs()

    with pytest.raises(ArtifactError, match="patch"):
        assert_build_evidence_compatible(
            catalog,
            patch_identity="new-patch",
            client_version=6_673,
            as_of_timestamp=catalog.as_of_timestamp,
            match_mode=MatchMode.RANKED,
            rank_range=DEFAULT_RANK_RANGE,
            rank_catalog=rank_catalog,
            heroes=heroes,
            assets=assets,
            epochs=epochs,
        )

    assert_build_evidence_compatible(
        catalog,
        patch_identity=PATCH_IDENTITY,
        client_version=6_673,
        as_of_timestamp=catalog.as_of_timestamp,
        match_mode=MatchMode.RANKED,
        rank_range=DEFAULT_RANK_RANGE,
        rank_catalog=_rank_catalog(),
        heroes=heroes,
        assets=_assets(),
        epochs=_epochs(),
    )


def test_situational_branch_requires_every_comparative_gate(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    branch: dict[str, object] = {
        "threat": "healing",
        "item_id": 103,
        "enemy_hero_id": 7,
        "enemy_scope": "whole_enemy_team",
        "phase": 1,
        "tier": 1,
        "mechanic_ref": "item/103/healing-reduction",
        "enemy_mechanics_refs": ["asset:ability:7:description"],
        "comparator": "same-tier default continuation or save",
        "comparator_item_id": 101,
        "comparison_support": 20,
        "same_opportunity": True,
        "support": 20,
        "effective_support": 20.0,
        "overlap": 0.5,
        "stable": True,
        "comparative_interval": [0.01, 0.06],
        "fold_comparative_estimates": {
            "train": 0.03,
            "validation": 0.04,
            "test": 0.02,
        },
        "fold_support": {
            "train": {"item": 20, "comparator": 20},
            "validation": {"item": 20, "comparator": 20},
            "test": {"item": 20, "comparator": 20},
        },
        "trigger": "Enemy healing is observed.",
        "replacement": "Replace the next optional purchase.",
        "execution": "Apply healing reduction after contact.",
        "failure_condition": "Skip when healing is not material.",
    }
    _situational_policy(document)["branches"] = [branch]
    _refingerprint(document)
    _write(path, document)

    catalog = load_build_evidence(path)
    assert catalog.heroes[13].situational_policy is not None
    assert catalog.heroes[13].situational_policy.branches[0].threat == "healing"

    baseline = dict(branch)
    for changes, error in (
        ({"overlap": 0.49}, "unqualified situational branch"),
        ({"same_opportunity": False}, "unqualified situational branch"),
        ({"stable": False}, "unqualified situational branch"),
        ({"support": 19}, "situational support"),
        ({"effective_support": 19.0}, "effective support"),
        ({"comparison_support": 19}, "comparison support"),
        (
            {
                "fold_comparative_estimates": {
                    "train": 0.03,
                    "validation": 0.04,
                    "test": -0.02,
                }
            },
            "unstable situational fold evidence",
        ),
        (
            {
                "fold_support": {
                    "train": {"item": 20, "comparator": 20},
                    "validation": {"item": 20, "comparator": 20},
                    "test": {"item": 19, "comparator": 20},
                }
            },
            "situational test item support",
        ),
        ({"comparative_interval": [-0.01, 0.06]}, "interval"),
        ({"comparative_interval": [0.01, 0.12]}, "interval"),
        ({"mechanic_ref": "item/999/healing"}, "mechanic reference"),
    ):
        branch.clear()
        branch.update(baseline, **changes)
        _refingerprint(document)
        _write(path, document)
        with pytest.raises(ArtifactError, match=error):
            load_build_evidence(path)

    active_assets = [
        {
            **asset,
            "is_active_item": integer(asset["id"]) in {103, 102, 201, 202, 301},
        }
        for asset in _assets()
    ]
    active_document = _document(assets=active_assets)
    _situational_policy(active_document)["branches"] = [baseline]
    _refingerprint(active_document)
    _write(path, active_document)
    active_catalog = load_build_evidence(path)

    with pytest.raises(ArtifactError, match="illegal situational replacement"):
        select_hero_build(active_catalog.heroes[13], active_assets)
