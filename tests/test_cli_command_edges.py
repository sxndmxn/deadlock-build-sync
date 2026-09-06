import json
from argparse import Namespace
from pathlib import Path
from types import SimpleNamespace

import pytest

from deadlock_build_sync import cli_recommend, cli_status, cli_support
from deadlock_build_sync.cache import CacheError


class _FakeApi:
    def __init__(self, *_args: object, **_kwargs: object) -> None:
        pass

    @staticmethod
    def items() -> dict[int, dict[str, object]]:
        return {42: {"id": 42}}


def test_run_recommend_emits_a_compatible_default_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    epochs = {"items": "epoch"}
    evidence = SimpleNamespace(
        artifact_id="evidence",
        heroes={12: {}},
        client_version=123,
        as_of_timestamp=456,
        cohort={"match_mode": "Ranked", "game_mode": "Normal"},
        patch={"identity": "patch"},
        epochs=SimpleNamespace(as_dict=lambda: epochs),
    )
    state = SimpleNamespace(hero_id=12)
    policy = SimpleNamespace(policy_id="policy")
    manifest = {
        "client_version": 123,
        "as_of_timestamp": 456,
        "match_mode": "ranked",
        "game_mode": "normal",
        "patch": {"identity": "patch"},
        "epochs": epochs,
    }
    api_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def api_factory(*args: object, **kwargs: object) -> _FakeApi:
        api_calls.append((args, kwargs))
        return _FakeApi()

    monkeypatch.setattr(cli_recommend, "DeadlockApi", api_factory)
    monkeypatch.setattr(
        cli_recommend,
        "require_current_build_evidence",
        lambda *_args: evidence,
    )
    monkeypatch.setattr(
        cli_recommend,
        "_record_fresh_evidence",
        lambda path, value: (
            pytest.fail("wrong evidence path")
            if path != args.build_evidence.resolve() or value is not evidence
            else None
        ),
    )
    monkeypatch.setattr(
        cli_recommend,
        "DecisionState",
        SimpleNamespace(
            from_file=lambda path: (
                state
                if path == args.state.resolve()
                else pytest.fail("wrong state path")
            )
        ),
    )
    monkeypatch.setattr(
        cli_recommend,
        "load_policy_artifact",
        lambda path: (
            (manifest, {(12, "default"): policy})
            if path == args.policies.resolve()
            else pytest.fail("wrong policy path")
        ),
    )

    def run_recommend(*values: object) -> SimpleNamespace:
        assert values == (evidence, policy, state, {42: {"id": 42}})
        return SimpleNamespace(as_dict=lambda: {"item_id": 42})

    monkeypatch.setattr(
        cli_recommend,
        "recommend",
        run_recommend,
    )
    monkeypatch.setattr(cli_recommend, "record_stage_facts", lambda *_args, **_kw: None)
    args = Namespace(
        build_evidence=tmp_path / "evidence.json",
        artifacts=None,
        policies=tmp_path / "policies.json",
        state=tmp_path / "state.json",
        api_base_url="https://example.invalid",
    )

    assert cli_recommend._run_recommend(args) == 0
    assert api_calls == [
        (("https://example.invalid",), {}),
        (
            ("https://example.invalid",),
            {
                "client_version": 123,
                "as_of_timestamp": 456,
                "epochs": evidence.epochs,
            },
        ),
    ]
    assert json.loads(capsys.readouterr().out) == {"item_id": 42}


