from deadlock_build_sync.offline.models import (
    BetaPrior,
    beta_posterior,
    fit_beta_prior,
    phase_for_time,
    prior_snapshot_value,
    wilson_interval,
)


def test_wilson_known_interval() -> None:
    low, high = wilson_interval(55, 100)
    assert round(low, 3) == 0.452
    assert round(high, 3) == 0.644


def test_empirical_bayes_shrinks_sparse_more_than_dense() -> None:
    prior = BetaPrior(50, 50, "test")
    sparse, _, _ = beta_posterior(9, 10, prior)
    dense, _, _ = beta_posterior(900, 1000, prior)
    assert abs(sparse - 0.5) < abs(dense - 0.5)
    assert dense > sparse


def test_prior_fit_is_finite_and_bounded() -> None:
    prior = fit_beta_prior([(45, 100), (52, 100), (48, 100), (55, 100)])
    assert 0 < prior.alpha <= 500
    assert 0 < prior.beta <= 500
    assert 5 <= prior.strength <= 500


def test_prior_snapshot_never_uses_future_or_final_fallback() -> None:
    assert prior_snapshot_value([60, 120], [1000, 2000], 100) == 1000
    assert prior_snapshot_value([60, 120], [1000, 2000], 30) is None


def test_phase_boundaries_are_half_open() -> None:
    assert [
        phase_for_time(value) for value in (0, 539, 540, 1199, 1200, 1799, 1800)
    ] == [
        0,
        0,
        1,
        1,
        2,
        2,
        3,
    ]
