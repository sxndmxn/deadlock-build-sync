"""Run independent hero calculations in separate CPU processes."""

import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context


def _initialize_discovery_worker() -> None:
    os.environ.setdefault("POLARS_MAX_THREADS", "1")


def map_discovery_jobs[Job, Result](
    operation: Callable[[Job], Result], jobs: list[Job], workers: int
) -> list[Result]:
    if workers < 1:
        raise ValueError("Worker count must be at least 1")
    if workers == 1:
        return [operation(job) for job in jobs]
    executor = ProcessPoolExecutor(
        max_workers=workers,
        mp_context=get_context("spawn"),
        initializer=_initialize_discovery_worker,
    )
    try:
        return list(executor.map(operation, jobs))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
