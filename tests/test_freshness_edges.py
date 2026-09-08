from __future__ import annotations

import json
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from deadlock_build_sync import freshness as freshness_module
from deadlock_build_sync.api import Patch
from deadlock_build_sync.freshness import (
    FreshnessError,
    FreshnessReport,
    FreshnessStage,
    FreshnessState,
    require_current_build_evidence,
)

if TYPE_CHECKING:
    from pathlib import Path

    from deadlock_build_sync.build_evidence import BuildEvidenceCatalog


class _Api:
    @staticmethod
    def resolve_client_version() -> int:
        return 123

    @staticmethod
    def current_patch() -> Patch:
        return Patch("Patch", 100, "2026-01-01T00:00:00Z")


def _evidence(
    *,
    client_version: int = 123,
    patch_identity: str | None = None,
) -> BuildEvidenceCatalog:
    return cast(
        "BuildEvidenceCatalog",
        SimpleNamespace(
            client_version=client_version,
            patch={"identity": patch_identity or _Api.current_patch().identity},
            as_of_timestamp=500,
            artifact_id="artifact",
        ),
    )


def _context(
    *,
    snapshot_id: str = "snapshot",
    policy_id: str = "policy",
) -> dict[str, object]:
    return {
        "snapshot_manifest": {
            "snapshot_id": snapshot_id,
            "client_version": 123,
            "patch": {"identity": _Api.current_patch().identity},
            "as_of_timestamp": 500,
        },
        "heroes": [
            {
                "hero_id": 12,
                "path_id": "default",
                "policy_id": policy_id,
            }
        ],
    }


def _write(path: Path, value: object) -> None:
    path.write_text(json.dumps(value), encoding="utf-8")


def _raise_os_error(_path: Path) -> object:
    raise OSError("unavailable")


def _accept_document(_document: dict[str, object]) -> None:
    return None


def test_require_current_evidence_handles_load_and_patch_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freshness_module, "load_build_evidence", _raise_os_error)
    with pytest.raises(FreshnessError, match="unavailable"):
        require_current_build_evidence(tmp_path / "missing", _Api())

    stale = _evidence(patch_identity="Old@1")
    monkeypatch.setattr(freshness_module, "load_build_evidence", lambda _path: stale)
    with pytest.raises(FreshnessError, match="patch Old@1"):
        require_current_build_evidence(tmp_path / "stale", _Api())


