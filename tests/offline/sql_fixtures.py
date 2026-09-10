"""Load SQL fixtures for offline analytics tests."""

from functools import cache
from pathlib import Path


@cache
def load_fixture_sql(name: str) -> str:
    return (Path(__file__).with_name("sql") / name).read_text(encoding="utf-8")
