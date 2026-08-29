#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from deadlock_build_sync.artifacts import atomic_write_json
from deadlock_build_sync.narratives import (
    NARRATIVE_GENERATOR_VERSION,
    NARRATIVE_SCHEMA_VERSION,
    NarrativeError,
    deterministic_build_description,
)
from deadlock_build_sync.strategy_context import (
    StrategyContextError,
    validate_strategy_context_document,
)

type BuildKey = tuple[int, str]

SCHEMA_VERSION = NARRATIVE_SCHEMA_VERSION
GENERATOR_VERSION = NARRATIVE_GENERATOR_VERSION


class GenerationError(RuntimeError):
    """Raised when deterministic description generation cannot continue."""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate reviewed deterministic Deadlock build descriptions."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--hero",
        action="append",
        help="limit generation to a hero name or numeric ID; repeatable",
    )
    parser.add_argument("--force", action="store_true")
    return parser.parse_args(argv)


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise GenerationError(f"could not read {path}: {error}") from error
    if not isinstance(value, dict):
        raise GenerationError(f"{path} did not contain a JSON object")
    return value


def _selected_heroes(
    document: dict[str, Any],
    selectors: list[str] | None,
) -> list[dict[str, Any]]:
    heroes = document.get("heroes")
    if not isinstance(heroes, list) or not all(
        isinstance(hero, dict) for hero in heroes
    ):
        raise GenerationError("strategy context is missing its heroes array")
    if not selectors:
        return heroes
    normalized = {selector.casefold().replace(" ", "") for selector in selectors}
    selected = [
        hero
        for hero in heroes
        if str(hero.get("hero_id")) in normalized
        or str(hero.get("hero") or "").casefold().replace(" ", "") in normalized
    ]
    matched = {
        value
        for hero in selected
        for value in (
            str(hero.get("hero_id")),
            str(hero.get("hero") or "").casefold().replace(" ", ""),
        )
    }
    missing = normalized - matched
    if missing:
        raise GenerationError(
            f"hero selector(s) not found: {', '.join(sorted(missing))}"
        )
    return selected


def _build_key(entry: dict[str, Any]) -> BuildKey | None:
    hero_id = entry.get("hero_id")
    path_id = entry.get("path_id")
    if not isinstance(hero_id, int) or not isinstance(path_id, str) or not path_id:
        return None
    return hero_id, path_id


def _existing_entries(path: Path) -> dict[BuildKey, dict[str, Any]]:
    if not path.is_file():
        return {}
    heroes = _load_object(path).get("heroes")
    if not isinstance(heroes, list):
        return {}
    entries: dict[BuildKey, dict[str, Any]] = {}
    for entry in heroes:
        if not isinstance(entry, dict):
            continue
        key = _build_key(entry)
        if key is not None:
            entries[key] = entry
    return entries


def deterministic_narrative(hero: dict[str, Any]) -> dict[str, Any]:
    """Create one exact-identity build description entry.

    Returns:
        A JSON-compatible artifact entry.

    Raises:
        GenerationError: If required identity or description data is missing.

    """
    identity_fields = (
        "hero_id",
        "path_id",
        "snapshot_id",
        "policy_id",
        "context_sha256",
        "narrative_basis_sha256",
    )
    if any(hero.get(field) in {None, ""} for field in identity_fields):
        raise GenerationError("strategy context omitted exact description identity")
    try:
        description = deterministic_build_description(hero)
    except NarrativeError as error:
        raise GenerationError(str(error)) from error
    return {
        "hero_id": int(hero["hero_id"]),
        "path_id": str(hero["path_id"]),
        "hero": str(hero.get("hero") or hero["hero_id"]),
        "snapshot_id": str(hero["snapshot_id"]),
        "policy_id": str(hero["policy_id"]),
        "context_sha256": str(hero["context_sha256"]),
        "narrative_basis_sha256": str(hero["narrative_basis_sha256"]),
        "generator_version": GENERATOR_VERSION,
        "build_description": description,
    }


