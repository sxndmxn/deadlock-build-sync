from __future__ import annotations

import gc
import hashlib
import json
import math
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from itertools import combinations
from typing import Any

import duckdb
import numpy as np
import polars as pl
import xgboost as xgb

from .api import read_json, write_json
from .config import RunPaths, sha256_json

XGBRanker: Any = vars(xgb)["XGBRanker"]
SEED = 20_260_809
START_ITEM = -1
MAX_ACTIVE_ITEMS = 4
TRAIN_CANDIDATES = 32
CORE_CANDIDATES = 64
FEATURE_NAMES = (
    "first_item",
    "previous_item",
    "purchase_position",
    "phase",
    "current_time_s",
    "prior_spend",
    "own_net_worth",
    "own_net_worth_missing",
    "team_lead",
    "team_lead_missing",
    "rank_family",
    "calibration",
    "owned_items",
    "owned_weapon",
    "owned_vitality",
    "owned_spirit",
    "owned_active",
    "candidate_item",
    "candidate_tier",
    "candidate_cost",
    "candidate_slot",
    "candidate_active",
    "candidate_unique",
    "component_credit",
    "incremental_cost",
    "owned_components",
    "direct_upgrade",
    "first_transition_logp",
    "transition_logp",
    "position_logp",
    "phase_logp",
    "popularity_logp",
)
FEATURE_TYPES = (
    "c",
    "c",
    "int",
    "c",
    "q",
    "q",
    "q",
    "i",
    "q",
    "i",
    "c",
    "i",
    "int",
    "int",
    "int",
    "int",
    "int",
    "c",
    "c",
    "q",
    "c",
    "i",
    "i",
    "q",
    "q",
    "int",
    "i",
    "q",
    "q",
    "q",
    "q",
    "q",
)


@dataclass(frozen=True)
class Asset:
    item_id: int
    index: int
    name: str
    tier: int
    cost: int
    slot: str
    slot_index: int
    active: bool
    unique: bool
    components: tuple[int, ...]


@dataclass(frozen=True)
class PurchaseQuery:
    match_id: int
    player_slot: int
    fold: str
    position: int
    phase: int
    first_item: int
    previous_item: int
    current_time_s: int
    prior_spend: int
    own_net_worth: float | None
    team_lead: float | None
    average_badge: int
    calibration: bool
    owned: tuple[int, ...]
    target: int
    target_buy_time_s: int
    component_upgrade: bool


@dataclass(frozen=True)
class InventoryObservation:
    fold: str
    items: frozenset[int]


@dataclass(frozen=True)
class RankRecord:
    match_id: int
    target: int
    previous: int
    component_upgrade: bool
    baseline_rank: int
    xgb_rank: int


@dataclass(frozen=True)
class ExperimentConfig:
    train_queries: int = 20_000
    validation_queries: int = 5_000
    test_queries: int = 10_000
    pilot_train_queries: int = 8_000
    pilot_validation_queries: int = 2_000
    evaluation_batch_queries: int = 250
    bootstrap_replicates: int = 1_000
    device: str = "auto"


@dataclass(frozen=True)
class ModelSpec:
    name: str
    objective: str
    max_depth: int


MODEL_SPECS = (
    ModelSpec("ndcg_depth6", "rank:ndcg", 6),
    ModelSpec("ndcg_depth8", "rank:ndcg", 8),
    ModelSpec("pairwise_depth6", "rank:pairwise", 6),
)


class BaselineCounts:
    def __init__(self, item_count: int) -> None:
        self.item_count = item_count
        self.first_transition: Counter[tuple[int, int, int]] = Counter()
        self.transition: Counter[tuple[int, int]] = Counter()
        self.position: Counter[tuple[int, int]] = Counter()
        self.phase: Counter[tuple[int, int]] = Counter()
        self.popularity: Counter[int] = Counter()
        self.first_context: Counter[tuple[int, int]] = Counter()
        self.transition_context: Counter[int] = Counter()
        self.position_context: Counter[int] = Counter()
        self.phase_context: Counter[int] = Counter()
        self.total = 0

    @classmethod
    def fit(cls, queries: list[PurchaseQuery], item_count: int) -> BaselineCounts:
        result = cls(item_count)
        for query in queries:
            if query.fold != "train":
                continue
            target = query.target
            first_key = (query.first_item, query.previous_item)
            result.first_transition[*first_key, target] += 1
            result.transition[query.previous_item, target] += 1
            result.position[query.position, target] += 1
            result.phase[query.phase, target] += 1
            result.popularity[target] += 1
            result.first_context[first_key] += 1
            result.transition_context[query.previous_item] += 1
            result.position_context[query.position] += 1
            result.phase_context[query.phase] += 1
            result.total += 1
        return result

    def _logp(self, count: int, total: int) -> float:
        return math.log((count + 1) / (total + self.item_count))

    def feature_scores(self, query: PurchaseQuery, candidate: int) -> tuple[float, ...]:
        first_key = (query.first_item, query.previous_item)
        return (
            self._logp(
                self.first_transition[*first_key, candidate],
                self.first_context[first_key],
            ),
            self._logp(
                self.transition[query.previous_item, candidate],
                self.transition_context[query.previous_item],
            ),
            self._logp(
                self.position[query.position, candidate],
                self.position_context[query.position],
            ),
            self._logp(
                self.phase[query.phase, candidate],
                self.phase_context[query.phase],
            ),
            self._logp(self.popularity[candidate], self.total),
        )

    def rank_score(self, query: PurchaseQuery, candidate: int) -> tuple[int, float]:
        first_key = (query.first_item, query.previous_item)
        if self.first_context[first_key]:
            return (
                4,
                self._logp(
                    self.first_transition[*first_key, candidate],
                    self.first_context[first_key],
                ),
            )
        if self.transition_context[query.previous_item]:
            return (
                3,
                self._logp(
                    self.transition[query.previous_item, candidate],
                    self.transition_context[query.previous_item],
                ),
            )
        if self.position_context[query.position]:
            return (
                2,
                self._logp(
                    self.position[query.position, candidate],
                    self.position_context[query.position],
                ),
            )
        return (1, self._logp(self.popularity[candidate], self.total))