def test_evidence_stage_reports_current_and_all_stale_differences(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "build-evidence.json"
    path.touch()
    monkeypatch.setattr(
        freshness_module,
        "load_build_evidence",
        lambda _path: _evidence(),
    )
    current, loaded = freshness_module._check_evidence_freshness(
        path, 123, _Api().current_patch()
    )
    assert current == FreshnessStage(
        "build_evidence", FreshnessState.CURRENT, "artifact"
    )
    assert loaded is not None

    monkeypatch.setattr(
        freshness_module,
        "load_build_evidence",
        lambda _path: _evidence(client_version=1, patch_identity="Old@1"),
    )
    stale, loaded = freshness_module._check_evidence_freshness(
        path, 123, _Api().current_patch()
    )
    assert stale == FreshnessStage(
        "build_evidence",
        FreshnessState.STALE,
        "client 1 != 123; patch identity differs",
    )
    assert loaded is not None


def test_context_stage_validates_shape_identity_and_manifest(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    path = tmp_path / "strategy-context.json"
    monkeypatch.setattr(
        freshness_module,
        "validate_strategy_context_document",
        _accept_document,
    )
    _write(path, _context())
    current, document = freshness_module._check_context_freshness(path, _evidence())
    assert current == FreshnessStage(
        "strategy_context", FreshnessState.CURRENT, "snapshot"
    )
    assert document is not None

    _write(path, {})
    malformed, document = freshness_module._check_context_freshness(path, _evidence())
    assert malformed == FreshnessStage(
        "strategy_context",
        FreshnessState.MALFORMED,
        "missing snapshot manifest",
    )
    assert document is None

    stale_document = _context()
    manifest = freshness_module.object_dict(stale_document["snapshot_manifest"])
    assert manifest is not None
    manifest["client_version"] = 1
    _write(path, stale_document)
    stale, document = freshness_module._check_context_freshness(path, _evidence())
    assert stale == FreshnessStage(
        "strategy_context",
        FreshnessState.STALE,
        "snapshot differs from build evidence",
    )
    assert document is not None

    _write(path, [])
    malformed, _ = freshness_module._check_context_freshness(path, _evidence())
    assert malformed == FreshnessStage(
        "strategy_context", FreshnessState.MALFORMED, "root must be an object"
    )


def test_policy_and_narrative_stages_cover_current_stale_and_malformed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_path = tmp_path / "policies.json"
    narrative_path = tmp_path / "narratives.json"
    context = _context()
    _write(policy_path, {"snapshot_manifest": context["snapshot_manifest"]})
    narrative_path.touch()
    monkeypatch.setattr(freshness_module, "validate_policy_artifact", _accept_document)
    monkeypatch.setattr(
        freshness_module,
        "load_narrative_catalog",
        lambda _path: SimpleNamespace(snapshot_id="snapshot"),
    )
    assert freshness_module._check_policy_freshness(
        policy_path, context
    ) == FreshnessStage("policies", FreshnessState.CURRENT, "validated")
    assert freshness_module._check_narrative_freshness(
        narrative_path, context
    ) == FreshnessStage("narratives", FreshnessState.CURRENT, "validated")

    other = _context(snapshot_id="other")
    assert freshness_module._check_policy_freshness(
        policy_path, other
    ) == FreshnessStage(
        "policies",
        FreshnessState.STALE,
        "snapshot differs from strategy context",
    )
    assert freshness_module._check_narrative_freshness(
        narrative_path, other
    ) == FreshnessStage(
        "narratives",
        FreshnessState.STALE,
        "snapshot differs from strategy context",
    )

    monkeypatch.setattr(freshness_module, "validate_policy_artifact", _raise_value)
    monkeypatch.setattr(freshness_module, "load_narrative_catalog", _raise_os_error)
    assert freshness_module._check_policy_freshness(
        policy_path, None
    ) == FreshnessStage("policies", FreshnessState.MALFORMED, "bad document")
    assert freshness_module._check_narrative_freshness(
        narrative_path, None
    ) == FreshnessStage("narratives", FreshnessState.MALFORMED, "unavailable")
    missing_policy = tmp_path / "missing-policy"
    assert freshness_module._check_policy_freshness(
        missing_policy, None
    ) == FreshnessStage("policies", FreshnessState.MISSING, str(missing_policy))
    missing_narrative = tmp_path / "missing-narrative"
    assert freshness_module._check_narrative_freshness(
        missing_narrative, None
    ) == FreshnessStage("narratives", FreshnessState.MISSING, str(missing_narrative))


def _raise_value(_document: dict[str, object]) -> None:
    raise ValueError("bad document")


def test_installed_stage_covers_validation_states(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache_path = tmp_path / "cache"
    context = _context()
    assert freshness_module._check_installed_build_freshness(
        None, None, context
    ) == FreshnessStage(
        "installed_cache",
        FreshnessState.UNAVAILABLE,
        "Steam cache location was not supplied",
    )
    assert freshness_module._check_installed_build_freshness(
        cache_path, 34, None
    ) == FreshnessStage(
        "installed_cache",
        FreshnessState.STALE,
        "strategy context is unavailable",
    )
    assert freshness_module._check_installed_build_freshness(
        cache_path, 34, {"heroes": "bad"}
    ) == FreshnessStage(
        "installed_cache",
        FreshnessState.MALFORMED,
        "strategy context has no hero list",
    )

    monkeypatch.setattr(freshness_module, "_read_installed_descriptions", _raise_cache)
    assert freshness_module._check_installed_build_freshness(
        cache_path, 34, context
    ) == FreshnessStage("installed_cache", FreshnessState.MALFORMED, "bad cache")
    monkeypatch.setattr(
        freshness_module,
        "_read_installed_descriptions",
        lambda _path, _account: {},
    )
    assert freshness_module._check_installed_build_freshness(
        cache_path, 34, context
    ) == FreshnessStage(
        "installed_cache",
        FreshnessState.STALE,
        "managed hero coverage differs from strategy context",
    )
    monkeypatch.setattr(
        freshness_module,
        "_read_installed_descriptions",
        lambda _path, _account: {(12, "default"): "Snapshot: wrong. Policy: wrong."},
    )
    mismatch = freshness_module._check_installed_build_freshness(
        cache_path, 34, context
    )
    assert mismatch == FreshnessStage(
        "installed_cache",
        FreshnessState.STALE,
        "hero 12/default uses another snapshot or policy",
    )
    monkeypatch.setattr(
        freshness_module,
        "_read_installed_descriptions",
        lambda _path, _account: {
            (12, "default"): "Snapshot: snapshot. Policy: policy."
        },
    )
    assert freshness_module._check_installed_build_freshness(
        cache_path, 34, context
    ) == FreshnessStage("installed_cache", FreshnessState.CURRENT, "validated")


def _raise_cache(_path: Path, _account_id: int) -> dict[tuple[int, str], str]:
    raise freshness_module.CacheError("bad cache")


def test_installed_descriptions_reject_invalid_and_duplicate_builds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(freshness_module, "read_cache", lambda _path: {})
    with pytest.raises(freshness_module.CacheError, match="Unpublished"):
        freshness_module._read_installed_descriptions(tmp_path, 34)

    metadata = SimpleNamespace(hero_id=12, description="managed")
    monkeypatch.setattr(
        freshness_module,
        "read_cache",
        lambda _path: {"Unpublished": ["skip", b"one", b"two"]},
    )
    monkeypatch.setattr(
        freshness_module, "parse_hero_build_metadata", lambda _blob: metadata
    )
    monkeypatch.setattr(freshness_module, "managed_build_path", lambda _meta: "default")
    monkeypatch.setattr(
        freshness_module,
        "is_managed_build",
        lambda _meta, *, hero_id, account_id: hero_id == 12 and account_id == 34,
    )
    with pytest.raises(freshness_module.CacheError, match="duplicate"):
        freshness_module._read_installed_descriptions(tmp_path, 34)

    metadata.hero_id = None
    assert freshness_module._read_installed_descriptions(tmp_path, 34) == {}


def test_bundle_stage_and_current_report(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = freshness_module._check_bundle_freshness(tmp_path)
    names = (
        "strategy-context.json",
        "policies.json",
        "narratives.json",
        "build-evidence.json",
    )
    assert missing == FreshnessStage(
        "artifact_bundle",
        FreshnessState.MISSING,
        "missing: " + ", ".join(str(tmp_path / name) for name in names),
    )
    for name in names:
        (tmp_path / name).touch()

    monkeypatch.setattr(freshness_module, "load_artifact_guide_bundle", _raise_bundle)
    assert freshness_module._check_bundle_freshness(tmp_path) == FreshnessStage(
        "artifact_bundle", FreshnessState.MALFORMED, "bad bundle"
    )
    monkeypatch.setattr(
        freshness_module,
        "load_artifact_guide_bundle",
        lambda *_paths: SimpleNamespace(guides=(1, 2)),
    )
    current = freshness_module._check_bundle_freshness(tmp_path)
    assert current == FreshnessStage(
        "artifact_bundle",
        FreshnessState.CURRENT,
        "2 reviewed guide(s) validated as one bundle",
    )

    report = FreshnessReport(
        (FreshnessStage("all", FreshnessState.CURRENT, "valid"),),
        123,
        _Api().current_patch(),
    )
    assert report.exit_code == 0
    assert report.as_dict() == {
        "status": "current",
        "latest_client_version": 123,
        "latest_patch": {
            "identity": (
                "d147fb9752a35abed94fcb64a5510713f4fa6bae5f0b7b29d09d08d220f00322"
            ),
            "title": "Patch",
            "start_timestamp": 100,
            "published_at": "2026-01-01T00:00:00Z",
            "source": "unknown",
            "guid": "unknown",
            "link": "",
            "content_sha256": "",
        },
        "stages": [
            {"stage": "all", "state": "current", "detail": "valid"},
        ],
    }


def _raise_bundle(*_paths: Path) -> object:
    raise ValueError("bad bundle")
