"""Comparison adapter for the shared production implementation."""

from deadlock_build_sync.offline.discovery_grouping import (
    consolidate,
    merge_complete,
    similarities,
)

__all__ = ["consolidate", "merge_complete", "similarities"]
