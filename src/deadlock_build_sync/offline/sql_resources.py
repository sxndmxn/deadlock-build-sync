"""Load packaged SQL statements once per process."""

from functools import cache
from importlib.resources import files


@cache
def load_sql(name: str) -> str:
    """Read a SQL file from the offline analytics package."""
    return (
        files("deadlock_build_sync.offline")
        .joinpath("sql", name)
        .read_text(encoding="utf-8")
    )