def _phase(time_s: int) -> int:
    if time_s < 540:
        return 0
    if time_s < 1200:
        return 1
    if time_s < 1800:
        return 2
    return 3


def _stable_hash(*values: object) -> int:
    payload = "|".join(str(value) for value in values).encode()
    return int.from_bytes(hashlib.blake2b(payload, digest_size=8).digest())


def _assets(paths: RunPaths) -> tuple[list[Asset], dict[int, Asset]]:
    raw = read_json(paths.raw / "items.json")
    by_class = {str(item["class_name"]): int(item["id"]) for item in raw}
    slots = {
        name: index
        for index, name in enumerate(
            sorted({str(item.get("item_slot_type") or "unknown") for item in raw})
        )
    }
    ordered = sorted(raw, key=lambda item: int(item["id"]))
    assets = [
        Asset(
            item_id=int(item["id"]),
            index=index,
            name=str(item.get("name") or item["id"]),
            tier=int(item["item_tier"]),
            cost=int(item.get("cost") or 0),
            slot=str(item.get("item_slot_type") or "unknown"),
            slot_index=slots[str(item.get("item_slot_type") or "unknown")],
            active=bool(item.get("is_active_item")),
            unique=bool(item.get("is_unique")),
            components=tuple(
                by_class[value]
                for value in item.get("component_items") or []
                if value in by_class
            ),
        )
        for index, item in enumerate(ordered)
    ]
    return assets, {asset.item_id: asset for asset in assets}


def _owned_summary(owned: tuple[int, ...], by_id: dict[int, Asset]) -> tuple[int, ...]:
    slots = Counter(by_id[item_id].slot for item_id in owned)
    return (
        len(owned),
        slots["weapon"],
        slots["vitality"],
        slots["spirit"],
        sum(by_id[item_id].active for item_id in owned),
    )


def _component_credit(
    asset: Asset, owned: tuple[int, ...], by_id: dict[int, Asset]
) -> int:
    return sum(by_id[item_id].cost for item_id in asset.components if item_id in owned)


def _apply_purchase(item_id: int, owned: set[int], by_id: dict[int, Asset]) -> int:
    asset = by_id[item_id]
    credit = 0
    for component in asset.components:
        if component in owned:
            owned.remove(component)
            credit += by_id[component].cost
    owned.add(item_id)
    return max(0, asset.cost - credit)


def load_hero_queries(
    con: duckdb.DuckDBPyConnection,
    hero_id: int,
    by_id: dict[int, Asset],
) -> tuple[list[PurchaseQuery], list[InventoryObservation]]:
    frame = con.sql(
        f"""
        SELECT match_id, player_slot, fold, average_badge, calibration,
               duration_s, item_id, buy_time, sold_time,
               own_net_worth_at_buy, team_net_worth_lead
        FROM first_purchases WHERE hero_id = {hero_id}
        ORDER BY match_id, player_slot, buy_time, item_id
        """
    ).pl()
    queries: list[PurchaseQuery] = []
    inventories: list[InventoryObservation] = []
    current_key: tuple[int, int] | None = None
    owned: set[int] = set()
    sale_times: dict[int, int] = {}
    first_item = START_ITEM
    previous_item = START_ITEM
    prior_spend = 0
    current_time = 0
    current_nw: float | None = None
    current_lead: float | None = None
    position = 0
    last_fold = ""
    last_duration = 0

    def finish_inventory() -> None:
        if current_key is None:
            return
        for owned_id, sale_time in tuple(sale_times.items()):
            if 0 < sale_time <= last_duration:
                owned.discard(owned_id)
        inventories.append(InventoryObservation(last_fold, frozenset(owned)))

    for row in frame.iter_rows(named=True):
        key = (int(row["match_id"]), int(row["player_slot"]))
        if key != current_key:
            finish_inventory()
            current_key = key
            owned = set()
            sale_times = {}
            first_item = START_ITEM
            previous_item = START_ITEM
            prior_spend = 0
            current_time = 0
            current_nw = None
            current_lead = None
            position = 0
        target_time = int(row["buy_time"])
        for owned_id, sale_time in tuple(sale_times.items()):
            if 0 < sale_time <= target_time:
                owned.discard(owned_id)
                sale_times.pop(owned_id, None)
        target = int(row["item_id"])
        queries.append(
            PurchaseQuery(
                match_id=key[0],
                player_slot=key[1],
                fold=str(row["fold"]),
                position=position,
                phase=_phase(current_time),
                first_item=first_item,
                previous_item=previous_item,
                current_time_s=current_time,
                prior_spend=prior_spend,
                own_net_worth=current_nw,
                team_lead=current_lead,
                average_badge=int(row["average_badge"]),
                calibration=bool(row["calibration"]),
                owned=tuple(sorted(owned)),
                target=target,
                target_buy_time_s=target_time,
                component_upgrade=(
                    previous_item != START_ITEM
                    and previous_item in by_id[target].components
                ),
            )
        )
        prior_spend += _apply_purchase(target, owned, by_id)
        sale_times[target] = int(row["sold_time"])
        first_item = target if first_item == START_ITEM else first_item
        previous_item = target
        current_time = target_time
        current_nw = (
            float(row["own_net_worth_at_buy"])
            if row["own_net_worth_at_buy"] is not None
            else None
        )
        current_lead = (
            float(row["team_net_worth_lead"])
            if row["team_net_worth_lead"] is not None
            else None
        )
        position += 1
        last_fold = str(row["fold"])
        last_duration = int(row["duration_s"])
    finish_inventory()
    return queries, inventories


