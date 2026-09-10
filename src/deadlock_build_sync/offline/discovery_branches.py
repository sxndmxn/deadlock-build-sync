"""Compare legal choices at a frozen checkpoint without selecting future owners."""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass
from functools import cached_property
from statistics import NormalDist

import numpy as np
import polars as pl

from deadlock_build_sync.mechanics import ItemGraph, MechanicsError
from deadlock_build_sync.purchase_guidance_types import PurchaseState
from deadlock_build_sync.purchase_planner import (
    find_first_incomplete_checkpoint,
    is_item_or_upgrade_owned,
    plan_purchases,
)
from deadlock_build_sync.value_validation import (
    integer,
    number,
    object_dict,
    object_list,
)

from .contrast_feature_table import ContrastFeatureSelection, ContrastFeatureTable
from .contrast_features import select_contrast_row
from .contrast_screening import ContrastBalanceRejection
from .decision_rows import DecisionRows, IndexedDecisionRows
from .discovery_contrast_cache import BranchContrastCache
from .discovery_types import NominatedCoreBuild
from .doubly_robust_estimation import estimate_admissible_contrast


@dataclass(frozen=True)
class ChoiceObservation:
    row: dict[str, object]
    conditions: set[tuple[str, str | int]]


@dataclass(frozen=True)
class ChoiceCohort:
    observations: list[ChoiceObservation]
    frame: pl.DataFrame | None
    conditions: dict[tuple[str, str | int], list[int]]

    @cached_property
    def feature_table(self) -> ContrastFeatureTable:
        if self.frame is None:
            raise ValueError("Shared features require consistent observation columns")
        return ContrastFeatureTable.from_frame(self.frame)

    @classmethod
    def from_observations(cls, observations: list[ChoiceObservation]) -> ChoiceCohort:
        conditions: dict[tuple[str, str | int], list[int]] = {}
        rows = [observation.row for observation in observations]
        for index, observation in enumerate(observations):
            for condition in observation.conditions:
                conditions.setdefault(condition, []).append(index)
        frame = (
            pl.DataFrame(rows, infer_schema_length=None, strict=False)
            if rows and all(row.keys() == rows[0].keys() for row in rows)
            else None
        )
        return cls(observations if frame is None else [], frame, conditions)

    @cached_property
    def inventories(self) -> tuple[tuple[int, ...], ...]:
        groups = (
            self.frame["owned_before"].to_list()
            if self.frame is not None and "owned_before" in self.frame.columns
            else [None] * self.frame.height
            if self.frame is not None
            else [
                observation.row.get("owned_before") for observation in self.observations
            ]
        )
        shared: dict[tuple[int, ...], tuple[int, ...]] = {}
        result = []
        for group in groups:
            owned = tuple(integer(value) for value in object_list(group) or [])
            result.append(shared.setdefault(owned, owned))
        return tuple(result)

    def select_indices(
        self, candidate: dict[str, object], graph: ItemGraph
    ) -> list[int]:
        condition = str(candidate["condition"]), candidate["value"]
        indices = self.conditions.get(condition, [])
        if object_dict(candidate.get("substitution")) is None:
            return indices
        legal_inventories: dict[tuple[int, ...], bool] = {}
        selected = []
        for index in indices:
            owned = self.inventories[index]
            if owned not in legal_inventories:
                legal_inventories[owned] = is_substitution_legal(
                    {"owned_before": list(owned)}, candidate, graph
                )
            if legal_inventories[owned]:
                selected.append(index)
        return selected


def extract_branch_conditions(row: dict[str, object]) -> set[tuple[str, str | int]]:
    result: set[tuple[str, str | int]] = set()
    relative = row.get("relative_wealth")
    if isinstance(relative, (int, float)):
        result.add((
            "relative_wealth",
            "behind" if relative < 0.90 else "ahead" if relative > 1.10 else "even",
        ))
    for field, condition in (
        ("enemy_heroes", "enemy_hero"),
        ("enemy_items", "enemy_item"),
    ):
        result.update(
            (condition, integer(item)) for item in object_list(row.get(field)) or []
        )
    return result


def is_purchase_legal_at_checkpoint(
    row: dict[str, object],
    nominee: NominatedCoreBuild,
    item: int,
    checkpoint: int,
    graph: ItemGraph,
) -> bool:
    path, core = tuple(nominee["guide"]["path"]), tuple(nominee["items"])
    owned = tuple(
        integer(value) for value in object_list(row.get("owned_before")) or []
    )
    current = find_first_incomplete_checkpoint(graph, path, owned)
    if current != checkpoint or is_item_or_upgrade_owned(graph, item, owned):
        return False
    try:
        plan_purchases(
            graph, path, core, {item: checkpoint}, state=PurchaseState(owned)
        )
        plan_purchases(graph, path, core, {}, state=PurchaseState(owned))
    except (MechanicsError, ValueError):
        return False
    return True


