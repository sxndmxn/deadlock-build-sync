"""Record and enforce the experiment boundary before test evaluation."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[2]


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def code_identity() -> dict[str, str]:
    paths = [
        *CODE_ROOT.glob("tools/purchase_search/*.py"),
        *CODE_ROOT.glob("tools/purchase_search/sql/*.sql"),
        *CODE_ROOT.glob("src/deadlock_build_sync/mechanics*.py"),
        CODE_ROOT / "src/deadlock_build_sync/offline/inventory_reconstruction.py",
        CODE_ROOT / "pyproject.toml",
        CODE_ROOT / "uv.lock",
    ]
    return {
        str(path.relative_to(CODE_ROOT)): file_digest(path) for path in sorted(paths)
    }


def verify_frozen(path: Path | None, fingerprint: str) -> dict[str, object]:
    if path is None or not path.is_file():
        raise ValueError("Test access requires a frozen experiment specification")
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema") != 1 or document.get("data_fingerprint") != fingerprint:
        raise ValueError("The frozen specification does not match the experiment data")
    if document.get("code") != code_identity():
        raise ValueError("Experiment code changed after the test configuration freeze")
    return document


def benchmark_settings(arguments: argparse.Namespace) -> dict[str, object]:
    return {
        name: getattr(arguments, name)
        for name in (
            "mode",
            "methods",
            "heroes",
            "depth",
            "alternatives",
            "sample_size",
            "diversity",
            "prior",
            "cost_exponent",
            "stateless",
            "joint_support",
        )
    }


def verify_benchmark(arguments: argparse.Namespace, fingerprint: str) -> None:
    document = verify_frozen(arguments.frozen, fingerprint)
    if benchmark_settings(arguments) not in document["allowed_benchmarks"]:
        raise ValueError("The requested test benchmark was not frozen")
    training = arguments.data / "train/statistics.json"
    if file_digest(training) != document["training_statistics_sha256"]:
        raise ValueError("Training statistics changed after the configuration freeze")
    expected = document["structures_sha256"]
    actual = file_digest(arguments.structures) if arguments.structures else None
    if actual != expected:
        raise ValueError("Structure proposals changed after the configuration freeze")


def freeze_specification(
    data: Path, structures: Path | None, settings: Path, output: Path
) -> None:
    manifest = json.loads((data / "train/manifest.json").read_text(encoding="utf-8"))
    document = {
        "schema": 1,
        "created_at": datetime.now(UTC).isoformat(),
        "data_fingerprint": manifest["fingerprint"],
        "patch": manifest["patch"],
        "code": code_identity(),
        "training_statistics_sha256": file_digest(data / "train/statistics.json"),
        "structures_sha256": file_digest(structures) if structures else None,
        "allowed_benchmarks": json.loads(settings.read_text(encoding="utf-8")),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(document, indent=2) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Freeze purchase-search settings")
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--structures", type=Path)
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    freeze_specification(
        arguments.data, arguments.structures, arguments.settings, arguments.output
    )


if __name__ == "__main__":
    main()
