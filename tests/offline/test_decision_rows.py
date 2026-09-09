from __future__ import annotations

from deadlock_build_sync.offline.decision_rows import IndexedDecisionRows


def test_index_preserves_order_duplicates_and_identical_action_selection() -> None:
    rows: list[dict[str, object]] = [
        {"item_id": item, "observation": index}
        for index, item in enumerate((3, 2, 1, 3, 4, 2, 1))
    ]
    indexed = IndexedDecisionRows(rows)
    for item, comparator in ((1, 3), (3, 1), (2, 2), (9, 1), (9, 10)):
        selected = list(indexed.select_items(item, comparator))
        expected = [row for row in rows if row["item_id"] in {item, comparator}]
        assert selected == expected
        assert all(
            actual is original
            for actual, original in zip(selected, expected, strict=True)
        )
