"""Distribute frozen candidate groups and restore their original result order."""

from deadlock_build_sync.value_validation import (
    require_object_dict,
    require_object_rows,
)


def partition_validation_rows(
    weights: list[list[int]], workers: int
) -> list[tuple[int, int, int]]:
    if workers < 1:
        raise ValueError("Worker count must be at least 1")
    target = max(1, sum(sum(rows) for rows in weights) // (workers * 4))
    batches = []
    for hero, rows in enumerate(weights):
        start, count = 0, 0
        for stop, weight in enumerate(rows):
            if workers > 1 and count and count + weight > target:
                batches.append((hero, start, stop))
                start, count = stop, 0
            count += weight
        batches.append((hero, start, len(rows)))
    return sorted(
        batches,
        key=lambda batch: -sum(weights[batch[0]][batch[1] : batch[2]]),
    )


def merge_validation_results(results: list[dict[str, object]]) -> dict[str, object]:
    merged = dict(results[0])
    if len(results) == 1:
        return merged
    builds = [
        build for result in results for build in require_object_rows(result["builds"])
    ]
    rejections = [
        rejection
        for result in results
        for rejection in require_object_rows(result["path_abstentions"])
    ]
    merged.update(builds=builds, path_abstentions=rejections)
    if builds:
        merged["exclusion"] = None
    else:
        exclusion = require_object_dict(merged["exclusion"])
        merged["exclusion"] = {
            **exclusion,
            "candidate_rejections": rejections or exclusion["candidate_rejections"],
        }
    return merged
