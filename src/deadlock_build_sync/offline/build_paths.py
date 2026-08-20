from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import KMeans
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import precision_recall_fscore_support

MINIMUM_PATH_SUPPORT = 20
MINIMUM_VALIDATION_GAIN = 0.10
MINIMUM_ASSIGNMENT_CONFIDENCE = 0.70
MINIMUM_TEST_PRECISION = 0.75
MINIMUM_TEST_RECALL = 0.50
MINIMUM_DISTINCT_ITEMS = 2
MINIMUM_SIGNATURE_LIFT = 0.20

type PlayerIdentity = tuple[int, int]


@dataclass(frozen=True)
class DiscoveredBuildPath:
    path_id: str
    member_ids: frozenset[PlayerIdentity]
    signature_item_ids: tuple[int, ...]
    fold_support: dict[str, int]
    diagnostics: dict[str, object]


@dataclass(frozen=True)
class _Leaf:
    member_ids: frozenset[PlayerIdentity]
    diagnostics: tuple[dict[str, object], ...]


def _item_universe(
    inventories: dict[PlayerIdentity, tuple[int, ...]],
    members: frozenset[PlayerIdentity],
) -> tuple[int, ...]:
    support = Counter(
        item_id
        for identity in members
        for item_id in set(inventories.get(identity, ()))
    )
    return tuple(
        item_id
        for item_id, count in sorted(support.items())
        if count >= MINIMUM_PATH_SUPPORT
    )


def _matrix(
    inventories: dict[PlayerIdentity, tuple[int, ...]],
    identities: list[PlayerIdentity],
    item_ids: tuple[int, ...],
) -> np.ndarray:
    columns = {item_id: index for index, item_id in enumerate(item_ids)}
    result = np.zeros((len(identities), len(item_ids)), dtype=np.float32)
    for row, identity in enumerate(identities):
        for item_id in inventories.get(identity, ()):
            column = columns.get(item_id)
            if column is not None:
                result[row, column] = 1.0
    return result


def _fold_counts(
    identities: list[PlayerIdentity],
    labels: np.ndarray,
    folds_by_match: dict[int, str],
) -> dict[int, dict[str, int]]:
    result = {0: Counter(), 1: Counter()}
    for identity, label in zip(identities, labels, strict=True):
        result[int(label)][folds_by_match[identity[0]]] += 1
    return {label: dict(counts) for label, counts in result.items()}


def _has_fold_support(counts: dict[int, dict[str, int]]) -> bool:
    return all(
        counts[label].get(fold, 0) >= MINIMUM_PATH_SUPPORT
        for label in (0, 1)
        for fold in ("train", "validation", "test")
    )


def _validation_gain(
    train: np.ndarray,
    validation: np.ndarray,
    centers: np.ndarray,
) -> float:
    if not len(validation):
        return 0.0
    parent = train.mean(axis=0)
    parent_error = float(np.square(validation - parent).sum(axis=1).mean())
    if parent_error <= 0:
        return 0.0
    child_error = float(
        np
        .square(validation[:, None, :] - centers[None, :, :])
        .sum(axis=2)
        .min(axis=1)
        .mean()
    )
    return 1.0 - child_error / parent_error


def _distinct_items(centers: np.ndarray, item_ids: tuple[int, ...]) -> tuple[int, ...]:
    deltas = centers[0] - centers[1]
    ranked = sorted(
        range(len(item_ids)),
        key=lambda index: (-abs(float(deltas[index])), item_ids[index]),
    )
    return tuple(
        item_ids[index] for index in ranked if abs(float(deltas[index])) >= 0.20
    )


def _early_metrics(
    early_train: np.ndarray,
    train_labels: np.ndarray,
    early_test: np.ndarray,
    test_labels: np.ndarray,
) -> tuple[tuple[float, float], ...] | None:
    if len({int(value) for value in train_labels}) != 2 or not len(test_labels):
        return None
    classifier = LogisticRegression(
        C=0.5,
        max_iter=2_000,
        random_state=0,
        solver="liblinear",
    )
    classifier.fit(early_train, train_labels)
    predicted = classifier.predict(early_test)
    precision, recall, _, _ = precision_recall_fscore_support(
        test_labels,
        predicted,
        labels=[0, 1],
        zero_division=0,
    )
    return tuple(
        (float(path_precision), float(path_recall))
        for path_precision, path_recall in zip(precision, recall, strict=True)
    )


