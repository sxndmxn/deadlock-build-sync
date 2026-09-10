from dataclasses import replace

import pytest

from deadlock_build_sync import cache_storage
from deadlock_build_sync.cache import CacheError
from deadlock_build_sync.presentation import MANAGED_MARKER
from deadlock_build_sync.protobuf import HeroBuildMetadata
from tests.cache_fixtures import (
    SNAPSHOT_ID,
    make_complete_guide,
    make_snapshot_manifest,
)


def _metadata(
    *,
    build_id: int | None = 2,
    hero_id: int | None = 12,
    account_id: int | None = 7,
    description: str | None = None,
) -> HeroBuildMetadata:
    return HeroBuildMetadata(
        build_id,
        hero_id,
        account_id,
        "Build",
        description
        if description is not None
        else f"{MANAGED_MARKER}\nBuild path: default.",
        0,
        None,
        (),
    )


def test_stable_cache_value_sorts_mixed_keys_by_their_text() -> None:
    normalized = cache_storage._normalize_cache_value({2: "a", "10": "z"})

    assert isinstance(normalized, dict)
    assert list(normalized) == ["10", "2"]
    assert normalized == {"10": "z", "2": "a"}


def test_out_of_scope_fingerprint_filters_only_unpublished_targets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cache_storage,
        "_is_target_managed_blob",
        lambda value, **_kwargs: value == "managed",
    )
    root: dict[str, object] = {
        "é": "snow ☃",
        "Z": ["managed"],
        "Unpublished": ["managed", "keep"],
        "bytes": b"\x00",
    }

    assert (
        cache_storage._calculate_unmanaged_cache_fingerprint(
            root,
            account_id=7,
            target_hero_ids={12},
        )
        == "e30975306b35df3e054b5d39bb95023a11f0cdb4067a23d6531170c9521c61f5"
    )


def test_target_blob_requires_both_hero_scope_and_managed_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cache_storage,
        "try_parse_hero_build_metadata",
        lambda _value: _metadata(hero_id=13),
    )

    assert not cache_storage._is_target_managed_blob(
        b"blob",
        account_id=7,
        target_hero_ids={12},
    )


@pytest.mark.parametrize(
    "metadata",
    [
        _metadata(account_id=8),
        _metadata(hero_id=None),
        _metadata(description=MANAGED_MARKER),
        _metadata(description="Build path: default."),
        _metadata(description=""),
    ],
)
def test_target_metadata_rejects_each_invalid_identity(
    metadata: HeroBuildMetadata,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        cache_storage,
        "try_parse_hero_build_metadata",
        lambda _value: metadata,
    )

    assert (
        cache_storage._match_target_managed_metadata(
            b"blob",
            {(12, "default"): 2},
            7,
        )
        is None
    )


def test_target_metadata_requires_an_expected_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    metadata = _metadata()
    monkeypatch.setattr(
        cache_storage,
        "try_parse_hero_build_metadata",
        lambda _value: metadata,
    )

    assert cache_storage._match_target_managed_metadata(b"blob", {}, 7) is None
    assert cache_storage._match_target_managed_metadata(
        b"blob", {(12, "default"): 2}, 7
    ) == (
        (12, "default"),
        metadata,
    )


def test_managed_identity_returns_id_and_requires_each_fingerprint() -> None:
    key = (12, "default")
    valid = _metadata(
        description=(
            f"{MANAGED_MARKER}\nBuild path: default.\n"
            "Snapshot: snapshot.\nPolicy: policy."
        )
    )

    assert cache_storage._validate_managed_identity(key, valid, {}) == 2
    assert (
        cache_storage._validate_managed_identity(
            key,
            valid,
            {key: ("snapshot", "policy")},
        )
        == 2
    )

    for description in (
        f"{MANAGED_MARKER}\nBuild path: default.\nPolicy: policy.",
        f"{MANAGED_MARKER}\nBuild path: default.\nSnapshot: snapshot.",
        None,
    ):
        with pytest.raises(
            CacheError,
            match=(r"^replacement cache managed build 12/default has stale identity$"),
        ):
            cache_storage._validate_managed_identity(
                key,
                replace(valid, description=description),
                {key: ("snapshot", "policy")},
            )


