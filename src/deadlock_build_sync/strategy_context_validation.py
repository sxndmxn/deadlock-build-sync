from __future__ import annotations

import hashlib
import json

from .build_tags import FUNCTION_CLASSES
from .mechanics import extract_asset_mechanics
from .value_validation import integer, object_dict, object_list, object_rows

CONTEXT_SCHEMA_VERSION = 16
KIT_BASIS_SCHEMA_VERSION = 3
NARRATIVE_BASIS_SCHEMA_VERSION = 10
TIER_LABELS = {1: "I", 2: "II", 3: "III", 4: "IV"}


class StrategyContextError(ValueError):
    """Raised when an exported strategy context is malformed or was edited."""


def _validate_build_identity(
    entry: dict[str, object], manifest: dict[str, object]
) -> None:
    projection = object_dict(entry.get("projection"))
    build = object_dict(projection.get("build")) if projection is not None else None
    if build is None:
        raise StrategyContextError("strategy context has no build identity")
    ids = build.get("tag_ids")
    classes = build.get("tag_classes")
    labels = build.get("tag_labels")
    valid = (
        isinstance(ids, list)
        and len(ids) == 3
        and all(isinstance(value, int) and value > 0 for value in ids)
        and len(set(ids)) == 3
        and isinstance(classes, list)
        and len(classes) == 3
        and isinstance(labels, list)
        and len(labels) == 3
    )
    if not valid:
        raise StrategyContextError("strategy context has invalid build tags")
    if (
        not all(isinstance(value, str) and value.strip() for value in classes[:2])
        or classes[2] not in FUNCTION_CLASSES
        or build.get("tag_catalog_sha256") != manifest.get("build_tags_sha256")
        or not isinstance(build.get("archetype"), str)
        or not str(build["archetype"]).strip()
    ):
        raise StrategyContextError("strategy context has invalid build tags")


def _calculate_canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_item_mechanics_catalog(
    assets: list[dict[str, object]],
    item_ids: set[int],
) -> dict[str, dict[str, object]]:
    """Return deterministic mechanics for the referenced item IDs.

    Returns:
        A catalog keyed by decimal item ID.

    """
    assets_by_id = {
        integer(asset["id"]): asset
        for asset in assets
        if isinstance(asset.get("id"), int)
    }
    return {
        str(item_id): (
            extract_asset_mechanics(assets_by_id[item_id])
            if item_id in assets_by_id
            else {}
        )
        for item_id in sorted(item_ids)
    }


