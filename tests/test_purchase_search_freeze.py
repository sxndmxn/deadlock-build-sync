"""Check that test access requires unchanged experiment settings and code."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from tools.purchase_search import freeze


def test_test_access_rejects_missing_specification() -> None:
    with pytest.raises(ValueError, match="frozen experiment specification"):
        freeze.verify_frozen(None, "data")


def test_test_access_rejects_changed_code(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "frozen.json"
    path.write_text(
        json.dumps({
            "schema": 1,
            "data_fingerprint": "data",
            "code": {"a.py": "first"},
        }),
        encoding="utf-8",
    )
    monkeypatch.setattr(freeze, "code_identity", lambda: {"a.py": "second"})
    with pytest.raises(ValueError, match="code changed"):
        freeze.verify_frozen(path, "data")


def test_test_access_rejects_changed_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "frozen.json"
    path.write_text(
        json.dumps({"schema": 1, "data_fingerprint": "first", "code": {}}),
        encoding="utf-8",
    )
    monkeypatch.setattr(freeze, "code_identity", dict)
    with pytest.raises(ValueError, match="does not match"):
        freeze.verify_frozen(path, "second")
