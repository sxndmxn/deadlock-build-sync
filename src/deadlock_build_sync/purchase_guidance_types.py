"""Typed purchase guidance shared by evidence, generation, and review."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .match_choices import AutomaticBranch


@dataclass(frozen=True)
class PurchaseTiming:
    item_id: int
    buyers: int
    counts_by_checkpoint: tuple[int, ...]

    @property
    def observed_position(self) -> int:
        return max(
            range(len(self.counts_by_checkpoint)),
            key=self.counts_by_checkpoint.__getitem__,
        )

    @property
    def support(self) -> int:
        return self.counts_by_checkpoint[self.observed_position]

    @property
    def position(self) -> int | None:
        if self.support >= 20 and self.support >= self.buyers * 0.1:
            return self.observed_position
        return None


@dataclass(frozen=True)
class ItemPurpose:
    label: str
    trigger: str
    evidence: str
    basis: str


@dataclass(frozen=True)
class PurchaseStep:
    item_id: int
    name: str
    incremental_cost: int
    cumulative_cost: int
    consumed_items: tuple[int, ...]
    owned_after: tuple[int, ...]


@dataclass(frozen=True)
class PurchasePlan:
    actions: tuple[PurchaseStep, ...]
    final_inventory: tuple[int, ...]
    remaining_cost: int
    decision: str
    save_souls: int | None


@dataclass(frozen=True)
class PurchaseState:
    owned: tuple[int, ...] = ()
    liquid_souls: int | None = None
    flex: int = 0


@dataclass(frozen=True)
class PurchaseChoice:
    item_id: int
    name: str
    tier: int
    catalog_cost: int
    purpose: ItemPurpose
    after_step: int | None
    timing: PurchaseTiming | None
    timing_basis: str
    route: tuple[int, ...]
    upgrades_core: tuple[int, ...]
    plan: PurchasePlan | None
    blocked_reason: str | None
    extra_path_cost: int | None
    rebought_components: tuple[int, ...]


@dataclass(frozen=True)
class PurchaseDecision:
    after_step: int
    kind: str
    purpose: str
    options: tuple[int, ...]
    upgrade_fork: bool = False


@dataclass(frozen=True)
class PurchaseGuidance:
    core_ids: tuple[int, ...]
    default_path: PurchasePlan
    choices: tuple[PurchaseChoice, ...]
    decisions: tuple[PurchaseDecision, ...]
    names: dict[int, str]
    evidence_basis: str = "Admitted production core; optional effects and timing do not prove an outcome benefit"
    schema_version: int = 2
    automatic_branches: tuple[AutomaticBranch, ...] = ()

    def as_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["names"] = {str(item): name for item, name in self.names.items()}
        return result
