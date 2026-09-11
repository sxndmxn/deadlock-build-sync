"""Write reviewable builds from the normal generation pipeline."""

from __future__ import annotations

from hashlib import sha256
from typing import TYPE_CHECKING

from .artifacts import atomic_write_bytes, atomic_write_json
from .cli_support import _build_preview_presentation
from .guide_groups import build_group_record
from .presentation_output import render_presentation_markdown, serialize_presentation
from .purchase_markdown import render_purchase_markdown

if TYPE_CHECKING:
    from pathlib import Path

    from .purchase_types import PurchaseGuide
    from .service import GeneratedGuides


def write_build_guides(
    directory: Path, guides: list[PurchaseGuide], generated: GeneratedGuides
) -> None:
    output = directory / "builds" / generated.manifest.snapshot_id
    output.mkdir(parents=True, exist_ok=True)
    index = ["# Builds", ""]
    entries: list[dict[str, object]] = []
    for guide in guides:
        if guide.purchase_guidance is None:
            raise ValueError("Generated build has no purchase guidance")
        identity = sha256(guide.path_id.encode()).hexdigest()[:16]
        stem = f"{guide.hero_id}-{identity}"
        presentation = _build_preview_presentation(guide, generated)
        content = serialize_presentation(presentation)
        body = render_presentation_markdown(presentation)
        atomic_write_bytes(output / f"{stem}.md", body.encode())
        atomic_write_json(output / f"{stem}.steam.json", content)
        atomic_write_bytes(
            output / f"{stem}.details.md",
            render_purchase_markdown(guide, details=True).encode(),
        )
        entry: dict[str, object] = {
            "hero_id": guide.hero_id,
            "hero": guide.hero_name,
            "path_id": guide.path_id,
            "policy_id": guide.policy_id,
            "markdown": f"{stem}.md",
            "steam_json": f"{stem}.steam.json",
            "steam_build": content,
            "purchase_guidance": guide.purchase_guidance.as_dict(),
            "guide_group": build_group_record(guide),
            "steam_categories": content["categories"],
            "variant_path_ids": [
                member.path_id for member in (guide, *guide.variant_guides)
            ],
            "item_pool": {
                str(tier): [item.item_id for item in items]
                for tier, items in guide.tiers.items()
            },
        }
        entries.append(entry)
        index.append(f"- [{guide.hero_name} — {guide.path_label}]({stem}.md)")
    atomic_write_json(
        output / "guides.json",
        {
            "schema_version": 2,
            "snapshot_manifest": generated.manifest.as_dict(),
            "guides": entries,
        },
    )
    atomic_write_bytes(output / "INDEX.md", ("\n".join(index) + "\n").encode())
    atomic_write_json(
        directory / "builds.json",
        {
            "schema_version": 2,
            "snapshot_id": generated.manifest.snapshot_id,
            "directory": str(output),
            "guides": [
                {
                    key: value
                    for key, value in entry.items()
                    if key not in {"purchase_guidance", "guide_group"}
                }
                for entry in entries
            ],
        },
    )
