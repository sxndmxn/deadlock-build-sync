import base64
from pathlib import Path

import pytest

from deadlock_build_sync.cache import CacheError, read_cache
from deadlock_build_sync.kv3_binary import encode_binary_v4


def test_binary_v4_round_trip(tmp_path: Path) -> None:
    root = {
        "LastUsedBuilds": {"hero_kelvin": 33},
        "Favorites": [b"\x01\x02"],
        "Unpublished": [b"\x03\x04\x05"],
        "SavedLastUsed": [],
        "Nested": {"truth": True, "nothing": None, "float": 2.5, "empty": ""},
    }
    path = tmp_path / "cache.kv3"
    path.write_bytes(encode_binary_v4(root))
    decoded = read_cache(path)
    assert decoded == root
    assert path.read_bytes()[:4] == b"\x04\x33\x56\x4b"


def test_reads_upstream_binary_v5_fixture_before_validating_cache_shape(
    tmp_path: Path,
) -> None:
    fixture = Path(__file__).parent / "fixtures/keyvalues3-v5.kv3.b64"
    path = tmp_path / "v5.kv3"
    path.write_bytes(base64.b64decode(fixture.read_text(encoding="ascii")))

    with pytest.raises(CacheError, match="missing required sections"):
        read_cache(path)