def test_run_preview_emits_generated_guides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    evidence_path = tmp_path / "evidence.json"
    evidence = SimpleNamespace(artifact_id="evidence")
    generated = SimpleNamespace(
        persona="Player",
        manifest=SimpleNamespace(
            as_dict=lambda: {"snapshot_id": "snapshot"}, rank_range="R"
        ),
        patch=SimpleNamespace(as_dict=lambda: {"title": "Patch"}),
        exclusions=((13, "missing evidence"),),
        policies=(SimpleNamespace(as_dict=lambda: {"policy_id": "policy"}),),
        guides=("guide",),
    )
    location = SimpleNamespace(account_id=7)
    api = object()
    catalog = object()
    monkeypatch.setattr(
        cli_recommend,
        "_location",
        lambda _args: location,
    )
    monkeypatch.setattr(
        cli_recommend,
        "_build_evidence",
        lambda _args: (evidence_path, evidence),
    )
    monkeypatch.setattr(cli_support, "_api", lambda *_args: api)
    monkeypatch.setattr(cli_recommend, "_catalog", lambda _args: catalog)

    def generate(*args: object, **kwargs: object) -> SimpleNamespace:
        assert args == (api,)
        assert kwargs == {
            "build_evidence": evidence,
            "account_id": 7,
            "hero_query": None,
            "all_heroes": True,
            "narrative_catalog": catalog,
        }
        return generated

    monkeypatch.setattr(cli_support, "generate_guides", generate)
    monkeypatch.setattr(cli_support, "_record_generated_facts", lambda _value: None)
    monkeypatch.setattr(cli_support, "_report_skipped", lambda _value: None)

    def describe(*args: object, account_id: int) -> dict[str, int]:
        assert args == ("guide", generated)
        return {"account_id": account_id}

    monkeypatch.setattr(cli_recommend, "_describe_preview_guide", describe)
    monkeypatch.setattr(cli_recommend, "record_stage_facts", lambda *_args, **_kw: None)
    args = Namespace(narratives=None, hero=None, all=True, format="json", details=False)

    assert cli_recommend._run_preview(args) == 0
    assert json.loads(capsys.readouterr().out) == {
        "account_id": 7,
        "persona": "Player",
        "snapshot_manifest": {"snapshot_id": "snapshot"},
        "patch": {"title": "Patch"},
        "rank_range": "R",
        "exclusions": [{"hero_id": 13, "reason": "missing evidence"}],
        "artifacts": {
            "build_evidence": str(evidence_path),
            "build_evidence_id": "evidence",
            "context": None,
            "policy": "inline:policies",
            "narrative": None,
        },
        "policies": [{"policy_id": "policy"}],
        "guides": [{"account_id": 7}],
    }


def test_run_status_emits_json_with_cache_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = SimpleNamespace(
        stages=(),
        exit_code=0,
        as_dict=lambda: {"exit_code": 0},
    )
    seen: dict[str, object] = {}
    monkeypatch.setattr(cli_status, "DeadlockApi", _FakeApi)
    monkeypatch.setattr(
        cli_status,
        "_location",
        lambda _args: SimpleNamespace(cache_path=tmp_path / "cache.kv3", account_id=7),
    )

    def build_report(*_args: object, **kwargs: object) -> SimpleNamespace:
        seen.update(kwargs)
        return report

    monkeypatch.setattr(cli_status, "build_freshness_report", build_report)
    monkeypatch.setattr(cli_status, "record_stage_facts", lambda *_args, **_kw: None)
    args = Namespace(
        artifacts=tmp_path,
        api_base_url="https://example.invalid",
        json=True,
    )

    assert cli_status._run_status(args) == 0
    assert seen == {"cache_path": tmp_path / "cache.kv3", "account_id": 7}
    assert json.loads(capsys.readouterr().out) == {"exit_code": 0}


def test_run_status_emits_text_without_cache_location(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report = SimpleNamespace(
        stages=(
            SimpleNamespace(
                name="evidence",
                state=SimpleNamespace(value="stale"),
                detail="regenerate",
            ),
        ),
        exit_code=2,
        latest_client_version=123,
        latest_patch=SimpleNamespace(
            title="Patch",
            published_at="2026-08-30T00:00:00Z",
        ),
    )
    monkeypatch.setattr(cli_status, "DeadlockApi", _FakeApi)
    monkeypatch.setattr(
        cli_status,
        "_location",
        lambda _args: (_ for _ in ()).throw(CacheError("missing cache")),
    )
    monkeypatch.setattr(
        cli_status,
        "build_freshness_report",
        lambda *_args, **_kw: report,
    )
    monkeypatch.setattr(cli_status, "record_stage_facts", lambda *_args, **_kw: None)
    args = Namespace(
        artifacts=tmp_path,
        api_base_url="https://example.invalid",
        json=False,
    )

    assert cli_status._run_status(args) == 2
    assert capsys.readouterr().out.splitlines() == [
        "STALE — regeneration required",
        "Latest: client 123 • Patch (2026-08-30T00:00:00Z)",
        "evidence: stale — regenerate",
    ]
