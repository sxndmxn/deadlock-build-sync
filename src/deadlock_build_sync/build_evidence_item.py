from __future__ import annotations

import math
from dataclasses import dataclass

from .artifacts import ArtifactError
from .build_evidence_types import (
    MINIMUM_IMBUE_SHARE,
    MINIMUM_IMBUE_SUPPORT,
    ItemEvidence,
)
from .build_evidence_values import (
    _document,
    _optional_float,
    _required_bool,
    _required_float,
    _required_int,
)

_FOLDS = ("training", "validation", "test")


@dataclass(frozen=True)
class _Identity:
    item_id: int
    name: str
    slot: str
    tier: int


@dataclass(frozen=True)
class _Totals:
    adopters: int
    eligible: int
    purchase_events: int
    wins: int
    adoption: float
    outcome: float


@dataclass(frozen=True)
class _Selection:
    adopters: int
    eligible: int
    adoption: float
    buy_time: float | None
    median_net_worth: float | None
    q25: float | None
    q75: float | None
    valid_observations: int
    valid_share: float


@dataclass(frozen=True)
class _Imbue:
    target_id: int | None
    target: str | None
    matches: int
    observations: int
    share: float


def _identity(document: dict[str, object], hero_id: int) -> _Identity:
    item_id = _required_int(document.get("item_id"), "item id", minimum=1)
    name = document.get("item")
    slot = document.get("slot")
    if not isinstance(name, str) or not name.strip():
        raise ArtifactError(f"hero {hero_id} item {item_id} lacks identity")
    if not isinstance(slot, str) or not slot.strip():
        raise ArtifactError(f"hero {hero_id} item {item_id} lacks identity")
    tier = _required_int(document.get("tier"), "item tier", minimum=1)
    if tier > 4:
        raise ArtifactError(f"hero {hero_id} item {item_id} has invalid tier")
    return _Identity(item_id, name.strip(), slot.strip().casefold(), tier)


def _totals(document: dict[str, object], hero_id: int, item_id: int) -> _Totals:
    adopters = _required_int(document.get("adopter_matches"), "adopter matches")
    eligible = _required_int(
        document.get("eligible_player_matches"),
        "eligible player matches",
        minimum=1,
    )
    purchase_events = _required_int(document.get("purchase_events"), "purchase events")
    wins = _required_int(document.get("wins"), "wins")
    if adopters > eligible or purchase_events < adopters or wins > adopters:
        raise ArtifactError(f"hero {hero_id} item {item_id} has impossible counts")
    adoption = _required_float(document.get("adoption"), "adoption", maximum=1.0)
    outcome = _required_float(
        document.get("observed_outcome_rate"), "observed outcome", maximum=1.0
    )
    if not math.isclose(adoption, adopters / eligible, abs_tol=1e-9):
        raise ArtifactError(f"hero {hero_id} item {item_id} adoption is inconsistent")
    expected_outcome = wins / adopters if adopters else 0.0
    if not math.isclose(outcome, expected_outcome, abs_tol=1e-9):
        raise ArtifactError(f"hero {hero_id} item {item_id} outcome is inconsistent")
    return _Totals(adopters, eligible, purchase_events, wins, adoption, outcome)


def _quantiles(
    document: dict[str, object],
    *,
    prefix: str = "",
) -> tuple[float | None, float | None, float | None]:
    label_prefix = f"{prefix} " if prefix else ""
    median = _optional_float(
        document.get(
            f"{prefix}_median_valid_buy_net_worth"
            if prefix
            else "median_valid_buy_net_worth"
        ),
        f"{label_prefix}median buy net worth",
    )
    q25 = _optional_float(
        document.get(f"{prefix}_buy_net_worth_q25" if prefix else "buy_net_worth_q25"),
        f"{label_prefix}buy net worth q25",
    )
    q75 = _optional_float(
        document.get(f"{prefix}_buy_net_worth_q75" if prefix else "buy_net_worth_q75"),
        f"{label_prefix}buy net worth q75",
    )
    return median, q25, q75


def _valid_quantiles(
    median: float | None,
    q25: float | None,
    q75: float | None,
) -> bool:
    if (median is None) != (q25 is None) or (median is None) != (q75 is None):
        return False
    if median is None or q25 is None or q75 is None:
        return True
    return q25 <= median <= q75


def _base_quantiles(
    document: dict[str, object], hero_id: int, item_id: int
) -> tuple[float | None, float | None, float | None]:
    median, q25, q75 = _quantiles(document)
    if not _valid_quantiles(median, q25, q75):
        raise ArtifactError(
            f"hero {hero_id} item {item_id} has invalid net-worth quantiles"
        )
    return median, q25, q75