def validated_reusable_entries(
    existing: dict[BuildKey, dict[str, Any]],
    source_heroes: dict[BuildKey, dict[str, Any]],
) -> dict[BuildKey, dict[str, Any]]:
    """Return entries that equal the current deterministic result.

    Returns:
        Reusable entries keyed by hero and path.

    """
    reusable: dict[BuildKey, dict[str, Any]] = {}
    for build_key, entry in existing.items():
        hero = source_heroes.get(build_key)
        if hero is None:
            continue
        try:
            expected = deterministic_narrative(hero)
        except GenerationError:
            continue
        if entry == expected:
            reusable[build_key] = entry
    return reusable


def _artifact_document(
    source: dict[str, Any],
    generated: dict[BuildKey, dict[str, Any]],
    *,
    requested_hero_ids: set[int],
) -> dict[str, Any]:
    manifest = source["snapshot_manifest"]
    source_exclusions = source.get("exclusions")
    exclusions = [
        exclusion
        for exclusion in source_exclusions or []
        if isinstance(exclusion, dict)
        and exclusion.get("hero_id") in requested_hero_ids
    ]
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "generator": "deadlock-build-sync deterministic description",
        "generator_version": GENERATOR_VERSION,
        "source_context_sha256": source.get("source_context_sha256"),
        "snapshot_id": manifest.get("snapshot_id"),
        "patch": source.get("patch"),
        "cohort": {
            "client_version": manifest.get("client_version"),
            "match_mode": manifest.get("match_mode"),
            "game_mode": manifest.get("game_mode"),
            "rank_range": manifest.get("rank_range"),
            "as_of_timestamp": manifest.get("as_of_timestamp"),
        },
        "requested_hero_ids": sorted(requested_hero_ids),
        "exclusions": exclusions,
        "heroes": [
            generated[key] for key in sorted(generated) if key[0] in requested_hero_ids
        ],
    }


def generate_document(
    source: dict[str, Any],
    selected: list[dict[str, Any]],
    existing: dict[BuildKey, dict[str, Any]],
    *,
    include_all_exclusions: bool,
    force: bool,
) -> dict[str, Any]:
    """Create a complete deterministic description artifact.

    Returns:
        The validated artifact document.

    """
    requested_hero_ids = {int(hero["hero_id"]) for hero in selected}
    if include_all_exclusions:
        requested_hero_ids.update(
            int(exclusion["hero_id"])
            for exclusion in source.get("exclusions") or []
            if isinstance(exclusion, dict) and isinstance(exclusion.get("hero_id"), int)
        )
    source_heroes = {
        (int(hero["hero_id"]), str(hero["path_id"])): hero for hero in selected
    }
    generated = {} if force else validated_reusable_entries(existing, source_heroes)
    for index, hero in enumerate(selected, start=1):
        build_key = int(hero["hero_id"]), str(hero["path_id"])
        action = "reuse" if build_key in generated else "write"
        if build_key not in generated:
            generated[build_key] = deterministic_narrative(hero)
        print(
            f"[{index}/{len(selected)}] {action} {hero.get('hero')} / "
            f"{hero.get('path_label') or hero.get('path_id')}",
            file=sys.stderr,
        )
    return _artifact_document(
        source,
        generated,
        requested_hero_ids=requested_hero_ids,
    )


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        source = _load_object(args.input)
        try:
            validate_strategy_context_document(source)
        except StrategyContextError as error:
            raise GenerationError(str(error)) from error
        selected = _selected_heroes(source, args.hero)
        document = generate_document(
            source,
            selected,
            _existing_entries(args.output),
            include_all_exclusions=args.hero is None,
            force=args.force,
        )
        atomic_write_json(args.output, document)
        print(f"Wrote {len(document['heroes'])} description(s): {args.output}")
        return 0
    except GenerationError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
