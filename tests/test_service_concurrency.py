from __future__ import annotations

from dataclasses import replace
from threading import Barrier, Event
from typing import TYPE_CHECKING

from deadlock_build_sync import service_inputs
from tests.service_evidence_fixtures import make_service_build_evidence
from tests.service_fake_api import FakeApi, make_ability_rows, make_duration_statistics

if TYPE_CHECKING:
    import pytest

    from deadlock_build_sync.api import DeadlockApi


def test_concurrent_hero_requests_preserve_serial_evidence_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    api = FakeApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    catalog = make_service_build_evidence(api)
    heroes: list[dict[str, object]] = [{"id": hero} for hero in range(4)]
    catalog = replace(catalog, heroes=dict.fromkeys(range(4), catalog.heroes[12]))
    evidence = service_inputs._GenerationEvidence([], catalog, 1, {}, {}, {})
    api.recorder.records.clear()
    api.recorder.record("/v1/assets/heroes", {}, b"initial")
    initial = api.recorder.records[0]
    barrier = Barrier(4, timeout=5)
    finished = Event()

    def prepare(
        scoped: DeadlockApi,
        hero: dict[str, object],
        _evidence: service_inputs._GenerationEvidence,
    ) -> tuple[()]:
        assert scoped.recorder is not api.recorder
        assert not scoped.recorder.records
        barrier.wait()
        if hero["id"] == 0:
            assert finished.wait(timeout=5)
        scoped.recorder.record(
            "/v1/analytics/ability-order-stats", {"hero_id": hero["id"]}, b"response"
        )
        if hero["id"] == 3:
            finished.set()
        return ()

    monkeypatch.setattr(service_inputs, "_prepare_hero_inputs", prepare)
    assert (
        service_inputs._collect_hero_inputs(api, heroes, evidence, all_heroes=True)
        == []
    )
    assert api.recorder.records[0] is initial
    assert [record.parameters for record in api.recorder.records[1:]] == [
        {"hero_id": hero["id"]} for hero in heroes
    ]
    api.close()
