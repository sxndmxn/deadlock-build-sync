from __future__ import annotations

import json
import tempfile
from pathlib import Path

from deadlock_build_sync.artifacts import atomic_write_bytes
from deadlock_build_sync.build_evidence import load_build_evidence, select_hero_build


def _atomic_write(path: Path, document: dict[str, object]) -> None:
    content = (
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    ).encode()
    atomic_write_bytes(path, content)


def write_validated_evidence(path: Path, document: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".evidence-", dir=path.parent) as directory:
        candidate = Path(directory) / path.name
        _atomic_write(candidate, document)
        catalog = load_build_evidence(candidate)
        for builds in catalog.hero_builds.values():
            for build in builds:
                select_hero_build(build, list(catalog.assets))
        _atomic_write(path, document)