def _fold_adoption(
    document: dict[str, object], hero_id: int, item_id: int
) -> tuple[dict[str, tuple[int, int]], dict[str, float]]:
    counts: dict[str, tuple[int, int]] = {}
    adoption: dict[str, float] = {}
    for fold in _FOLDS:
        adopters = _required_int(
            document.get(f"{fold}_adopter_matches"), f"{fold} adopter matches"
        )
        eligible = _required_int(
            document.get(f"{fold}_eligible_player_matches"),
            f"{fold} eligible player matches",
            minimum=1 if fold == "training" else 0,
        )
        rate = _required_float(
            document.get(f"{fold}_adoption"), f"{fold} adoption", maximum=1.0
        )
        expected = adopters / eligible if eligible else 0.0
        if adopters > eligible or not math.isclose(rate, expected, abs_tol=1e-9):
            raise ArtifactError(
                f"hero {hero_id} item {item_id} has invalid fold counts"
            )
        counts[fold] = adopters, eligible
        adoption[fold] = rate
    return counts, adoption


def _selection_counts(
    document: dict[str, object],
    hero_id: int,
    item_id: int,
    totals: _Totals,
    folds: dict[str, tuple[int, int]],
) -> tuple[int, int, float]:
    adopters = _required_int(
        document.get("selection_adopter_matches"), "selection adopter matches"
    )
    eligible = _required_int(
        document.get("selection_eligible_player_matches"),
        "selection eligible player matches",
        minimum=1,
    )
    adoption = _required_float(
        document.get("selection_adoption"), "selection adoption", maximum=1.0
    )
    expected_adopters = folds["training"][0] + folds["validation"][0]
    expected_eligible = folds["training"][1] + folds["validation"][1]
    consistent = (
        adopters == expected_adopters
        and eligible == expected_eligible
        and totals.adopters == adopters + folds["test"][0]
        and totals.eligible == eligible + folds["test"][1]
        and math.isclose(adoption, adopters / eligible, abs_tol=1e-9)
    )
    if not consistent:
        raise ArtifactError(
            f"hero {hero_id} item {item_id} has inconsistent selection counts"
        )
    return adopters, eligible, adoption


def _selection_window(
    document: dict[str, object],
    hero_id: int,
    item_id: int,
    *,
    adopters: int,
    eligible: int,
    adoption: float,
) -> _Selection:
    buy_time = _optional_float(
        document.get("selection_median_buy_time_s"), "selection median buy time"
    )
    median, q25, q75 = _quantiles(document, prefix="selection")
    observations = _required_int(
        document.get("selection_valid_buy_net_worth_observations"),
        "selection valid buy net worth observations",
    )
    share = _required_float(
        document.get("selection_valid_buy_net_worth_share"),
        "selection valid buy net worth share",
        maximum=1.0,
    )
    expected_share = observations / adopters if adopters else 0.0
    invalid = (
        (buy_time is None) != (adopters == 0)
        or observations > adopters
        or not math.isclose(share, expected_share, abs_tol=1e-9)
        or (median is None) != (observations == 0)
        or not _valid_quantiles(median, q25, q75)
    )
    if invalid:
        raise ArtifactError(
            f"hero {hero_id} item {item_id} has invalid selection timing evidence"
        )
    return _Selection(
        adopters,
        eligible,
        adoption,
        buy_time,
        median,
        q25,
        q75,
        observations,
        share,
    )


def _fold_windows(
    document: dict[str, object],
    hero_id: int,
    item_id: int,
    folds: dict[str, tuple[int, int]],
    selection_observations: int,
) -> dict[str, tuple[int, float | None, float | None]]:
    windows: dict[str, tuple[int, float | None, float | None]] = {}
    for fold in ("training", "validation"):
        observations = _required_int(
            document.get(f"{fold}_valid_buy_net_worth_observations"),
            f"{fold} valid buy net worth observations",
        )
        lower = _optional_float(
            document.get(f"{fold}_buy_net_worth_q25"),
            f"{fold} buy net worth q25",
        )
        upper = _optional_float(
            document.get(f"{fold}_buy_net_worth_q75"),
            f"{fold} buy net worth q75",
        )
        invalid = (
            observations > folds[fold][0]
            or (lower is None) != (observations == 0)
            or (upper is None) != (observations == 0)
            or (lower is not None and upper is not None and lower > upper)
        )
        if invalid:
            raise ArtifactError(
                f"hero {hero_id} item {item_id} has invalid {fold} window evidence"
            )
        windows[fold] = observations, lower, upper
    if selection_observations != sum(row[0] for row in windows.values()):
        raise ArtifactError(
            f"hero {hero_id} item {item_id} has inconsistent window counts"
        )
    return windows


