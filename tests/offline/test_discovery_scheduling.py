from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync.offline import discovery_export as producer
from deadlock_build_sync.offline.config import RunPaths
from deadlock_build_sync.offline.discovery_scheduling import (
    merge_validation_results,
    partition_validation_rows,
)
from tests.offline.production_evidence_fixtures import make_export_context

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.parametrize("workers", [1, 2, 8])
def test_partitions_cover_all_candidates_once_and_start_larger_batches_first(
    workers: int,
) -> None:
    weights = [[5, 19, 1, 6, 3], [], [2, 2], [91, 1, 1, 1]]
    batches = partition_validation_rows(weights, workers)
    for hero, rows in enumerate(weights):
        assert sorted(
            index
            for identifier, start, stop in batches
            if identifier == hero
            for index in range(start, stop)
        ) == list(range(len(rows)))
    costs = [sum(weights[hero][start:stop]) for hero, start, stop in batches]
    assert costs == sorted(costs, reverse=True)
    assert (1, 0, 0) in batches
    assert (len(batches) == len(weights)) is (workers == 1)
    assert partition_validation_rows([], workers) == []


def test_partition_rejects_invalid_worker_count() -> None:
    with pytest.raises(ValueError, match="at least 1"):
        partition_validation_rows([[1]], 0)


def test_batch_merge_preserves_all_rejections_without_changing_input_records() -> None:
    first: dict[str, object] = {
        "hero_id": 1,
        "builds": [],
        "path_abstentions": [{"path_id": "first"}],
        "exclusion": {"candidate_rejections": [{"path_id": "first"}]},
    }
    second: dict[str, object] = {
        **first,
        "path_abstentions": [{"path_id": "second"}],
    }
    merged = merge_validation_results([first, second])
    assert merged["path_abstentions"] == [{"path_id": "first"}, {"path_id": "second"}]
    assert merged["exclusion"] == {"candidate_rejections": merged["path_abstentions"]}
    assert first["exclusion"] == {"candidate_rejections": [{"path_id": "first"}]}
    without_rejections: dict[str, object] = {**first, "path_abstentions": []}
    assert (
        merge_validation_results([without_rejections] * 2)["exclusion"]
        == first["exclusion"]
    )


def test_scheduled_batches_keep_complete_family_and_restore_roster_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    context = make_export_context(RunPaths.create(tmp_path, "scheduled"))
    family = producer.ValidationFamily(10, 100, "frozen")
    jobs = [
        producer.HeroValidationJob(
            {"id": hero, "name": f"Hero {hero}"},
            context,
            {
                "rows": [{"branch_candidates": [{}] * 10} for _ in range(count)],
                "candidate_count": count,
                "candidates": [],
                "cohort": {},
                "grouping": {
                    "groups": [],
                    "seeds": [],
                    "edges": [],
                    "candidate_order": [],
                },
            },
            family,
            {},
        )
        for hero, count in ((1, 3), (2, 7))
    ]
    observed = []

    def validate(job: producer.HeroValidationJob) -> dict[str, object]:
        assert job.family is family
        assert len(job.report["rows"]) == (3 if job.hero["id"] == 1 else 7)
        observed.append(job.bounds)
        start, stop = job.bounds or (0, len(job.report["rows"]))
        return {
            "hero_id": job.hero["id"],
            "builds": [{"path_id": str(index)} for index in range(start, stop)],
            "path_abstentions": [],
            "exclusion": None,
        }

    monkeypatch.setattr(producer, "_run_validation_job", validate)
    monkeypatch.setattr(
        producer,
        "map_discovery_jobs",
        lambda operation, batches, _workers: [operation(batch) for batch in batches],
    )
    expected = producer.validate_hero_roster(jobs, 1)
    assert observed == [None, None]
    observed.clear()
    assert producer.validate_hero_roster(jobs, 4) == expected
    assert all(bounds is not None for bounds in observed)