def calculate_item_mechanics_sha256(
    item_ids: list[int],
    catalog: dict[str, dict[str, object]],
) -> str:
    """Bind one hero to exactly its referenced mechanics records.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    return _calculate_canonical_hash({
        str(item_id): catalog[str(item_id)] for item_id in item_ids
    })


def _collect_context_item_records(entry: dict[str, object]) -> list[dict[str, object]]:
    records: list[dict[str, object]] = []
    core = object_dict(entry.get("core"))
    if core is not None:
        records.extend(object_rows(core.get("items")) or [])
        records.extend(object_rows(core.get("optional_core_substitution_cards")) or [])
    tiers = object_dict(entry.get("tiers"))
    if tiers is not None:
        for tier_items in tiers.values():
            records.extend(object_rows(tier_items) or [])
    return records


def _parse_item_mechanics_records(value: object) -> dict[str, dict[str, object]]:
    document = object_dict(value)
    if document is None:
        raise StrategyContextError("strategy context has invalid item mechanics")
    records: dict[str, dict[str, object]] = {}
    for key, value_record in document.items():
        record = object_dict(value_record)
        if (
            not key.isdecimal()
            or integer(key) <= 0
            or str(integer(key)) != key
            or record is None
        ):
            raise StrategyContextError("strategy context has invalid item mechanics")
        records[key] = record
    return records


def _validate_hero_item_mechanics(
    entry: dict[str, object],
    catalog: dict[str, dict[str, object]],
    hero_name: str,
) -> set[int]:
    item_ids = object_list(entry.get("item_mechanics_ids"))
    if item_ids is None:
        raise StrategyContextError(
            f"strategy context has invalid item mechanics references for {hero_name}"
        )
    normalized_ids = [item_id for item_id in item_ids if isinstance(item_id, int)]
    if (
        len(normalized_ids) != len(item_ids)
        or any(item_id <= 0 for item_id in normalized_ids)
        or normalized_ids != sorted(set(normalized_ids))
    ):
        raise StrategyContextError(
            f"strategy context has invalid item mechanics references for {hero_name}"
        )
    item_records = _collect_context_item_records(entry)
    if any(
        not isinstance(item.get("item_id"), int) or "mechanics" in item
        for item in item_records
    ) or normalized_ids != sorted({integer(item["item_id"]) for item in item_records}):
        raise StrategyContextError(
            f"strategy context item mechanics references differ for {hero_name}"
        )
    if "hero_description" in entry or "abilities" in entry:
        raise StrategyContextError(
            f"strategy context contains duplicate hero mechanics for {hero_name}"
        )
    try:
        item_digest = calculate_item_mechanics_sha256(normalized_ids, catalog)
    except KeyError as error:
        raise StrategyContextError(
            f"strategy context is missing item mechanics for {hero_name}"
        ) from error
    if entry.get("item_mechanics_sha256") != item_digest:
        raise StrategyContextError(
            f"strategy context item mechanics were edited for {hero_name}; "
            "run export-context again"
        )
    return set(normalized_ids)


def _build_narrative_basis(context: dict[str, object]) -> dict[str, object]:
    core = object_dict(context.get("core"))
    core_items = object_rows(core.get("items")) if core is not None else None
    policy = object_dict(context.get("policy"))
    policy_summary = None
    if policy is not None:
        policy_summary = {
            key: policy.get(key)
            for key in (
                "variant",
                "invariant_kit_id",
                "strategic_role",
                "abstentions",
            )
        }
    return {
        "schema_version": NARRATIVE_BASIS_SCHEMA_VERSION,
        "hero_id": context.get("hero_id"),
        "path_id": context.get("path_id"),
        "path_label": context.get("path_label"),
        "hero": context.get("hero"),
        "hero_mechanics": context.get("hero_mechanics"),
        "ability_policy": context.get("ability_policy"),
        "core_items": [
            {
                "item_id": item.get("item_id"),
                "item": item.get("item"),
                "tier": item.get("tier"),
            }
            for item in core_items or []
        ],
        "policy_summary": policy_summary,
    }


def _build_kit_basis(context: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": KIT_BASIS_SCHEMA_VERSION,
        "hero_id": context.get("hero_id"),
        "path_id": context.get("path_id"),
        "hero": context.get("hero"),
        "hero_mechanics": context.get("hero_mechanics"),
        "ability_policy": context.get("ability_policy"),
    }


def calculate_kit_basis_sha256(context: dict[str, object]) -> str:
    """Return the ability-only tactical fingerprint for one hero context.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    return _calculate_canonical_hash(_build_kit_basis(context))


def calculate_narrative_basis_sha256(context: dict[str, object]) -> str:
    """Return the tactical-basis fingerprint for one hero context.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    return _calculate_canonical_hash(_build_narrative_basis(context))


def calculate_context_sha256(context: dict[str, object]) -> str:
    """Return the full fingerprint for one hero context.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    payload = dict(context)
    payload.pop("context_sha256", None)
    return _calculate_canonical_hash(payload)


def calculate_source_context_sha256(document: dict[str, object]) -> str:
    """Return the fingerprint for a complete exported context document.

    Returns:
        A lowercase hexadecimal SHA-256 digest.

    """
    payload = dict(document)
    payload.pop("source_context_sha256", None)
    return _calculate_canonical_hash(payload)


type _StrategyContextHeader = tuple[
    dict[str, object],
    list[dict[str, object]],
    dict[str, dict[str, object]],
    list[int],
    list[dict[str, object]],
]


def _parse_strategy_context_header(
    document: dict[str, object],
) -> _StrategyContextHeader:
    manifest = object_dict(document.get("snapshot_manifest"))
    if manifest is None or not isinstance(manifest.get("snapshot_id"), str):
        raise StrategyContextError("strategy context is missing its snapshot manifest")
    heroes = object_rows(document.get("heroes"))
    if heroes is None:
        raise StrategyContextError("strategy context is missing its heroes array")
    item_mechanics = _parse_item_mechanics_records(document.get("item_mechanics"))
    requested = object_list(document.get("requested_hero_ids"))
    exclusions = object_rows(document.get("exclusions"))
    if requested is None or not all(isinstance(hero_id, int) for hero_id in requested):
        raise StrategyContextError("strategy context has invalid requested heroes")
    if exclusions is None or not all(
        isinstance(exclusion.get("hero_id"), int)
        and isinstance(exclusion.get("reason"), str)
        and bool(str(exclusion["reason"]).strip())
        for exclusion in exclusions
    ):
        raise StrategyContextError("strategy context has invalid exclusions")
    return (
        manifest,
        heroes,
        item_mechanics,
        [integer(value) for value in requested],
        exclusions,
    )


