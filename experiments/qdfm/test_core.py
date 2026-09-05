"""Numerical and temporal correctness checks for the isolated experiment."""

from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np
import pytest
import torch

from experiments.qdfm.data import transition_rows
from experiments.qdfm.model import (
    Flow,
    conditional_generator,
    critic_target,
    masked_probs,
)
from experiments.qdfm.run import validate_dataset_identity
from experiments.qdfm.state import Catalog, Player, Purchase, features, groups

if TYPE_CHECKING:
    from pathlib import Path


class FixedFlow(Flow):
    def __init__(self) -> None:
        super().__init__(1, 2, 8)

    def rates(
        self,
        _states: torch.Tensor,
        current: torch.Tensor,
        _times: torch.Tensor,
        _masks: torch.Tensor,
    ) -> torch.Tensor:
        rates = torch.zeros((len(current), self.actions))
        rates[:, 1] = (current == 0).float()
        return rates


def tiny_catalog() -> Catalog:
    catalog = Catalog.__new__(Catalog)
    catalog.ids = [10, 20, 30]
    catalog.index = {10: 0, 20: 1, 30: 2}
    catalog.ancestors = {10: frozenset(), 20: frozenset({10}), 30: frozenset()}
    catalog.hero_index = {1: 0}
    catalog.heroes = [1]
    return catalog


@pytest.fixture(autouse=True)
def seed_randomness() -> None:
    torch.manual_seed(197)
    torch.set_num_threads(2)


def test_generator_conserves_mass_and_endpoint_is_absorbing() -> None:
    current = torch.tensor([0, 1])
    target = conditional_generator(
        current, torch.tensor([1, 1]), torch.tensor([0.5, 0.9]), 3
    )
    torch.testing.assert_close(
        target, torch.tensor([[-2.0, 2.0, 0.0], [0.0, 0.0, 0.0]])
    )
    torch.testing.assert_close(target.sum(dim=1), torch.zeros(2))


def test_sampler_matches_known_euler_chain() -> None:
    draws = FixedFlow().sample(
        torch.zeros((1, 1)),
        torch.tensor([[1.0, 0.0]]),
        torch.ones((1, 2), dtype=torch.bool),
        10,
        20000,
    )
    observed = float((draws == 1).float().mean())
    assert observed == pytest.approx(1 - 0.9**10, abs=0.015)


def test_masked_actions_have_zero_probability() -> None:
    mask = torch.tensor([[True, False, True]])
    initial = masked_probs(torch.tensor([[1.0, 1000.0, 1.0]]), mask)
    draws = Flow(2, 3, 8).sample(torch.zeros((1, 2)), initial, mask, 20, 3000)
    assert not bool((draws == 1).any())
    with pytest.raises(ValueError, match="abstain"):
        masked_probs(torch.zeros((1, 3)), torch.zeros_like(mask))


def test_terminal_transition_never_bootstraps() -> None:
    targets = critic_target(
        torch.tensor([1.0, 0.0, 0.0]),
        torch.tensor([True, True, False]),
        torch.tensor([100.0, 100.0, 0.6]),
        1.0,
    )
    torch.testing.assert_close(targets, torch.tensor([1.0, 0.0, 0.6]))


def test_purchase_and_sale_timing_and_component_consumption() -> None:
    catalog = tiny_catalog()
    purchases = [Purchase(10, 100, 0), Purchase(20, 200, 350), Purchase(30, 300, 0)]
    assert catalog.inventory(purchases, 100) == ()
    assert catalog.inventory(purchases, 200) == (10,)
    assert catalog.inventory(purchases, 201) == (20,)
    assert catalog.inventory(purchases, 351) == (30,)
    assert not catalog.legal_bundle((20,), (10,))
    assert catalog.legal_bundle((10,), (20,))


def test_simultaneous_purchases_are_one_basket() -> None:
    assert groups([Purchase(30, 600, 0), Purchase(10, 600, 0)]) == [(600, (10, 30))]


def test_snapshot_at_or_after_decision_is_not_visible() -> None:
    player = Player(0, 1, 0, [100, 200, 300], [10, 20, 999999], [])
    assert player.wealth_before(300) == (20, 100)
    assert player.wealth_before(100) is None


def test_future_wealth_and_purchases_cannot_change_present_features() -> None:
    catalog = tiny_catalog()
    players = [
        Player(
            slot,
            1,
            int(slot >= 6),
            [300, 600, 900],
            [1000 + slot, 2000 + slot, 999999],
            [],
        )
        for slot in range(12)
    ]
    before = features(catalog, players, players[0], 700, 80, 1)[0]
    for player in players:
        player.wealth[-1] = 100000000
        player.purchases.append(Purchase(20, 800, 0))
    after = features(catalog, players, players[0], 700, 80, 1)[0]
    np.testing.assert_array_equal(before, after)


@pytest.mark.parametrize("won", [False, True])
def test_trajectory_has_exactly_one_terminal_reward(*, won: bool) -> None:
    states = [(np.array([float(i)]), 0, np.array([True, False]), i) for i in range(3)]
    rows = transition_rows(states, 10, 12, won=won)
    assert [row[2] for row in rows] == [0.0, 0.0, float(won)]
    assert [row[4] for row in rows] == [False, False, True]
    np.testing.assert_array_equal(rows[0][3], states[1][0])


def test_checkpoint_rejects_another_dataset(tmp_path: Path) -> None:
    validate_dataset_identity(tmp_path, "first")
    with pytest.raises(ValueError, match="different frozen dataset"):
        validate_dataset_identity(tmp_path, "second")