def _imbue(document: dict[str, object], hero_id: int, item_id: int) -> _Imbue:
    raw_target_id = document.get("imbue_target_ability_id")
    target_id = (
        None
        if raw_target_id is None
        else _required_int(raw_target_id, "imbue target ability id", minimum=1)
    )
    raw_target = document.get("imbue_target_ability")
    matches = _required_int(
        document.get("imbue_target_matches"), "imbue target matches"
    )
    observations = _required_int(
        document.get("imbue_observations"), "imbue observations"
    )
    share = _required_float(
        document.get("imbue_target_share"), "imbue target share", maximum=1.0
    )
    if target_id is None:
        if raw_target is not None or any((matches, observations, share)):
            raise ArtifactError(
                f"hero {hero_id} item {item_id} has invalid imbue evidence"
            )
        return _Imbue(None, None, matches, observations, share)
    valid_target = isinstance(raw_target, str) and bool(raw_target.strip())
    valid_rate = observations > 0 and math.isclose(
        share, matches / observations, abs_tol=1e-9
    )
    if (
        not valid_target
        or matches > observations
        or matches < MINIMUM_IMBUE_SUPPORT
        or share <= MINIMUM_IMBUE_SHARE
        or not valid_rate
    ):
        raise ArtifactError(f"hero {hero_id} item {item_id} has invalid imbue evidence")
    return _Imbue(target_id, str(raw_target).strip(), matches, observations, share)


def _item(value: object, hero_id: int) -> ItemEvidence:
    document = _document(value, f"hero {hero_id} has a malformed item evidence row")
    identity = _identity(document, hero_id)
    totals = _totals(document, hero_id, identity.item_id)
    median, q25, q75 = _base_quantiles(document, hero_id, identity.item_id)
    folds, fold_adoption = _fold_adoption(document, hero_id, identity.item_id)
    selection_counts = _selection_counts(
        document, hero_id, identity.item_id, totals, folds
    )
    selection = _selection_window(
        document,
        hero_id,
        identity.item_id,
        adopters=selection_counts[0],
        eligible=selection_counts[1],
        adoption=selection_counts[2],
    )
    windows = _fold_windows(
        document,
        hero_id,
        identity.item_id,
        folds,
        selection.valid_observations,
    )
    imbue = _imbue(document, hero_id, identity.item_id)
    return ItemEvidence(
        item_id=identity.item_id,
        item=identity.name,
        tier=identity.tier,
        cost=_required_int(document.get("cost"), "item cost"),
        slot=identity.slot,
        active=_required_bool(document.get("active"), "active-item flag"),
        adopter_matches=totals.adopters,
        eligible_player_matches=totals.eligible,
        purchase_events=totals.purchase_events,
        wins=totals.wins,
        adoption=totals.adoption,
        observed_outcome_rate=totals.outcome,
        median_buy_time_s=_required_float(
            document.get("median_buy_time_s"), "median buy time"
        ),
        median_valid_buy_net_worth=median,
        buy_net_worth_q25=q25,
        buy_net_worth_q75=q75,
        valid_buy_net_worth_share=_required_float(
            document.get("valid_buy_net_worth_share"),
            "valid buy net worth share",
            maximum=1.0,
        ),
        selection_adopter_matches=selection.adopters,
        selection_eligible_player_matches=selection.eligible,
        training_adopter_matches=folds["training"][0],
        training_eligible_player_matches=folds["training"][1],
        validation_adopter_matches=folds["validation"][0],
        validation_eligible_player_matches=folds["validation"][1],
        test_adopter_matches=folds["test"][0],
        test_eligible_player_matches=folds["test"][1],
        selection_adoption=selection.adoption,
        training_adoption=fold_adoption["training"],
        validation_adoption=fold_adoption["validation"],
        test_adoption=fold_adoption["test"],
        selection_median_buy_time_s=selection.buy_time,
        selection_median_valid_buy_net_worth=selection.median_net_worth,
        selection_buy_net_worth_q25=selection.q25,
        selection_buy_net_worth_q75=selection.q75,
        selection_valid_buy_net_worth_share=selection.valid_share,
        selection_valid_buy_net_worth_observations=selection.valid_observations,
        training_valid_buy_net_worth_observations=windows["training"][0],
        validation_valid_buy_net_worth_observations=windows["validation"][0],
        training_buy_net_worth_q25=windows["training"][1],
        training_buy_net_worth_q75=windows["training"][2],
        validation_buy_net_worth_q25=windows["validation"][1],
        validation_buy_net_worth_q75=windows["validation"][2],
        imbue_target_ability_id=imbue.target_id,
        imbue_target_ability=imbue.target,
        imbue_target_matches=imbue.matches,
        imbue_observations=imbue.observations,
        imbue_target_share=imbue.share,
    )