def freeze_branch_candidates(
    rows: DecisionRows, nominee: NominatedCoreBuild, graph: ItemGraph
) -> list[dict[str, object]]:
    if not nominee["guide"]["ready"]:
        return []
    timing = nominee["guide"]["purchase_timing"]
    result = []
    for value in object_list(timing.get("items")) or []:
        record = object_dict(value)
        if record is None:
            raise ValueError("Frozen optional timing is malformed")
        item = integer(record["item_id"])
        counts = [
            integer(count)
            for count in object_list(record.get("counts_by_checkpoint")) or []
        ]
        checkpoint = max(range(len(counts)), key=counts.__getitem__)
        if counts[checkpoint] < max(
            20, integer(record["buyers"]) * 0.1
        ) or checkpoint >= len(nominee["guide"]["path"]):
            continue
        result.extend(freeze_choice_conditions(rows, nominee, item, checkpoint, graph))
    return result


def freeze_choice_conditions(
    rows: DecisionRows,
    nominee: NominatedCoreBuild,
    item: int,
    checkpoint: int,
    graph: ItemGraph,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    try:
        plan_purchases(
            graph,
            tuple(nominee["guide"]["path"]),
            tuple(nominee["items"]),
            {item: checkpoint},
        )
    except (MechanicsError, ValueError):
        return result
    comparator = nominee["guide"]["path"][checkpoint]
    discovery = _select_choice_observations(
        rows, nominee, (item, checkpoint, comparator), graph, fold="train"
    )
    counts = Counter(
        (condition, trigger, integer(observation.row["item_id"]))
        for observation in discovery
        for condition, trigger in observation.conditions
    )
    triggers = {(condition, trigger) for condition, trigger, _action in counts}
    for condition, trigger in sorted(triggers, key=str):
        if (
            min(counts[condition, trigger, action] for action in (item, comparator))
            >= 20
        ):
            result.append({
                "item_id": item,
                "after_step": checkpoint,
                "comparator_item_id": comparator,
                "condition": condition,
                "value": trigger,
            })
    return result


class BranchCandidateEvaluator:
    def __init__(
        self, rows: list[dict[str, object]], graph: ItemGraph, hypotheses: int
    ) -> None:
        self.rows = IndexedDecisionRows(rows)
        self.graph = graph
        self.hypotheses = hypotheses
        self.contrast_cache = BranchContrastCache(estimate_admissible_contrast)

    def evaluate_candidates(
        self, nominee: NominatedCoreBuild, candidates: list[dict[str, object]]
    ) -> dict[str, object]:
        rows, graph, hypotheses = self.rows, self.graph, self.hypotheses
        admitted, audit = [], []
        critical = NormalDist().inv_cdf(1 - 0.025 / max(1, hypotheses))
        choice_rows: dict[tuple[int, int, int], ChoiceCohort] = {}
        for candidate in candidates:
            item = integer(candidate["item_id"])
            comparator = integer(candidate["comparator_item_id"])
            frame, cohort, indices = _select_comparison_rows(
                rows, nominee, candidate, graph, choice_rows
            )
            counts = Counter(frame.select("fold", "item_id").iter_rows())
            if any(
                counts[fold, action] < 20
                for fold in ("train", "validation")
                for action in (item, comparator)
            ):
                audit.append({
                    **candidate,
                    "admitted": False,
                    "reason": "Insufficient support in a temporal fold",
                })
                continue
            try:
                contrast = self.contrast_cache.estimate_contrast(
                    frame,
                    item,
                    comparator,
                    feature_selection=ContrastFeatureSelection(
                        cohort.feature_table, indices
                    )
                    if cohort is not None and cohort.frame is not None
                    else None,
                )
            except (ValueError, RuntimeError) as error:
                audit.append({**candidate, "admitted": False, "reason": str(error)})
                continue
            if isinstance(contrast, ContrastBalanceRejection):
                audit.append({
                    **candidate,
                    "admitted": False,
                    "reason": "Balance check failed; later outcome diagnostics were not calculated",
                    "balance_screening": replace_nonfinite_values(asdict(contrast)),
                })
                continue
            record = object_dict(replace_nonfinite_values(asdict(contrast))) or {}
            lowers, widths = [], []
            for fold in ("train", "validation"):
                diagnostics = contrast.fold_diagnostics[fold]
                interval = object_list(diagnostics["interval"]) or []
                center = number(diagnostics["estimate"])
                radius = (
                    (number(interval[1]) - number(interval[0])) / 2 / 1.96 * critical
                )
                lowers.append(center - radius)
                widths.append(2 * radius)
            lower = min(lowers)
            passes = contrast.admitted and lower > 0 and max(widths) <= 0.10
            evidence = {
                **record,
                "hypotheses": hypotheses,
                "lower_bound": lower,
                "test_evaluated": False,
                "gates": {
                    "support": contrast.admitted,
                    "overlap": contrast.admitted,
                    "balance": contrast.admitted,
                    "uncertainty": max(widths) <= 0.10,
                    "temporal_stability": contrast.stable,
                    "corrected_outcome": lower > 0,
                    "legal_path": True,
                    "pre_decision_cohort": True,
                },
            }
            branch = {
                **candidate,
                "support": contrast.support,
                "lower_bound": lower,
                "evidence": evidence,
            }
            audit.append({**branch, "admitted": passes})
            if passes:
                admitted.append(branch)
        return {
            "version": 1,
            "branches": admitted,
            "audit": audit,
            "test_evaluated": False,
        }


def evaluate_branch_candidates(
    rows: list[dict[str, object]],
    nominee: NominatedCoreBuild,
    candidates: list[dict[str, object]],
    graph: ItemGraph,
    hypotheses: int,
) -> dict[str, object]:
    return BranchCandidateEvaluator(rows, graph, hypotheses).evaluate_candidates(
        nominee, candidates
    )


def is_substitution_legal(
    row: dict[str, object], candidate: dict[str, object], graph: ItemGraph
) -> bool:
    substitution = object_dict(candidate.get("substitution"))
    if substitution is None:
        return True
    path = tuple(
        integer(value) for value in object_list(substitution.get("path")) or []
    )
    core = tuple(
        integer(value) for value in object_list(substitution.get("core")) or []
    )
    owned = tuple(
        integer(value) for value in object_list(row.get("owned_before")) or []
    )
    try:
        plan_purchases(graph, path, core, {}, state=PurchaseState(owned))
    except (MechanicsError, ValueError):
        return False
    return True


def replace_nonfinite_values(value: object) -> object:
    if isinstance(value, float) and not math.isfinite(value):
        return None
    mapping = object_dict(value)
    if mapping is not None:
        return {key: replace_nonfinite_values(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        return [replace_nonfinite_values(item) for item in value]
    return value


def build_comparison_frame(
    rows: DecisionRows,
    nominee: NominatedCoreBuild,
    candidate: dict[str, object],
    graph: ItemGraph,
    choice_rows: dict[tuple[int, int, int], ChoiceCohort],
) -> pl.DataFrame:
    return _select_comparison_rows(rows, nominee, candidate, graph, choice_rows)[0]


def _select_comparison_rows(
    rows: DecisionRows,
    nominee: NominatedCoreBuild,
    candidate: dict[str, object],
    graph: ItemGraph,
    choice_rows: dict[tuple[int, int, int], ChoiceCohort],
) -> tuple[pl.DataFrame, ChoiceCohort | None, np.ndarray]:
    item, checkpoint, comparator = (
        integer(candidate["item_id"]),
        integer(candidate["after_step"]),
        integer(candidate["comparator_item_id"]),
    )
    key = item, checkpoint, comparator
    if key not in choice_rows:
        observations = _select_choice_observations(rows, nominee, key, graph)
        choice_rows[key] = ChoiceCohort.from_observations(observations)
    cohort = choice_rows[key]
    selected = cohort.select_indices(candidate, graph)
    if not selected:
        frame = pl.DataFrame(
            schema={
                "match_id": pl.Int64,
                "player_slot": pl.Int64,
                "fold": pl.String,
                "item_id": pl.Int64,
            }
        )
        return frame, None, np.empty(0, dtype=np.intp)
    frame = (
        cohort.frame[selected, :]
        if cohort.frame is not None
        else pl.DataFrame(
            [cohort.observations[index].row for index in selected],
            infer_schema_length=None,
            strict=False,
        )
    )
    first = frame.select(
        pl.struct("match_id", "player_slot").is_first_distinct()
    ).to_series()
    indices = np.asarray(selected, dtype=np.intp)[first.to_numpy()]
    return frame.filter(first), cohort, indices


def _select_choice_observations(
    rows: DecisionRows,
    nominee: NominatedCoreBuild,
    choice: tuple[int, int, int],
    graph: ItemGraph,
    *,
    fold: str | None = None,
) -> list[ChoiceObservation]:
    item, checkpoint, comparator = choice
    legal_inventories: dict[tuple[int, ...], bool] = {}
    selected = []
    candidates = (
        rows.select_items(item, comparator)
        if isinstance(rows, IndexedDecisionRows)
        else (row for row in rows if row["item_id"] in {item, comparator})
    )
    for row in candidates:
        if fold is not None and row["fold"] != fold:
            continue
        if row.get("relative_wealth") is None:
            continue
        owned = tuple(
            integer(value) for value in object_list(row.get("owned_before")) or []
        )
        if owned not in legal_inventories:
            legal_inventories[owned] = is_purchase_legal_at_checkpoint(
                row, nominee, item, checkpoint, graph
            )
        if legal_inventories[owned]:
            selected.append(
                ChoiceObservation(
                    select_contrast_row(row), extract_branch_conditions(row)
                )
            )
    return selected
