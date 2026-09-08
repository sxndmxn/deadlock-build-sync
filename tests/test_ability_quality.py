from dataclasses import replace
from typing import override

import pytest

from deadlock_build_sync.ability_order import AbilityPath
from deadlock_build_sync.service import generate_guides
from tests.service_evidence_fixtures import make_service_build_evidence
from tests.service_fake_api import FakeApi, make_ability_rows, make_duration_statistics


class _SparseBuildApi(FakeApi):
    @override
    def ability_order_stats(
        self,
        *,
        hero_id: int,
        min_unix_timestamp: int,
        min_matches: int,
        include_item_ids: tuple[int, ...] = (),
    ) -> list[dict[str, object]]:
        rows = super().ability_order_stats(
            hero_id=hero_id,
            min_unix_timestamp=min_unix_timestamp,
            min_matches=min_matches,
            include_item_ids=include_item_ids,
        )
        if include_item_ids:
            return [{**row, "matches": 1, "wins": 1, "losses": 0} for row in rows]
        return rows


@pytest.mark.parametrize("empty", [False, True])
def test_unsupported_build_orders_keep_explicit_unapproved_fallback(
    monkeypatch: pytest.MonkeyPatch,
    *,
    empty: bool,
) -> None:
    api = _SparseBuildApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    if empty:
        original = api.ability_order_stats

        def without_build(**kwargs: object) -> list[dict[str, object]]:
            return (
                []
                if kwargs.get("include_item_ids")
                else original(hero_id=12, min_unix_timestamp=1, min_matches=1)
            )

        monkeypatch.setattr(api, "ability_order_stats", without_build)
    generated = generate_guides(
        api,
        build_evidence=make_service_build_evidence(api),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )
    path = generated.guides[0].ability_path
    assert path is not None
    assert path.fallback_reason
    assert path.quality_assessment()["status"] == "unevaluated"
    assert not path.quality_assessment()["build_conditioned"]


def test_single_path_checks_build_conditioned_ability_support() -> None:
    api = FakeApi(
        ability_rows=make_ability_rows(), duration_points=make_duration_statistics()
    )
    generated = generate_guides(
        api,
        build_evidence=make_service_build_evidence(api),
        account_id=123,
        hero_query="Kelvin",
        all_heroes=False,
    )
    assert len(api.ability_filter_calls) == 2
    assert api.ability_filter_calls[1]
    path = generated.guides[0].ability_path
    assert path is not None
    assert path.quality_assessment()["status"] == "pass"


def test_ability_quality_does_not_approve_sparse_or_unverified_orders() -> None:
    path = AbilityPath((1, 2, 3, 4) * 4, 20, 10, 10, 20, decision_support=(20,) * 16)
    assert path.quality_assessment()["status"] == "unevaluated"
    verified = replace(path, filter_item_ids=(100, 200))
    assert verified.quality_assessment()["status"] == "pass"
    assert (
        replace(verified, decision_support=(20,) * 15 + (1,)).quality_assessment()[
            "status"
        ]
        == "fail"
    )
    fallback = replace(path, fallback_reason="insufficient build-conditioned support")
    assert fallback.quality_assessment()["fallback_reason"]
    assert fallback.quality_assessment()["status"] == "unevaluated"
