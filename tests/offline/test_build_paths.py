from __future__ import annotations

from deadlock_build_sync.offline.build_paths import discover_build_paths


def _two_paths(
    *, predictable_early: bool = True, omit_test_path: bool = False
) -> tuple[
    dict[tuple[int, int], tuple[int, ...]],
    dict[tuple[int, int], tuple[int, ...]],
    dict[int, str],
]:
    inventories = {}
    early = {}
    folds = {}
    match_id = 1
    for fold in ("train", "validation", "test"):
        for path_index, signature in enumerate(((10, 11), (20, 21))):
            if omit_test_path and fold == "test" and path_index == 1:
                continue
            for _ in range(60):
                identity = match_id, path_index
                inventories[identity] = (1, 2, *signature)
                early[identity] = signature if predictable_early else (1, 2)
                folds[match_id] = fold
                match_id += 1
    return inventories, early, folds


def test_discovers_two_stable_early_identifiable_item_paths() -> None:
    paths = discover_build_paths(*_two_paths())

    assert len(paths) == 2
    assert {path.fold_support["test"] for path in paths} == {60}
    assert {path.signature_item_ids for path in paths} == {(10, 11), (20, 21)}
    assert all(
        path.diagnostics["selection"] == "recursive-held-out-purchase-split"
        for path in paths
    )


def test_keeps_one_build_when_final_paths_are_not_early_identifiable() -> None:
    paths = discover_build_paths(*_two_paths(predictable_early=False))

    assert len(paths) == 1
    assert paths[0].path_id == "default"
    assert len(paths[0].member_ids) == 360


def test_keeps_one_build_when_a_path_lacks_temporal_support() -> None:
    paths = discover_build_paths(*_two_paths(omit_test_path=True))

    assert len(paths) == 1
    assert paths[0].path_id == "default"