def sample_queries(
    queries: list[PurchaseQuery], fold: str, limit: int
) -> list[PurchaseQuery]:
    eligible = [query for query in queries if query.fold == fold]
    if len(eligible) <= limit:
        return eligible
    strata: dict[tuple[int, int], list[PurchaseQuery]] = defaultdict(list)
    for query in eligible:
        strata[query.phase, min(query.position // 3, 5)].append(query)
    selected: list[PurchaseQuery] = []
    per_stratum = max(1, limit // len(strata))
    leftovers: list[PurchaseQuery] = []
    for key in sorted(strata):
        ordered = sorted(
            strata[key],
            key=lambda query: _stable_hash(
                query.match_id, query.player_slot, query.position, SEED
            ),
        )
        selected.extend(ordered[:per_stratum])
        leftovers.extend(ordered[per_stratum:])
    remaining = limit - len(selected)
    if remaining > 0:
        selected.extend(
            sorted(
                leftovers,
                key=lambda query: _stable_hash(
                    query.match_id, query.player_slot, query.position, SEED
                ),
            )[:remaining]
        )
    return sorted(
        selected[:limit],
        key=lambda query: (query.match_id, query.player_slot, query.position),
    )


def legal_candidates(
    query: PurchaseQuery, assets: list[Asset], by_id: dict[int, Asset]
) -> list[int]:
    owned = set(query.owned)
    active_count = sum(by_id[item_id].active for item_id in owned)
    candidates = [
        asset.item_id
        for asset in assets
        if asset.item_id not in owned
        and (not asset.active or active_count < MAX_ACTIVE_ITEMS)
    ]
    if query.target not in candidates:
        candidates.append(query.target)
    return sorted(set(candidates))


def feature_row(
    query: PurchaseQuery,
    candidate: int,
    *,
    baseline: BaselineCounts,
    by_id: dict[int, Asset],
    start_index: int,
) -> list[float]:
    asset = by_id[candidate]
    first_index = (
        start_index if query.first_item == START_ITEM else by_id[query.first_item].index
    )
    previous_index = (
        start_index
        if query.previous_item == START_ITEM
        else by_id[query.previous_item].index
    )
    owned_summary = _owned_summary(query.owned, by_id)
    credit = _component_credit(asset, query.owned, by_id)
    baseline_scores = baseline.feature_scores(query, candidate)
    return [
        float(first_index),
        float(previous_index),
        float(query.position),
        float(query.phase),
        float(query.current_time_s),
        float(query.prior_spend),
        float(query.own_net_worth) if query.own_net_worth is not None else np.nan,
        float(query.own_net_worth is None),
        float(query.team_lead) if query.team_lead is not None else np.nan,
        float(query.team_lead is None),
        float(query.average_badge // 10),
        float(query.calibration),
        *(float(value) for value in owned_summary),
        float(asset.index),
        float(asset.tier),
        float(asset.cost),
        float(asset.slot_index),
        float(asset.active),
        float(asset.unique),
        float(credit),
        float(max(0, asset.cost - credit)),
        float(sum(component in query.owned for component in asset.components)),
        float(query.previous_item in asset.components),
        *baseline_scores,
    ]


def sampled_candidates(
    query: PurchaseQuery,
    *,
    baseline: BaselineCounts,
    assets: list[Asset],
    by_id: dict[int, Asset],
    count: int = TRAIN_CANDIDATES,
) -> list[int]:
    legal = legal_candidates(query, assets, by_id)
    if len(legal) <= count:
        return legal
    target = query.target
    remaining = [candidate for candidate in legal if candidate != target]
    hard = sorted(
        remaining,
        key=lambda candidate: (
            baseline.rank_score(query, candidate),
            -by_id[candidate].index,
        ),
        reverse=True,
    )[:16]
    chosen = {target, *hard}
    mechanical = sorted(
        (
            candidate
            for candidate in remaining
            if candidate not in chosen
            and (
                by_id[candidate].components
                or by_id[candidate].slot
                == (
                    by_id[query.previous_item].slot
                    if query.previous_item != START_ITEM
                    else by_id[candidate].slot
                )
            )
        ),
        key=lambda candidate: (
            -_component_credit(by_id[candidate], query.owned, by_id),
            -baseline.rank_score(query, candidate)[1],
            by_id[candidate].index,
        ),
    )[:8]
    chosen.update(mechanical)
    uniform = sorted(
        (candidate for candidate in remaining if candidate not in chosen),
        key=lambda candidate: _stable_hash(
            query.match_id,
            query.player_slot,
            query.position,
            candidate,
            SEED,
        ),
    )
    chosen.update(uniform[: max(0, count - len(chosen))])
    return sorted(chosen, key=lambda candidate: by_id[candidate].index)


def build_matrix(
    queries: list[PurchaseQuery],
    *,
    baseline: BaselineCounts,
    assets: list[Asset],
    by_id: dict[int, Asset],
    sampled: bool,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[list[int]]]:
    rows: list[list[float]] = []
    labels: list[int] = []
    qids: list[int] = []
    groups: list[list[int]] = []
    start_index = len(assets)
    for qid, query in enumerate(queries):
        candidates = (
            sampled_candidates(query, baseline=baseline, assets=assets, by_id=by_id)
            if sampled
            else legal_candidates(query, assets, by_id)
        )
        groups.append(candidates)
        for candidate in candidates:
            rows.append(
                feature_row(
                    query,
                    candidate,
                    baseline=baseline,
                    by_id=by_id,
                    start_index=start_index,
                )
            )
            labels.append(int(candidate == query.target))
            qids.append(qid)
    return (
        np.asarray(rows, dtype=np.float32),
        np.asarray(labels, dtype=np.float32),
        np.asarray(qids, dtype=np.uint32),
        groups,
    )


def _resolve_device(requested: str) -> str:
    if requested not in {"auto", "cpu", "cuda"}:
        raise ValueError("XGBoost device must be auto, cpu, or cuda")
    if requested == "cpu":
        return "cpu"
    if not bool(xgb.build_info().get("USE_CUDA")):
        if requested == "cuda":
            raise RuntimeError("installed XGBoost package has no CUDA support")
        return "cpu"
    matrix = xgb.DMatrix(
        np.asarray([[0.0], [1.0]], dtype=np.float32),
        label=np.asarray([0.0, 1.0], dtype=np.float32),
    )
    try:
        xgb.train(
            {"device": "cuda", "tree_method": "hist", "verbosity": 0},
            matrix,
            num_boost_round=1,
        )
    except xgb.core.XGBoostError as error:
        if requested == "cuda":
            raise RuntimeError("XGBoost could not initialize a CUDA device") from error
        return "cpu"
    return "cuda"


def _model(spec: ModelSpec, *, device: str) -> Any:
    parameters: dict[str, Any] = {
        "objective": spec.objective,
        "tree_method": "hist",
        "device": device,
        "n_estimators": 400,
        "learning_rate": 0.05,
        "max_depth": spec.max_depth,
        "min_child_weight": 20,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "reg_lambda": 2.0,
        "max_bin": 256,
        "random_state": SEED,
        "n_jobs": 12,
        "eval_metric": "ndcg@5",
        "early_stopping_rounds": 30,
        "enable_categorical": True,
        "feature_types": list(FEATURE_TYPES),
    }
    if spec.objective == "rank:ndcg":
        parameters.update(
            lambdarank_pair_method="topk",
            lambdarank_num_pair_per_sample=16,
        )
    return XGBRanker(**parameters)


def fit_model(
    train: list[PurchaseQuery],
    validation: list[PurchaseQuery],
    *,
    spec: ModelSpec,
    baseline: BaselineCounts,
    assets: list[Asset],
    by_id: dict[int, Asset],
    device: str = "cpu",
) -> Any:
    x_train, y_train, qid_train, _ = build_matrix(
        train, baseline=baseline, assets=assets, by_id=by_id, sampled=True
    )
    x_validation, y_validation, qid_validation, _ = build_matrix(
        validation, baseline=baseline, assets=assets, by_id=by_id, sampled=True
    )
    model = _model(spec, device=device)
    model.fit(
        x_train,
        y_train,
        qid=qid_train,
        eval_set=[(x_validation, y_validation)],
        eval_qid=[qid_validation],
        verbose=False,
    )
    del x_train, y_train, qid_train, x_validation, y_validation, qid_validation
    gc.collect()
    return model


def _rank(
    target: int, candidates: list[int], scores: np.ndarray, by_id: dict[int, Asset]
) -> int:
    ordered = sorted(
        zip(candidates, scores, strict=True),
        key=lambda pair: (-float(pair[1]), by_id[pair[0]].index),
    )
    return next(
        index for index, pair in enumerate(ordered, start=1) if pair[0] == target
    )


def evaluate_model(
    model: Any,
    queries: list[PurchaseQuery],
    *,
    baseline: BaselineCounts,
    assets: list[Asset],
    by_id: dict[int, Asset],
    batch_queries: int,
) -> list[RankRecord]:
    result: list[RankRecord] = []
    for offset in range(0, len(queries), batch_queries):
        batch = queries[offset : offset + batch_queries]
        matrix, _, _, groups = build_matrix(
            batch, baseline=baseline, assets=assets, by_id=by_id, sampled=False
        )
        predictions = model.predict(matrix)
        cursor = 0
        for query, candidates in zip(batch, groups, strict=True):
            size = len(candidates)
            model_scores = predictions[cursor : cursor + size]
            baseline_scores = np.asarray([
                baseline.rank_score(query, candidate)[0] * 100
                + baseline.rank_score(query, candidate)[1]
                for candidate in candidates
            ])
            result.append(
                RankRecord(
                    match_id=query.match_id,
                    target=query.target,
                    previous=query.previous_item,
                    component_upgrade=query.component_upgrade,
                    baseline_rank=_rank(
                        query.target, candidates, baseline_scores, by_id
                    ),
                    xgb_rank=_rank(query.target, candidates, model_scores, by_id),
                )
            )
            cursor += size
        del matrix, predictions
    return result


def _metrics(ranks: np.ndarray) -> dict[str, float]:
    if ranks.size == 0:
        return dict.fromkeys(
            ("top1", "top3", "top5", "mrr", "ndcg1", "ndcg3", "ndcg5"), 0.0
        )
    reciprocal = 1.0 / ranks
    discount = 1.0 / np.log2(ranks + 1)
    return {
        "top1": float(np.mean(ranks <= 1)),
        "top3": float(np.mean(ranks <= 3)),
        "top5": float(np.mean(ranks <= 5)),
        "mrr": float(np.mean(reciprocal)),
        "ndcg1": float(np.mean(np.where(ranks <= 1, discount, 0.0))),
        "ndcg3": float(np.mean(np.where(ranks <= 3, discount, 0.0))),
        "ndcg5": float(np.mean(np.where(ranks <= 5, discount, 0.0))),
    }


def metric_rows(
    hero_id: int, fold: str, records: list[RankRecord]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for subset, selected in (
        ("all", records),
        (
            "non_component",
            [record for record in records if not record.component_upgrade],
        ),
    ):
        for model_name, field in (
            ("baseline", "baseline_rank"),
            ("xgboost", "xgb_rank"),
        ):
            ranks = np.asarray(
                [getattr(record, field) for record in selected], dtype=float
            )
            rows.append({
                "hero_id": hero_id,
                "fold": fold,
                "subset": subset,
                "model": model_name,
                "queries": len(selected),
                "target_coverage": 1.0,
                **_metrics(ranks),
            })
    return rows


def _bootstrap_interval(records: list[RankRecord], replicates: int) -> dict[str, float]:
    grouped: dict[int, list[RankRecord]] = defaultdict(list)
    for record in records:
        if not record.component_upgrade:
            grouped[record.match_id].append(record)
    match_deltas = np.asarray(
        [
            np.mean([
                1 / record.xgb_rank - 1 / record.baseline_rank for record in values
            ])
            for values in grouped.values()
        ],
        dtype=float,
    )
    if match_deltas.size == 0:
        return {"mrr_delta": 0.0, "lower": 0.0, "upper": 0.0}
    rng = np.random.default_rng(SEED)
    estimates = np.asarray([
        float(np.mean(rng.choice(match_deltas, size=match_deltas.size, replace=True)))
        for _ in range(replicates)
    ])
    return {
        "mrr_delta": float(np.mean(match_deltas)),
        "lower": float(np.quantile(estimates, 0.025)),
        "upper": float(np.quantile(estimates, 0.975)),
    }


def _top_core_sets(
    inventories: list[InventoryObservation], fold: str, limit: int
) -> list[tuple[frozenset[int], int]]:
    counts: Counter[tuple[int, ...]] = Counter()
    for observation in inventories:
        if observation.fold != fold or len(observation.items) < 8:
            continue
        counts.update(combinations(sorted(observation.items), 8))
    return [(frozenset(items), count) for items, count in counts.most_common(limit)]


def _set_support(
    candidate: frozenset[int], inventories: list[InventoryObservation], fold: str
) -> int:
    return sum(
        candidate.issubset(observation.items)
        for observation in inventories
        if observation.fold == fold
    )


def _set_rank_score(candidate: frozenset[int], records: list[RankRecord]) -> float:
    selected = [1 / record.xgb_rank for record in records if record.target in candidate]
    return float(np.mean(selected)) if selected else 0.0


def _expand_component_path(
    ordered_core: list[int], by_id: dict[int, Asset]
) -> tuple[list[dict[str, Any]], int]:
    owned: set[int] = set()
    actions: list[dict[str, Any]] = []
    cumulative = 0

    def purchase(item_id: int) -> None:
        nonlocal cumulative
        if item_id in owned:
            return
        asset = by_id[item_id]
        for component in asset.components:
            purchase(component)
        incremental = _apply_purchase(item_id, owned, by_id)
        cumulative += incremental
        actions.append({
            "item_id": item_id,
            "item": asset.name,
            "tier": asset.tier,
            "incremental_souls": incremental,
            "cumulative_souls": cumulative,
        })

    for item_id in ordered_core:
        purchase(item_id)
    if owned != set(ordered_core):
        raise RuntimeError("expanded component path does not end in the core inventory")
    return actions, cumulative


def compare_cores(
    hero_id: int,
    queries: list[PurchaseQuery],
    inventories: list[InventoryObservation],
    validation_records: list[RankRecord],
    test_records: list[RankRecord],
    by_id: dict[int, Asset],
    typical_budget: int,
) -> dict[str, Any]:
    candidates = _top_core_sets(inventories, "train", CORE_CANDIDATES)
    if not candidates:
        return {
            "hero_id": hero_id,
            "status": "abstained",
            "reason": "no eight-item train inventory",
        }
    deterministic, deterministic_train = candidates[0]
    deterministic_validation = _set_support(deterministic, inventories, "validation")
    minimum_validation = max(20, math.floor(deterministic_validation * 0.75))
    eligible: list[tuple[float, int, frozenset[int], int]] = []
    for candidate, train_support in candidates:
        validation_support = _set_support(candidate, inventories, "validation")
        if (
            validation_support < minimum_validation
            or sum(by_id[item_id].cost for item_id in candidate) > typical_budget
        ):
            continue
        eligible.append((
            _set_rank_score(candidate, validation_records),
            validation_support,
            candidate,
            train_support,
        ))
    selected = (
        max(
            eligible,
            key=lambda value: (value[0], value[1], tuple(sorted(value[2]))),
        )[2]
        if eligible
        else deterministic
    )
    time_by_item: dict[int, list[int]] = defaultdict(list)
    for query in queries:
        if query.fold == "train":
            time_by_item[query.target].append(query.target_buy_time_s)

    def core_payload(candidate: frozenset[int], train_support: int) -> dict[str, Any]:
        ordered = sorted(
            candidate,
            key=lambda item_id: (
                float(np.median(time_by_item[item_id]))
                if time_by_item[item_id]
                else float("inf"),
                item_id,
            ),
        )
        actions, cost = _expand_component_path(ordered, by_id)
        return {
            "item_ids": ordered,
            "items": [by_id[item_id].name for item_id in ordered],
            "final_item_value": sum(by_id[item_id].cost for item_id in candidate),
            "component_path_cost": cost,
            "train_joint_support": train_support,
            "validation_joint_support": _set_support(
                candidate, inventories, "validation"
            ),
            "test_joint_support": _set_support(candidate, inventories, "test"),
            "validation_xgb_sequence_mrr": _set_rank_score(
                candidate, validation_records
            ),
            "test_xgb_sequence_mrr": _set_rank_score(candidate, test_records),
            "purchase_path": actions,
        }

    selected_train = next(
        (support for candidate, support in candidates if candidate == selected), 0
    )
    return {
        "hero_id": hero_id,
        "status": "ok",
        "changed": selected != deterministic,
        "typical_final_net_worth": typical_budget,
        "deterministic": core_payload(deterministic, deterministic_train),
        "xgboost": core_payload(selected, selected_train),
    }


def _pilot_heroes(con: duckdb.DuckDBPyConnection) -> list[int]:
    rows = con.execute(
        "SELECT hero_id, count(*) AS n FROM first_purchases GROUP BY hero_id ORDER BY n, hero_id"
    ).fetchall()
    ordered = [int(row[0]) for row in rows]
    selected = {12, 13}
    selected.update(
        ordered[round((len(ordered) - 1) * quantile)] for quantile in (0.25, 0.5, 0.75)
    )
    return sorted(selected)


def _aggregate_metric(
    rows: list[dict[str, Any]], model: str, subset: str, name: str
) -> float:
    selected = [
        row for row in rows if row["model"] == model and row["subset"] == subset
    ]
    total = sum(int(row["queries"]) for row in selected)
    return (
        sum(float(row[name]) * int(row["queries"]) for row in selected) / total
        if total
        else 0.0
    )


def _weighted_summary(metric_frame: pl.DataFrame, fold: str) -> list[dict[str, Any]]:
    selected_frame = metric_frame.filter(pl.col("fold") == fold)
    rows: list[dict[str, Any]] = []
    for subset in ("all", "non_component"):
        for model in ("baseline", "xgboost"):
            selected = selected_frame.filter(
                (pl.col("subset") == subset) & (pl.col("model") == model)
            )
            weights = selected["queries"].to_numpy()
            rows.append({
                "subset": subset,
                "model": model,
                "queries": int(weights.sum()),
                **{
                    metric: float(
                        np.average(selected[metric].to_numpy(), weights=weights)
                    )
                    for metric in ("top1", "top3", "top5", "mrr", "ndcg5")
                },
            })
    return rows


def _gate(metric_frame: pl.DataFrame, bootstrap: dict[str, float]) -> dict[str, Any]:
    summary = _weighted_summary(metric_frame, "test")
    non_component_mrr_delta = _aggregate_metric(
        summary, "xgboost", "non_component", "mrr"
    ) - _aggregate_metric(summary, "baseline", "non_component", "mrr")
    non_component_ndcg5_delta = _aggregate_metric(
        summary, "xgboost", "non_component", "ndcg5"
    ) - _aggregate_metric(summary, "baseline", "non_component", "ndcg5")
    non_component_top5_delta = _aggregate_metric(
        summary, "xgboost", "non_component", "top5"
    ) - _aggregate_metric(summary, "baseline", "non_component", "top5")
    all_mrr_delta = _aggregate_metric(
        summary, "xgboost", "all", "mrr"
    ) - _aggregate_metric(summary, "baseline", "all", "mrr")
    hero_rows = metric_frame.filter(
        (pl.col("fold") == "test") & (pl.col("subset") == "non_component")
    )
    baseline_by_hero = {
        int(row["hero_id"]): float(row["mrr"])
        for row in hero_rows.filter(pl.col("model") == "baseline").iter_rows(named=True)
    }
    xgb_by_hero = {
        int(row["hero_id"]): float(row["mrr"])
        for row in hero_rows.filter(pl.col("model") == "xgboost").iter_rows(named=True)
    }
    worst_hero_delta = min(
        (
            xgb_by_hero[hero_id] - baseline
            for hero_id, baseline in baseline_by_hero.items()
        ),
        default=0.0,
    )
    passed = (
        non_component_mrr_delta >= 0.01
        and bootstrap["lower"] > 0
        and non_component_ndcg5_delta >= 0.01
        and non_component_top5_delta >= 0
        and all_mrr_delta >= -0.005
        and worst_hero_delta >= -0.02
    )
    return {
        "passed": passed,
        "non_component_mrr_delta": non_component_mrr_delta,
        "non_component_ndcg5_delta": non_component_ndcg5_delta,
        "non_component_top5_delta": non_component_top5_delta,
        "all_mrr_delta": all_mrr_delta,
        "worst_hero_mrr_delta": worst_hero_delta,
        "bootstrap_lower": bootstrap["lower"],
        "bootstrap_upper": bootstrap["upper"],
    }


def _markdown_metrics(rows: list[dict[str, Any]]) -> str:
    lines = [
        "| Subset | Model | Queries | Top-1 | Top-3 | Top-5 | MRR | NDCG@5 |",
        "|---|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['subset']} | {row['model']} | {int(row['queries']):,} | "
            f"{row['top1']:.3f} | {row['top3']:.3f} | {row['top5']:.3f} | "
            f"{row['mrr']:.3f} | {row['ndcg5']:.3f} |"
        )
    return "\n".join(lines)


def _item_window(row: dict[str, Any]) -> str:
    median = row.get("median_valid_buy_net_worth")
    window = (
        f"{float(median) / 1000:.1f}k NW" if median is not None else "NW unavailable"
    )
    return f"{row['item_name']} <br><sub>{float(row['adoption_rate']):.1%} · {window}</sub>"


def _preview_rows(
    core: dict[str, Any], hero_items: pl.DataFrame
) -> list[tuple[str, list[str]]]:
    core_ids = {int(item_id) for item_id in core["item_ids"]}
    names_by_id = {
        int(row["item_id"]): str(row["item_name"])
        for row in hero_items.iter_rows(named=True)
    }
    rows: list[tuple[str, list[str]]] = [
        (
            "CORE ITEMS",
            [
                f"**{names_by_id.get(int(item_id), str(item_id))}**"
                for item_id in core["item_ids"]
            ],
        )
    ]
    for tier in range(1, 5):
        shortlist = (
            hero_items
            .filter(pl.col("tier") == tier)
            .sort(
                ["adoption_rate", "adopter_matches", "item_id"],
                descending=[True, True, False],
            )
            .head(8)
            .sort(
                [
                    "median_valid_buy_net_worth",
                    "median_buy_time_s",
                    "item_id",
                ],
                nulls_last=True,
            )
        )
        if shortlist.height != 8:
            raise RuntimeError(
                f"hero preview has {shortlist.height} tier-{tier} items; 8 required"
            )
        items = []
        for item_row in shortlist.iter_rows(named=True):
            label = _item_window(item_row)
            if int(item_row["item_id"]) in core_ids:
                label = f"**{label}**"
            items.append(label)
        rows.append((f"TIER {tier}", items))
    return rows


def _render_preview_table(core: dict[str, Any], hero_items: pl.DataFrame) -> str:
    lines = ["| Row | Items, left to right |", "|---|---|"]
    for name, items in _preview_rows(core, hero_items):
        lines.append(f"| **{name}** | {' → '.join(items)} |")
    return "\n".join(lines)


def _render_build_previews(
    cores: list[dict[str, Any]],
    hero_names: dict[int, str],
    item_metrics: pl.DataFrame,
) -> str:
    sections = []
    for core in sorted(cores, key=lambda value: hero_names.get(value["hero_id"], "")):
        if core.get("status") != "ok":
            continue
        hero_id = int(core["hero_id"])
        hero_items = item_metrics.filter(pl.col("hero_id") == hero_id)
        sections.append(
            f"## {hero_names.get(hero_id, str(hero_id))}\n\n"
            f"- Typical final net worth: **{int(core['typical_final_net_worth']):,} souls**\n"
            f"- XGBoost changed the core: **{str(core['changed']).lower()}**\n\n"
            "### Deterministic baseline\n\n"
            f"{_render_preview_table(core['deterministic'], hero_items)}\n\n"
            "### XGBoost challenger\n\n"
            f"{_render_preview_table(core['xgboost'], hero_items)}"
        )
    return """---
title: "Deterministic and XGBoost five-row build previews"
---

# Five-row build previews

> [!IMPORTANT]
> These are review artifacts, not production builds. Each core is a coherent
> eight-item final inventory. Tier menus contain the eight most-adopted items in
> that tier and are ordered left-to-right by valid pre-purchase net worth.

The percentage under each tier item is player-match purchase adoption. Bold tier
items also appear in that preview's core. Observed outcomes are intentionally not a
selection or ordering signal.

""" + "\n\n".join(sections)


def _render_report(
    *,
    selected_spec: ModelSpec,
    pilot_rows: list[dict[str, Any]],
    metric_frame: pl.DataFrame,
    bootstrap: dict[str, float],
    cores: list[dict[str, Any]],
    hero_names: dict[int, str],
    config: ExperimentConfig,
) -> str:
    summary_rows = _weighted_summary(metric_frame, "test")
    changed = [core for core in cores if core.get("changed")]
    detail_lines = []
    for hero_id in (12, 13):
        core = next((value for value in cores if value["hero_id"] == hero_id), None)
        if core is None or core.get("status") != "ok":
            continue
        detail_lines.append(
            f"### {hero_names.get(hero_id, str(hero_id))}\n\n"
            f"- Deterministic: {' → '.join(core['deterministic']['items'])} ({core['deterministic']['component_path_cost']:,} souls)\n"
            f"- XGBoost candidate: {' → '.join(core['xgboost']['items'])} ({core['xgboost']['component_path_cost']:,} souls)\n"
            f"- Changed: **{str(core['changed']).lower()}**\n"
            f"- Held-out joint support: {core['deterministic']['test_joint_support']} deterministic vs {core['xgboost']['test_joint_support']} XGBoost"
        )
    gate = _gate(metric_frame, bootstrap)
    pass_gate = bool(gate["passed"])
    return f"""---
title: "XGBoost next-item challenger"
status: "{"passed" if pass_gate else "did-not-pass"}"
selected_model: "{selected_spec.name}"
---

# XGBoost next-item challenger

> [!IMPORTANT]
> This experiment does not authorize production integration. It compares a contextual
> ranker with the deterministic sequence baseline on chronological held-out matches.

## Verdict

**{"PASS" if pass_gate else "DOES NOT PASS"}** the predeclared aggregate gate.

- Non-component paired MRR delta: **{bootstrap["mrr_delta"]:+.4f}**
- Match-bootstrap 95% interval: **[{bootstrap["lower"]:+.4f}, {bootstrap["upper"]:+.4f}]**
- Non-component NDCG@5 delta: **{gate["non_component_ndcg5_delta"]:+.4f}**
- Worst per-hero MRR delta: **{gate["worst_hero_mrr_delta"]:+.4f}**
- Heroes with a changed eight-item candidate: **{len(changed)} / {len(cores)}**
- Selected pilot configuration: `{selected_spec.name}`

## Chronological test metrics

{_markdown_metrics(summary_rows)}

## Kelvin and Haze candidates

{chr(10).join(detail_lines)}

## Method

- One query per first acquisition, using only the state available after the preceding
  purchase; START queries contain explicit missing state.
- Up to {config.train_queries:,} train, {config.validation_queries:,} validation, and
  {config.test_queries:,} test queries per hero.
- Thirty-two train candidates per query; full legal shop catalog during held-out scoring.
- Candidate cores are restricted to the 64 most-supported coherent train itemsets.
- Challenger cores must fit below the hero's median final net worth and retain at
  least 75% of the deterministic core's validation joint support.
- No outcome, duration, final net worth, target timing, or future purchase feature enters
  the model.

## Pilot selection

```json
{json.dumps(pilot_rows, indent=2)}
```

## Artifacts

- [`xgb_metrics.csv`](xgb_metrics.csv)
- [`xgb_core_comparison.json`](xgb_core_comparison.json)
- [`xgb_build_previews.md`](xgb_build_previews.md)
- [`xgb_feature_importance.csv`](xgb_feature_importance.csv)
- [`xgb_experiment_manifest.json`](xgb_experiment_manifest.json)
"""


def run_xgboost_experiment(
    paths: RunPaths, config: ExperimentConfig | None = None
) -> dict[str, Any]:
    config = config or ExperimentConfig()
    device = _resolve_device(config.device)
    print(f"XGBoost device: {device}", flush=True)
    output = paths.run / "xgboost"
    output.mkdir(parents=True, exist_ok=True)
    assets, by_id = _assets(paths)
    hero_names = {
        int(hero["id"]): str(hero.get("name") or hero["id"])
        for hero in read_json(paths.raw / "heroes.json")
    }
    con = duckdb.connect(str(paths.raw / "analysis.duckdb"), read_only=True)
    try:
        hero_ids = [
            int(row[0])
            for row in con.execute(
                "SELECT DISTINCT hero_id FROM first_purchases ORDER BY hero_id"
            ).fetchall()
        ]
        pilots = _pilot_heroes(con)
        pilot_scores: dict[str, list[float]] = defaultdict(list)
        pilot_rows: list[dict[str, Any]] = []
        for hero_id in pilots:
            print(f"XGBoost pilot: {hero_names.get(hero_id, hero_id)}", flush=True)
            queries, _ = load_hero_queries(con, hero_id, by_id)
            baseline = BaselineCounts.fit(queries, len(assets))
            train = sample_queries(queries, "train", config.pilot_train_queries)
            validation = sample_queries(
                queries, "validation", config.pilot_validation_queries
            )
            for spec in MODEL_SPECS:
                model = fit_model(
                    train,
                    validation,
                    spec=spec,
                    baseline=baseline,
                    assets=assets,
                    by_id=by_id,
                    device=device,
                )
                records = evaluate_model(
                    model,
                    validation,
                    baseline=baseline,
                    assets=assets,
                    by_id=by_id,
                    batch_queries=config.evaluation_batch_queries,
                )
                non_component = [
                    record for record in records if not record.component_upgrade
                ]
                score = _metrics(
                    np.asarray([record.xgb_rank for record in non_component])
                )["mrr"]
                pilot_scores[spec.name].append(score)
                pilot_rows.append({
                    "hero_id": hero_id,
                    "model": spec.name,
                    "non_component_mrr": score,
                })
                del model, records
                gc.collect()
        selected_spec = max(
            MODEL_SPECS,
            key=lambda spec: (
                float(np.mean(pilot_scores[spec.name])),
                -spec.max_depth,
                spec.name,
            ),
        )
        model_run_key = (
            f"{selected_spec.name}-train-{config.train_queries}"
            f"-validation-{config.validation_queries}-test-{config.test_queries}"
        )
        models_dir = output / "models" / model_run_key
        models_dir.mkdir(parents=True, exist_ok=True)

        metrics: list[dict[str, Any]] = []
        cores: list[dict[str, Any]] = []
        feature_importance: list[dict[str, Any]] = []
        all_test_records: list[RankRecord] = []
        for index, hero_id in enumerate(hero_ids, start=1):
            print(
                f"XGBoost hero {index}/{len(hero_ids)}: {hero_names.get(hero_id, hero_id)}",
                flush=True,
            )
            queries, inventories = load_hero_queries(con, hero_id, by_id)
            baseline = BaselineCounts.fit(queries, len(assets))
            train = sample_queries(queries, "train", config.train_queries)
            validation = sample_queries(
                queries, "validation", config.validation_queries
            )
            test = sample_queries(queries, "test", config.test_queries)
            model = fit_model(
                train,
                validation,
                spec=selected_spec,
                baseline=baseline,
                assets=assets,
                by_id=by_id,
                device=device,
            )
            validation_records = evaluate_model(
                model,
                validation,
                baseline=baseline,
                assets=assets,
                by_id=by_id,
                batch_queries=config.evaluation_batch_queries,
            )
            test_records = evaluate_model(
                model,
                test,
                baseline=baseline,
                assets=assets,
                by_id=by_id,
                batch_queries=config.evaluation_batch_queries,
            )
            metrics.extend(metric_rows(hero_id, "validation", validation_records))
            metrics.extend(metric_rows(hero_id, "test", test_records))
            all_test_records.extend(test_records)
            typical_budget_result = con.execute(
                f"""
                SELECT median(final_net_worth)
                FROM player_matches
                WHERE hero_id = {hero_id}
                """
            ).fetchone()
            if typical_budget_result is None or typical_budget_result[0] is None:
                raise RuntimeError(f"hero {hero_id} has no final net-worth evidence")
            cores.append(
                compare_cores(
                    hero_id,
                    queries,
                    inventories,
                    validation_records,
                    test_records,
                    by_id,
                    int(typical_budget_result[0]),
                )
            )
            booster = model.get_booster()
            for feature, gain in booster.get_score(importance_type="gain").items():
                feature_name = feature
                if feature.startswith("f") and feature[1:].isdigit():
                    feature_name = FEATURE_NAMES[int(feature[1:])]
                feature_importance.append({
                    "hero_id": hero_id,
                    "feature": feature_name,
                    "gain": gain,
                })
            model_path = models_dir / f"hero_{hero_id}.json"
            model.save_model(model_path)
            del model, queries, inventories, validation_records, test_records
            gc.collect()
    finally:
        con.close()

    metric_frame = pl.DataFrame(metrics)
    metric_frame.write_csv(output / "xgb_metrics.csv")
    importance_frame = pl.DataFrame(feature_importance)
    if not importance_frame.is_empty():
        importance_frame.write_csv(output / "xgb_feature_importance.csv")
    else:
        (output / "xgb_feature_importance.csv").write_text(
            "hero_id,feature,gain\n", encoding="utf-8"
        )
    write_json(output / "xgb_core_comparison.json", cores)
    bootstrap = _bootstrap_interval(all_test_records, config.bootstrap_replicates)
    gate = _gate(metric_frame, bootstrap)
    item_metrics = pl.read_csv(paths.tables / "item_metrics.csv")
    (output / "xgb_build_previews.md").write_text(
        _render_build_previews(cores, hero_names, item_metrics), encoding="utf-8"
    )
    manifest = {
        "schema_version": 1,
        "seed": SEED,
        "config": asdict(config),
        "resolved_device": device,
        "selected_model": asdict(selected_spec),
        "pilot_heroes": pilots,
        "hero_count": len(hero_ids),
        "feature_names": list(FEATURE_NAMES),
        "feature_types": list(FEATURE_TYPES),
        "excluded_future_features": [
            "won",
            "duration_s",
            "final_net_worth",
            "target_buy_time",
            "future_items",
            "sold_time",
        ],
        "bootstrap": bootstrap,
        "promotion_gate": gate,
        "model_directory": str(models_dir),
        "source_database": str(paths.raw / "analysis.duckdb"),
        "producer_source_modified": False,
        "producer_source_unchanged": True,
    }
    manifest["experiment_sha256"] = sha256_json(manifest)
    write_json(output / "xgb_experiment_manifest.json", manifest)
    report = _render_report(
        selected_spec=selected_spec,
        pilot_rows=pilot_rows,
        metric_frame=metric_frame,
        bootstrap=bootstrap,
        cores=cores,
        hero_names=hero_names,
        config=config,
    )
    (output / "XGBOOST_REPORT.md").write_text(report, encoding="utf-8")
    return {
        "output": str(output),
        "selected_model": selected_spec.name,
        "hero_count": len(hero_ids),
        "device": device,
        "bootstrap": bootstrap,
        "pass_gate": bool(gate["passed"]),
        "report": str(output / "XGBOOST_REPORT.md"),
        "previews": str(output / "xgb_build_previews.md"),
        "models": str(models_dir),
    }