def _parse_context_build_key(entry: object) -> tuple[int, str]:
    hero = object_dict(entry)
    if hero is None:
        raise StrategyContextError("strategy context contains an invalid hero")
    hero_id = hero.get("hero_id")
    path_id = hero.get("path_id")
    if not isinstance(hero_id, int) or not isinstance(path_id, str) or not path_id:
        raise StrategyContextError("strategy context contains an invalid hero")
    return hero_id, path_id


def _validate_context_hero(
    entry: dict[str, object],
    manifest: dict[str, object],
    item_mechanics: dict[str, dict[str, object]],
) -> set[int]:
    hero_name = str(entry.get("hero") or entry["hero_id"])
    if entry.get("snapshot_id") != manifest["snapshot_id"]:
        raise StrategyContextError(f"strategy context snapshot differs for {hero_name}")
    referenced = _validate_hero_item_mechanics(entry, item_mechanics, hero_name)
    _validate_build_identity(entry, manifest)
    if entry.get("kit_basis_sha256") != calculate_kit_basis_sha256(entry):
        raise StrategyContextError(
            f"strategy context kit basis was edited for {hero_name}; "
            "run export-context again"
        )
    if entry.get("narrative_basis_sha256") != calculate_narrative_basis_sha256(entry):
        raise StrategyContextError(
            f"strategy context tactical basis was edited for {hero_name}; "
            "run export-context again"
        )
    if entry.get("context_sha256") != calculate_context_sha256(entry):
        raise StrategyContextError(
            f"strategy context was edited for {hero_name}; run export-context again"
        )
    return referenced


def _validate_context_coverage(
    seen_hero_ids: set[int],
    referenced_item_ids: set[int],
    requested: list[int],
    exclusions: list[dict[str, object]],
    item_mechanics: dict[str, dict[str, object]],
) -> None:
    excluded_ids = {integer(exclusion["hero_id"]) for exclusion in exclusions}
    if seen_hero_ids | excluded_ids != set(requested):
        raise StrategyContextError("strategy context does not cover requested heroes")
    if seen_hero_ids & excluded_ids:
        raise StrategyContextError("strategy context both includes and excludes a hero")
    if set(item_mechanics) != {str(item_id) for item_id in referenced_item_ids}:
        raise StrategyContextError("strategy context has unreferenced item mechanics")


def validate_strategy_context_document(document: dict[str, object]) -> None:
    """Verify schema, coverage, snapshot, hero, and full export fingerprints.

    Raises:
        StrategyContextError: If the document is malformed, stale, or edited.

    """
    if document.get("schema_version") != CONTEXT_SCHEMA_VERSION:
        raise StrategyContextError("unsupported strategy-context schema")
    manifest, heroes, item_mechanics, requested, exclusions = (
        _parse_strategy_context_header(document)
    )

    seen_build_keys: set[tuple[int, str]] = set()
    seen_hero_ids: set[int] = set()
    referenced_item_ids: set[int] = set()
    for entry in heroes:
        build_key = _parse_context_build_key(entry)
        hero_id = build_key[0]
        if build_key in seen_build_keys:
            raise StrategyContextError(
                f"strategy context contains duplicate build {hero_id}/{build_key[1]}"
            )
        seen_build_keys.add(build_key)
        seen_hero_ids.add(hero_id)
        referenced_item_ids.update(
            _validate_context_hero(entry, manifest, item_mechanics)
        )
    _validate_context_coverage(
        seen_hero_ids,
        referenced_item_ids,
        requested,
        exclusions,
        item_mechanics,
    )
    if document.get("source_context_sha256") != calculate_source_context_sha256(
        document
    ):
        raise StrategyContextError(
            "strategy context document was edited; run export-context again"
        )
