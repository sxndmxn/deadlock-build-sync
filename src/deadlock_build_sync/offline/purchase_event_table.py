"""Keep ordered purchase histories in integer arrays and select one match."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class PurchaseEventTable:
    match_ids: np.ndarray
    player_slots: np.ndarray
    events: np.ndarray

    def for_match(self, match: int) -> dict[int, list[tuple[int, int, int, int]]]:
        if (
            not len(self.match_ids)
            or match < int(self.match_ids[0])
            or match > int(self.match_ids[-1])
        ):
            return {}
        key = np.asarray(match, dtype=self.match_ids.dtype)
        start = int(np.searchsorted(self.match_ids, key, side="left"))
        stop = int(np.searchsorted(self.match_ids, key, side="right"))
        result: dict[int, list[tuple[int, int, int, int]]] = {}
        for slot, (team, item, bought, sold) in zip(
            self.player_slots[start:stop], self.events[start:stop], strict=True
        ):
            result.setdefault(int(slot), []).append((
                int(team),
                int(item),
                int(bought),
                int(sold),
            ))
        return result
