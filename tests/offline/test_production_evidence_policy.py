import polars as pl

from deadlock_build_sync.offline.doubly_robust_estimation import (
    estimate_cross_fitted_doubly_robust_contrast,
)
from deadlock_build_sync.offline.production_sources import (
    _calculate_patch_content_sha256,
)
from tests.offline.production_evidence_fixtures import (
    make_contrast_rows,
)


def test_cross_fitted_dr_contrast_rejects_a_stable_like_state_tie() -> None:
    contrast = estimate_cross_fitted_doubly_robust_contrast(
        pl.DataFrame(make_contrast_rows(positive=False)), 10, 20
    )

    assert not contrast.admitted
    assert contrast.estimate == 0
    assert "positive_advantage" in contrast.failed_gates


def test_cross_fitted_dr_contrast_admits_positive_train_and_validation() -> None:
    contrast = estimate_cross_fitted_doubly_robust_contrast(
        pl.DataFrame(make_contrast_rows(positive=True)), 10, 20
    )

    assert contrast.admitted
    assert contrast.estimate == 1
    assert contrast.overlap == 1
    assert contrast.effective_support >= 20
    assert contrast.maximum_weight <= 10
    assert contrast.maximum_standardized_mean_difference <= 0.10
    assert set(contrast.fold_estimates) == {"train", "validation", "test"}


def test_test_outcomes_do_not_admit_optional_core_substitutions() -> None:
    rows = make_contrast_rows(positive=True)
    baseline = estimate_cross_fitted_doubly_robust_contrast(pl.DataFrame(rows), 10, 20)
    without_test = estimate_cross_fitted_doubly_robust_contrast(
        pl.DataFrame([row for row in rows if row["fold"] != "test"]),
        10,
        20,
    )

    assert baseline.admitted == without_test.admitted
    assert baseline.estimate == without_test.estimate
    assert baseline.interval == without_test.interval
    assert set(without_test.fold_estimates) == {"train", "validation"}


def test_patch_content_hash_normalizes_steam_cdn_routing() -> None:
    akamai = '<img src="https://clan.akamai.steamstatic.com/images/x.png">Notes'
    fastly = akamai.replace("akamai", "fastly")

    assert _calculate_patch_content_sha256(akamai) == _calculate_patch_content_sha256(
        fastly
    )
    assert _calculate_patch_content_sha256(akamai) != _calculate_patch_content_sha256(
        fastly.replace("Notes", "Changed notes")
    )
