from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import Patch
    from .narratives import NarrativeCatalog
    from .purchase_guide import PurchaseGuide
    from .ranks import RankRange


class ArtifactBundleError(ValueError):
    """Raised when reviewed install artifacts do not form one exact bundle."""


_COVERAGE_MISMATCH = "artifact bundle coverage differs across files"
_CORE_CATEGORY_NAME = "CORE ITEMS"


@dataclass(frozen=True)
class ArtifactGuideBundle:
    guides: list[PurchaseGuide]
    snapshot_manifest: dict[str, object]
    patch: Patch
    rank_range: RankRange
    expected_hero_ids: frozenset[int]
    exclusions: tuple[tuple[int, str], ...]


@dataclass(frozen=True)
class ArtifactBuildIdentity:
    tag_ids: tuple[int, ...]
    tag_classes: tuple[str, ...]
    tag_labels: tuple[str, ...]
    catalog_sha256: str
    archetype: str


@dataclass(frozen=True)
class _GuideReconstructionContext:
    manifest: dict[str, object]
    rank_identity: str
    patch: Patch
    narratives: NarrativeCatalog
