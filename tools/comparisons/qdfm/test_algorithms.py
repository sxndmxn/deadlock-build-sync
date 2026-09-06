"""Check published loss semantics, categorical support, and terminal handling."""

from __future__ import annotations

import copy

import pytest
import torch

from tools.comparisons.qdfm.algorithm_diagnostics import greedy_toy_score
from tools.comparisons.qdfm.algorithm_run import toy_outcome
from tools.comparisons.qdfm.algorithms import (
    QQL_HIGH,
    QQL_LOW,
    QQL_SOFT,
    AlgorithmConfig,
    Learner,
    Trainer,
    advantage_weights,
    asymmetric_loss,
    conservative_penalty,
    qql_target,
)
from tools.comparisons.qdfm.toy import make_data


def test_quantile_and_expectile_use_different_residual_geometry() -> None:
    residual = torch.tensor([-2.0, 1.0])
    assert float(asymmetric_loss(residual, 0.8, squared=False)) == pytest.approx(0.6)
    assert float(asymmetric_loss(residual, 0.8, squared=True)) == pytest.approx(0.8)
    assert pytest.approx(0.4296239983) == QQL_LOW
    assert pytest.approx(0.6321205588) == QQL_SOFT
    assert pytest.approx(0.83154252, abs=1e-7) == QQL_HIGH
    assert QQL_LOW < QQL_SOFT < QQL_HIGH


def test_cql_penalty_only_pushes_down_legal_alternatives() -> None:
    values = torch.tensor([[0.0, 0.0, 999.0]], requires_grad=True)
    loss = conservative_penalty(
        values, torch.tensor([0]), torch.tensor([[True, True, False]])
    )
    loss.backward()
    torch.testing.assert_close(values.grad, torch.tensor([[-0.5, 0.5, 0.0]]))
    assert float(loss.detach()) == pytest.approx(0.69314718)
    with pytest.raises(ValueError, match="outside legal support"):
        conservative_penalty(
            values, torch.tensor([2]), torch.tensor([[True, True, False]])
        )


def test_qql_terminal_target_retains_current_gap_but_no_future_value() -> None:
    data = make_data(42, episodes=1)
    data.rewards[:] = torch.tensor([0.0, 1.0])
    target = qql_target(data, torch.tensor([0.7, 999.0]), torch.tensor([0.1, 0.2]), 1)
    torch.testing.assert_close(target, torch.tensor([0.6, 0.8]))


def test_exponential_weight_cap_is_finite_before_overflow() -> None:
    weights = advantage_weights(torch.tensor([-1000.0, 0.0, 1000.0]))
    torch.testing.assert_close(weights, torch.tensor([0.0, 1.0, 100.0]))


@pytest.mark.parametrize("method", ["bc", "iql", "cql", "qql"])
def test_policy_abstains_on_empty_pool_and_training_keeps_masks(method: str) -> None:
    torch.manual_seed(42)
    data = make_data(42, episodes=5)
    model = Learner(5, 4, AlgorithmConfig(method, hidden=8, steps=1))
    Trainer(model).step(data)
    masks = data.masks.clone()
    masks[0] = False
    masks[1] = torch.tensor([False, False, True, False])
    probs = model.policy(data.states, masks)
    assert bool(torch.isfinite(probs).all())
    assert probs[0].sum() == 0
    assert probs[1, 2] == 1
    assert bool((probs[~masks] == 0).all())


def test_qql_imagination_never_trains_on_terminal_placeholders() -> None:
    data = make_data(42, episodes=2)
    data.done[:] = True
    data.next_states[:] = float("nan")
    model = Learner(5, 4, AlgorithmConfig("qql", hidden=8))
    before = copy.deepcopy(model.state_dict())
    Trainer(model).imagination_step(data)
    for name, value in model.state_dict().items():
        torch.testing.assert_close(value, before[name])


def test_exact_toy_evaluation_integrates_both_purchase_stages() -> None:
    # Zero logits yield a uniform policy at both stages, with analytic mean .38125.
    model = Learner(5, 4, AlgorithmConfig("bc", hidden=8))
    with torch.no_grad():
        for parameter in model.actor.parameters():
            parameter.zero_()
    assert toy_outcome(model)["mean_true_expected_success"] == pytest.approx(0.38125)
    # Greedy ties pick action zero then two: (.65 + .85 + .55 + .80) / 4.
    assert greedy_toy_score(model) == pytest.approx(0.7125)
