from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from deadlock_build_sync import artifacts
from deadlock_build_sync.artifacts import ArtifactError
from deadlock_build_sync.offline import production_storage as storage
from tests.build_evidence_fixtures import (
    make_evidence_document,
    refresh_evidence_fingerprints,
)

if TYPE_CHECKING:
    from pathlib import Path


def test_atomic_write_replaces_document_and_cleans_failed_temp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = tmp_path / "nested/document.json"
    storage._atomic_write(target, {"value": 1})
    assert json.loads(target.read_text(encoding="utf-8")) == {"value": 1}

    failed = tmp_path / "failed/document.json"
    monkeypatch.setattr(artifacts.os, "fsync", _fail_fsync)
    with pytest.raises(OSError, match="sync failed"):
        storage._atomic_write(failed, {"value": 2})
    assert not failed.exists()
    assert list(failed.parent.glob("*.tmp")) == []


def _fail_fsync(_descriptor: int) -> None:
    raise OSError("sync failed")


def test_invalid_replacement_evidence_preserves_current_artifact(
    tmp_path: Path,
) -> None:
    target = tmp_path / "build-evidence.json"
    document = make_evidence_document()
    storage.write_validated_evidence(target, document)
    previous = target.read_bytes()
    document["schema_version"] = 10
    refresh_evidence_fingerprints(document)
    with pytest.raises(ArtifactError, match="refresh-evidence"):
        storage.write_validated_evidence(target, document)
    assert target.read_bytes() == previous
    assert list(tmp_path.iterdir()) == [target]
