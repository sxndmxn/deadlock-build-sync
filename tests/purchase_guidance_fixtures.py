from deadlock_build_sync.mechanics import ItemGraph
from deadlock_build_sync.purchase_guidance import attach_purchase_guidance
from deadlock_build_sync.purchase_guidance_types import PurchaseTiming
from deadlock_build_sync.purchase_types import GuideItem, PurchaseGuide
from tests.mechanics_fixtures import make_item_asset


def make_guidance_assets() -> list[dict[str, object]]:
    return [
        make_item_asset(1, "Sprint", cost=800),
        make_item_asset(2, "Speed", cost=1600, components=["Sprint"]),
        make_item_asset(3, "Core A", cost=800),
        make_item_asset(4, "Core B", cost=1600),
        make_item_asset(5, "Core C", cost=3200),
        {
            **make_item_asset(6, "Trophy", cost=3200, components=["Sprint"]),
            "description": "Bonus souls on assist or kill.",
        },
        {
            **make_item_asset(7, "Bullet Guard", cost=1600),
            "description": "Grants bullet resist.",
        },
        {
            **make_item_asset(8, "Bullet Shield", cost=3200, active=True),
            "description": "Immune to bullets.",
        },
        {**make_item_asset(9, "Mystery", cost=800), "description": "A strange effect."},
        make_item_asset(10, "Range", cost=800),
        make_item_asset(11, "Greater Range", cost=3200, components=["Range"]),
        make_item_asset(12, "Other Range", cost=3200, components=["Range"]),
    ]


def make_purchase_guidance() -> tuple[PurchaseGuide, ItemGraph]:
    assets = make_guidance_assets()
    graph = ItemGraph.from_assets(assets)
    by_id = {
        node.item_id: GuideItem(
            node.item_id, node.name, node.tier, 100, 0.5, 0.4, 0.5, ()
        )
        for node in graph.nodes.values()
    }
    guide = PurchaseGuide(
        12,
        "Kelvin",
        "hero_kelvin",
        {1: tuple(by_id[key] for key in (6, 7, 8, 9, 10, 11, 12)), 2: (), 3: (), 4: ()},
        core_items=tuple(by_id[key] for key in (2, 3, 4, 5)),
        core_purchase_items=tuple(by_id[key] for key in (1, 3, 2, 4, 5)),
        core_target_cost=7200,
        purchase_timing=tuple(
            PurchaseTiming(key, 100, (0, 0, 30, 0, 0, 0))
            for key in (6, 7, 8, 10, 11, 12)
        ),
    )
    return attach_purchase_guidance(guide, assets), graph
