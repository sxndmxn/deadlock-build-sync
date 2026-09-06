"""Read frozen inputs, preserve experiment versions, and bind provenance."""

from __future__ import annotations

import json
from pathlib import Path

from deadlock_build_sync.offline.config import sha256_json

from experiments.core_discovery.discover import source_fingerprints
from experiments.qdfm.extract import fingerprint

FIT_MODULES = (
    "config",
    "mining",
    "grouping",
    "tactics",
    "orders",
    "storage",
    "purchase_data",
    "fit",
)


def read_json(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def producer_hashes() -> dict:
    directory = Path(__file__).parent
    paths = [directory / f"{name}.py" for name in FIT_MODULES]
    paths += [directory / name for name in ("PROTOCOL.md", "pyproject.toml", "uv.lock")]
    paths += list(Path("src/deadlock_build_sync").glob("mechanics*.py"))
    paths += [
        Path("src/deadlock_build_sync/offline/production_sequence.py"),
        Path("experiments/qdfm/state.py"),
    ]
    return {
        "identity_paths": {str(path): fingerprint(path) for path in sorted(paths)},
        "core_discovery": source_fingerprints(),
    }


def verify_data(directory: Path) -> dict:
    manifest = read_json(directory / "manifest.json")
    for name, expected in manifest["files"].items():
        if fingerprint(directory / name) != expected:
            raise ValueError(f"Frozen dataset changed: {name}")
    if (
        manifest["test_fold_read"]
        or manifest["build_labels_used"]
        or manifest["cross_partition_matches"]
    ):
        raise ValueError("Dataset violates the identity experiment partition contract")
    return manifest


def source_hashes(source: Path) -> dict:
    paths = [source / "manifest.json"]
    paths += [
        source / "raw" / name
        for name in ("analysis.duckdb", "items.json", "items-all.json", "heroes.json")
    ]
    return {str(path): fingerprint(path) for path in paths}


def verify_original_assets(source: Path, recorded: dict) -> None:
    for name in ("items.json", "items-all.json", "heroes.json"):
        if sha256_json(read_json(source / "raw" / name)) != recorded[name]:
            raise ValueError(f"Original asset changed: {name}")


def verify_run(runs: Path) -> tuple[dict, dict]:
    manifest = read_json(runs / "manifest.json")
    if manifest["producer_sha256"] != producer_hashes():
        raise ValueError("Frozen fitting sources changed")
    if manifest["data_manifest_sha256"] != fingerprint(
        Path(manifest["directory"]) / "manifest.json"
    ):
        raise ValueError("Frozen data manifest changed")
    verify_data(Path(manifest["directory"]))
    for path, expected in manifest["source_sha256"].items():
        if fingerprint(Path(path)) != expected:
            raise ValueError(f"Frozen input changed: {path}")
    for name, expected in manifest["files"].items():
        if fingerprint(runs / name) != expected:
            raise ValueError(f"Frozen model or nomination changed: {name}")
    return manifest, read_json(runs / "nominations.json")
