import numpy as np
import pytest

from deadlock_build_sync.offline.inventory_reconstruction import (
    InventoryTimeline,
    reconstruct_final_inventory,
)


@pytest.mark.parametrize("malformed_sale", [False, True])
def test_inventory_timeline_matches_replay_at_every_event_boundary(
    *,
    malformed_sale: bool,
) -> None:
    generator = np.random.default_rng(819)
    purchases = [
        (int(generator.integers(1, 5)), bought, bought + int(generator.integers(0, 8)))
        for bought in sorted(int(value) for value in generator.integers(1, 30, 40))
    ]
    purchases.extend([(1, 10, 0), (2, 10, 10), (3, 10, 0), (1, 20, 0)])
    if malformed_sale:
        purchases.append((1, 25, 2))
    components = {2: (1,), 3: (2,)}
    timeline = InventoryTimeline(purchases, components)
    clocks = [*range(40), *range(39, -1, -1), 10, 10, 30, 1, 40]
    for clock in clocks:
        expected = reconstruct_final_inventory(
            [
                (item, bought, sold if 0 < sold < clock else 0)
                for item, bought, sold in purchases
                if bought < clock
            ],
            components,
        )
        assert timeline.before(clock) == expected


def test_empty_inventory_timeline_has_no_items() -> None:
    assert InventoryTimeline([], {}).before(100) == ()