def test_managed_entry_errors_report_exact_section_and_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(
        CacheError,
        match=r"^replacement cache Unpublished section is not an array$",
    ):
        cache_storage._validate_managed_entries({}, {}, account_id=7)

    metadata = _metadata()
    monkeypatch.setattr(
        cache_storage,
        "_match_target_managed_metadata",
        lambda _blob, _expected, _account_id: ((12, "default"), metadata),
    )
    with pytest.raises(
        CacheError,
        match=r"^replacement cache contains duplicate managed build 12/default$",
    ):
        cache_storage._validate_managed_entries(
            {"Unpublished": [b"one", b"two"]},
            {(12, "default"): 2},
            account_id=7,
        )


def test_install_coverage_reports_missing_and_extra_heroes_exactly() -> None:
    with pytest.raises(
        CacheError,
        match=(
            r"^all-hero installation coverage mismatch; missing \[13\], extra \[14\]$"
        ),
    ):
        cache_storage._validate_install_coverage(
            {12, 14},
            {12, 13},
            allow_subset=False,
        )


def test_install_request_rejects_each_incomplete_guide_field() -> None:
    base = make_complete_guide()
    all_optional = tuple(
        replace(category, optional=True) for category in base.rendered_categories
    )
    incomplete = [
        replace(base, tiers={}),
        replace(base, categories=all_optional),
        replace(base, snapshot_id=""),
        replace(base, policy_id=""),
        replace(base, client_version=None),
        replace(base, match_mode=""),
        replace(base, rank_identity=""),
    ]

    for invalid in incomplete:
        with pytest.raises(
            CacheError,
            match=(
                r"^refusing to install guides with incomplete policy "
                r"identity/projection: Kelvin$"
            ),
        ):
            cache_storage._validate_install_request(
                [invalid],
                make_snapshot_manifest(),
                {12},
                allow_subset=False,
            )


def test_install_request_lists_each_incomplete_hero() -> None:
    first = replace(make_complete_guide(), hero_name="Alpha", snapshot_id="")
    second = replace(
        make_complete_guide(),
        hero_id=13,
        hero_name="Beta",
        snapshot_id="",
    )

    with pytest.raises(
        CacheError,
        match=(
            r"^refusing to install guides with incomplete policy "
            r"identity/projection: Alpha, Beta$"
        ),
    ):
        cache_storage._validate_install_request(
            [first, second],
            make_snapshot_manifest(),
            {12, 13},
            allow_subset=False,
        )


def test_install_request_returns_complete_identity_and_allows_a_subset() -> None:
    guide = make_complete_guide()

    identity = cache_storage._validate_install_request(
        [guide],
        make_snapshot_manifest(),
        {12, 13},
        allow_subset=True,
    )

    assert identity == cache_storage._GuideInstallationIdentity(
        hero_ids={12},
        build_keys={(12, "default")},
        snapshot_id=SNAPSHOT_ID,
        policy_ids={(12, "default"): "policy/kelvin"},
        identities={(12, "default"): (SNAPSHOT_ID, "policy/kelvin")},
    )


def test_install_request_reports_other_contract_errors_exactly() -> None:
    guide = make_complete_guide()
    duplicate = replace(guide)

    with pytest.raises(CacheError, match=r"^no guides were generated$"):
        cache_storage._validate_install_request(
            [], make_snapshot_manifest(), {12}, allow_subset=False
        )
    with pytest.raises(
        CacheError,
        match=r"^refusing to install duplicate hero/build-path guides$",
    ):
        cache_storage._validate_install_request(
            [guide, duplicate],
            make_snapshot_manifest(),
            {12},
            allow_subset=False,
        )
    with pytest.raises(
        CacheError,
        match=r"^all installed guides must use one snapshot$",
    ):
        cache_storage._validate_install_request(
            [guide, replace(guide, hero_id=13, snapshot_id="other")],
            make_snapshot_manifest(),
            {12, 13},
            allow_subset=False,
        )
    with pytest.raises(
        CacheError,
        match=r"^install snapshot manifest is missing or incompatible$",
    ):
        cache_storage._validate_install_request(
            [guide],
            None,
            {12},
            allow_subset=False,
        )
