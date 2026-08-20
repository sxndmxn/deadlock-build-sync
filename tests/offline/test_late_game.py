from deadlock_build_sync.offline.late_game import reconstruct_final_inventory


def test_final_inventory_consumes_components_and_applies_sales() -> None:
    purchases = [
        (1, 100, 0),
        (2, 200, 0),
        (3, 300, 0),
        (4, 400, 500),
        (4, 600, 0),
    ]
    components = {3: (1, 2)}

    assert reconstruct_final_inventory(purchases, components) == (3, 4)


def test_equal_time_removal_wins_over_purchase() -> None:
    assert reconstruct_final_inventory([(1, 100, 100)], {}) == ()


def test_equal_time_upgrade_replay_uses_dependency_order_not_item_id() -> None:
    purchases = [
        (20, 100, 0),
        (5, 100, 0),
        (1, 100, 0),
    ]
    components = {5: (20,), 1: (5,)}

    assert reconstruct_final_inventory(purchases, components) == (1,)


def test_equal_time_component_removal_does_not_remove_completed_upgrade() -> None:
    purchases = [(1, 100, 100), (2, 100, 0)]

    assert reconstruct_final_inventory(purchases, {2: (1,)}) == (2,)
