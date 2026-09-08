from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.build_evidence import (
    assert_build_evidence_compatible,
    load_build_evidence,
    select_hero_build,
)
from deadlock_build_sync.build_evidence_loader import BuildEvidenceIdentity
from deadlock_build_sync.ranks import DEFAULT_RANK_RANGE
from deadlock_build_sync.snapshot import (
    MatchMode,
)
from deadlock_build_sync.value_validation import (
    integer,
    require_object_dict,
    require_object_list,
    require_object_rows,
)
from tests.build_evidence_fixtures import (
    PATCH_IDENTITY,
    _assets,
    _document,
    _epochs,
    _first_item,
    _rank_catalog,
    _sequence_policy,
    _situational_policy,
    _write,
    write_fingerprinted_evidence,
)
from tests.build_evidence_policy_fixtures import situational_branch

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
    write_fingerprinted_evidence(path, document)

    with pytest.raises(ArtifactError, match="sequence policy"):
        load_build_evidence(path)


def test_loader_rejects_repeated_default_path_item(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    path_items = require_object_list(
        _sequence_policy(document)["component_expanded_default_path"]
    )
    path_items[1] = 101
    write_fingerprinted_evidence(path, document)

    with pytest.raises(ArtifactError, match="repeats an item"):
        load_build_evidence(path)


def test_selection_preserves_legal_order_with_uncertain_soul_windows(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    build = require_object_rows(require_object_rows(document["heroes"])[0]["builds"])[0]
    discovery = require_object_dict(build["discovery"])
    frozen = require_object_dict(discovery["frozen_guide"])
    frozen["bounds"] = {"101": [20_000, 30_000], "102": [1_000, 2_000]}
    write_fingerprinted_evidence(path, document)

    catalog = load_build_evidence(path)
    hero = catalog.heroes[13]
    assets = _assets()
    selected = select_hero_build(hero, assets)
    assert hero.sequence_policy is not None
    assert (
        tuple(item.item_id for item in selected.core_purchase_path)
        == hero.sequence_policy.default_path
    )


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
            BuildEvidenceIdentity(
                patch_identity="new-patch",
                client_version=6_673,
                as_of_timestamp=catalog.as_of_timestamp,
                match_mode=MatchMode.RANKED,
                rank_range=DEFAULT_RANK_RANGE,
                rank_catalog=rank_catalog,
                heroes=heroes,
                assets=assets,
                epochs=epochs,
            ),
        )

    assert_build_evidence_compatible(
        catalog,
        BuildEvidenceIdentity(
            patch_identity=PATCH_IDENTITY,
            client_version=6_673,
            as_of_timestamp=catalog.as_of_timestamp,
            match_mode=MatchMode.RANKED,
            rank_range=DEFAULT_RANK_RANGE,
            rank_catalog=_rank_catalog(),
            heroes=heroes,
            assets=_assets(),
            epochs=_epochs(),
        ),
    )


def test_loader_accepts_supported_situational_branch(tmp_path: Path) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    branch = situational_branch()
    _situational_policy(document)["branches"] = [branch]
    write_fingerprinted_evidence(path, document)

    catalog = load_build_evidence(path)
    assert catalog.heroes[13].situational_policy is not None
    assert catalog.heroes[13].situational_policy.branches[0].threat == "healing"


@pytest.mark.parametrize(
    ("changes", "error"),
    [
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
    ],
    ids=[
        "overlap",
        "opportunity",
        "stability",
        "support",
        "effective-support",
        "comparison-support",
        "fold-estimates",
        "fold-support",
        "negative-interval",
        "wide-interval",
        "mechanic-reference",
    ],
)
def test_situational_branch_requires_every_comparative_gate(
    tmp_path: Path, changes: dict[str, object], error: str
) -> None:
    path = tmp_path / "build-evidence.json"
    document = _document()
    branch = situational_branch()
    branch.update(changes)
    _situational_policy(document)["branches"] = [branch]
    write_fingerprinted_evidence(path, document)

    with pytest.raises(ArtifactError, match=error):
        load_build_evidence(path)


def test_selection_rejects_a_branch_that_exceeds_active_item_slots(
    tmp_path: Path,
) -> None:
    path = tmp_path / "build-evidence.json"
    active_assets = [
        {
            **asset,
            "is_active_item": integer(asset["id"]) in {103, 102, 201, 202, 301},
        }
        for asset in _assets()
    ]
    active_document = _document(assets=active_assets)
    _situational_policy(active_document)["branches"] = [situational_branch()]
    write_fingerprinted_evidence(path, active_document)
    active_catalog = load_build_evidence(path)

    with pytest.raises(ArtifactError, match="illegal situational replacement"):
        select_hero_build(active_catalog.heroes[13], active_assets)
