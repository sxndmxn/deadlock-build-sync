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
