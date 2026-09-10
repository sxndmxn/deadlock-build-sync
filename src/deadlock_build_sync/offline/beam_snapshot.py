"""Fingerprint producer code and reject incompatible beam resume requests."""

from hashlib import sha256
from pathlib import Path

from deadlock_build_sync.guide_generator import generator_record
from deadlock_build_sync.snapshot import sha256_json


def beam_implementation_record() -> dict[str, object]:
    root = Path(__file__).resolve().parent.parent
    files = {
        str(path.relative_to(root)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.suffix in {".py", ".sql"}
    }
    return {"files": files, "sha256": sha256_json(files)}


def beam_resume_record() -> dict[str, object]:
    return {
        "generator": generator_record(),
        "implementation": beam_implementation_record(),
    }


def require_beam_resume(manifest: dict[str, object]) -> None:
    if manifest.get("beam_resume") != beam_resume_record():
        raise ValueError("Beam resume settings or code differ. Start a new --run-id.")
