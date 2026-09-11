"""Check complete-variant recovery and purchase-order display boundaries."""

from __future__ import annotations

from tools.purchase_search.display import (
    BuildVariant,
    card_rows,
    factor_variants,
    layout_dimensions,
    recover_cores,
)


def test_shared_core_factoring_recovers_every_complete_variant() -> None:
    common = frozenset({
        "Swift Striker",
        "Titanic Magazine",
        "Spirit Lifesteal",
        "Toxic Bullets",
    })
    variants = tuple(
        BuildVariant(name, common | additions, ())
        for name, additions in (
            ("Default", {"Mystic Vulnerability", "Enduring Speed"}),
            ("Variant 2", {"Mystic Vulnerability", "Superior Duration"}),
            ("Variant 3", {"Duration Extender"}),
        )
    )
    result = factor_variants(variants)
    assert result.shared_core == common
    assert recover_cores(result) == tuple(variant.core for variant in variants)
    assert (result.repeated_cards, result.factored_cards) == (17, 9)
    assert "Mystic Vulnerability" not in result.shared_core


def test_common_owned_items_do_not_imply_a_common_purchase_prefix() -> None:
    variants = (
        BuildVariant("First", frozenset({"A", "B", "C"}), ("C", "A", "B")),
        BuildVariant("Second", frozenset({"A", "B", "D"}), ("A", "B", "D")),
    )
    result = factor_variants(variants)
    assert result.shared_core == frozenset({"A", "B"})
    assert result.common_purchase_prefix == ()


def test_only_identical_ordered_prefixes_can_share_a_purchase_queue() -> None:
    variants = (
        BuildVariant("First", frozenset({"A", "B", "C"}), ("A", "B", "C")),
        BuildVariant("Second", frozenset({"A", "B", "D"}), ("A", "B", "D")),
    )
    assert factor_variants(variants).common_purchase_prefix == ("A", "B")


def test_row_estimate_preserves_category_boundaries() -> None:
    assert card_rows((4, 2, 2, 1), 4) == 4
    assert card_rows((4, 2, 2, 1), 6) == 4


def test_proposed_layout_dimensions_include_category_gaps() -> None:
    assert layout_dimensions(((9,), (4, 2, 2, 1), (2, 2, 2, 3))) == (872, 516)
    assert layout_dimensions(((9,), (4, 2, 2, 1), (4, 4, 4), (4,))) == (1068, 692)