def _attempt_split(
    inventories: dict[PlayerIdentity, tuple[int, ...]],
    early_inventories: dict[PlayerIdentity, tuple[int, ...]],
    folds_by_match: dict[int, str],
    members: frozenset[PlayerIdentity],
) -> tuple[_Leaf, _Leaf] | None:
    identities = sorted(members)
    item_ids = _item_universe(inventories, members)
    if len(item_ids) < MINIMUM_DISTINCT_ITEMS:
        return None
    fold_rows = {
        fold: [
            index
            for index, identity in enumerate(identities)
            if folds_by_match[identity[0]] == fold
        ]
        for fold in ("train", "validation", "test")
    }
    final = _matrix(inventories, identities, item_ids)
    early = _matrix(early_inventories, identities, item_ids)
    train_rows = fold_rows["train"]
    validation_rows = fold_rows["validation"]
    test_rows = fold_rows["test"]
    if (
        any(len(rows) < MINIMUM_PATH_SUPPORT * 2 for rows in fold_rows.values())
        or len(np.unique(final[train_rows], axis=0)) < 2
    ):
        return None
    model = KMeans(n_clusters=2, n_init=20, random_state=0)
    model.fit(final[train_rows])
    train_labels = model.predict(final[train_rows])
    if len(np.unique(train_labels)) < 2:
        return None

    assignment_model = LogisticRegression(
        C=1.0,
        max_iter=2_000,
        random_state=0,
        solver="liblinear",
    )
    assignment_model.fit(final[train_rows], train_labels)
    probabilities = assignment_model.predict_proba(final)
    confidence = probabilities.max(axis=1)
    labels = probabilities.argmax(axis=1)
    admitted_rows = [
        index
        for index, probability in enumerate(confidence)
        if probability >= MINIMUM_ASSIGNMENT_CONFIDENCE
    ]
    admitted_identities = [identities[index] for index in admitted_rows]
    admitted_labels = labels[admitted_rows]
    counts = _fold_counts(admitted_identities, admitted_labels, folds_by_match)
    gain = _validation_gain(
        final[train_rows],
        final[validation_rows],
        model.cluster_centers_,
    )
    distinct = _distinct_items(model.cluster_centers_, item_ids)
    if (
        not _has_fold_support(counts)
        or gain < MINIMUM_VALIDATION_GAIN
        or len(distinct) < MINIMUM_DISTINCT_ITEMS
    ):
        return None

    confident_test_rows = [
        row for row in test_rows if confidence[row] >= MINIMUM_ASSIGNMENT_CONFIDENCE
    ]
    metrics = _early_metrics(
        early[train_rows],
        train_labels,
        early[confident_test_rows],
        labels[confident_test_rows],
    )
    if metrics is None or any(
        precision < MINIMUM_TEST_PRECISION or recall < MINIMUM_TEST_RECALL
        for precision, recall in metrics
    ):
        return None

    children: list[_Leaf] = []
    for label in (0, 1):
        child_ids = frozenset(
            identity
            for identity, assigned in zip(
                admitted_identities, admitted_labels, strict=True
            )
            if int(assigned) == label
        )
        children.append(
            _Leaf(
                child_ids,
                (
                    {
                        "validation_distortion_gain": gain,
                        "assignment_confidence_floor": MINIMUM_ASSIGNMENT_CONFIDENCE,
                        "fold_support": counts[label],
                        "test_precision": metrics[label][0],
                        "test_recall": metrics[label][1],
                        "distinct_item_ids": list(distinct),
                        "abstained_matches": len(identities) - len(admitted_rows),
                    },
                ),
            )
        )
    return children[0], children[1]


def _split_recursively(
    inventories: dict[PlayerIdentity, tuple[int, ...]],
    early_inventories: dict[PlayerIdentity, tuple[int, ...]],
    folds_by_match: dict[int, str],
    leaf: _Leaf,
) -> list[_Leaf]:
    split = _attempt_split(
        inventories,
        early_inventories,
        folds_by_match,
        leaf.member_ids,
    )
    if split is None:
        return [leaf]
    result: list[_Leaf] = []
    for child in split:
        nested = _Leaf(child.member_ids, (*leaf.diagnostics, *child.diagnostics))
        result.extend(
            _split_recursively(
                inventories,
                early_inventories,
                folds_by_match,
                nested,
            )
        )
    return result


def _signature_items(
    inventories: dict[PlayerIdentity, tuple[int, ...]],
    members: frozenset[PlayerIdentity],
    others: frozenset[PlayerIdentity],
) -> tuple[int, ...]:
    member_counts = Counter(
        item_id for identity in members for item_id in set(inventories[identity])
    )
    other_counts = Counter(
        item_id for identity in others for item_id in set(inventories[identity])
    )
    adoption_lift = {
        item_id: member_counts[item_id] / max(1, len(members))
        - other_counts[item_id] / max(1, len(others))
        for item_id in member_counts
    }
    ranked = sorted(
        (
            item_id
            for item_id, lift in adoption_lift.items()
            if lift >= MINIMUM_SIGNATURE_LIFT
        ),
        key=lambda item_id: (
            -adoption_lift[item_id],
            -member_counts[item_id],
            item_id,
        ),
    )
    return tuple(ranked[:3])


def _path_id(signature_item_ids: tuple[int, ...]) -> str:
    encoded = json.dumps(signature_item_ids, separators=(",", ":")).encode()
    return "path-" + hashlib.sha256(encoded).hexdigest()[:12]


def discover_build_paths(
    inventories: dict[PlayerIdentity, tuple[int, ...]],
    early_inventories: dict[PlayerIdentity, tuple[int, ...]],
    folds_by_match: dict[int, str],
) -> tuple[DiscoveredBuildPath, ...]:
    """Return supported purchase archetypes without using match outcomes."""
    root_ids = frozenset(inventories)
    leaves = _split_recursively(
        inventories,
        early_inventories,
        folds_by_match,
        _Leaf(root_ids, ()),
    )
    if len(leaves) == 1:
        fold_support = dict(
            Counter(folds_by_match[identity[0]] for identity in root_ids)
        )
        return (
            DiscoveredBuildPath(
                "default",
                root_ids,
                (),
                fold_support,
                {"selection": "single-supported-path"},
            ),
        )

    paths = []
    for leaf in leaves:
        others = root_ids - leaf.member_ids
        signature = _signature_items(inventories, leaf.member_ids, others)
        fold_support = dict(
            Counter(folds_by_match[identity[0]] for identity in leaf.member_ids)
        )
        paths.append(
            DiscoveredBuildPath(
                _path_id(signature),
                leaf.member_ids,
                signature,
                fold_support,
                {
                    "selection": "recursive-held-out-purchase-split",
                    "splits": list(leaf.diagnostics),
                },
            )
        )
    return tuple(sorted(paths, key=lambda path: path.path_id))
