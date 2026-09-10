"""Check comparison independence and captured response integrity."""

from __future__ import annotations

from typing import TYPE_CHECKING

import httpx
import pytest

from tools.beam_comparison.report import mode_totals
from tools.beam_comparison.snapshot_transport import SnapshotTransport

if TYPE_CHECKING:
    from pathlib import Path


def test_response_cache_reuses_exact_bytes_and_rejects_changes(tmp_path: Path) -> None:
    transport = SnapshotTransport(tmp_path / "raw", tmp_path / "cache")
    transport.transport = httpx.MockTransport(
        lambda _request: httpx.Response(200, content=b'[{"wins": 7}]')
    )
    request = httpx.Request("GET", "https://example.invalid/analytics?hero=1")
    first = transport.handle_request(request)
    assert transport.handle_request(request).content == first.content
    cached = next(
        path
        for path in (tmp_path / "cache").glob("*.json")
        if not path.name.endswith(".request.json")
    )
    cached.write_bytes(b'[{"wins": 70}]')
    with pytest.raises(ValueError, match="fingerprint"):
        transport.handle_request(request)
    transport.close()


def test_comparison_separates_core_order_actions_and_fallbacks() -> None:
    original: dict[str, object] = {"core": [1, 2, 3, 4], "path": [1, 2, 3, 4]}
    build: dict[str, object] = {
        "core": [2, 1, 3, 4],
        "path": [2, 1, 3, 4],
        "core_cost": 6400,
        "variant_count": 2,
        "generator": {"effective": "current"},
        "status": "observed",
        "variants": [
            {"generator": {"effective": "current"}, "core": [1, 2, 3, 4]},
            {"generator": {"effective": "beam"}, "core": [1, 2, 3, 5]},
        ],
    }
    totals = mode_totals([build], [(original, build)])
    assert totals["same_default_core"] == 1
    assert totals["same_final_core_order"] == totals["same_component_path"] == 0
    assert totals["beam_defaults"] == 0 and totals["beam_variants"] == 1
    assert totals["mean_within_group_core_distance"] == pytest.approx(0.4)
