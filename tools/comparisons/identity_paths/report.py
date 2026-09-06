"""Readable core and path previews, including abstentions and evidence limits."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def window(values: list | None, divisor: float = 1) -> str:
    if values is None:
        return "unknown"
    return f"{values[0] / divisor:,.1f}–{values[2] / divisor:,.1f}"


def preview(row: dict) -> list[str]:
    status = (
        "SUPPORTED CORE-PATH PREVIEW"
        if row["complete_preview"]
        else "CANDIDATE — INCOMPLETE EVIDENCE"
    )
    validation = row["core_validation"]
    lines = [
        f"### {row['hero']} / {row['arm']} / {row['identity_id']}",
        "",
        f"**{status}**",
        "",
        "Core: " + " + ".join(row["names"]),
        "",
        f"Core catalog cost: {row['cost']:,}. Later owners: {validation['owners']:,}; observed wins: {percent(validation['win_rate'])}.",
        f"Core gate: {row['passes_core_gate']}; mechanics explanation: {row['tactics']['supported_focus']}; sequence gate: {row['passes_sequence_gate']}.",
        "",
    ]
    if row["preview_rejections"]:
        lines.extend([
            "Incomplete because: " + "; ".join(row["preview_rejections"]) + ".",
            "",
        ])
    focuses = row["tactics"]["focuses"]
    for focus in focuses:
        items = ", ".join(item["name"] for item in focus["items"])
        abilities = ", ".join(ability["name"] for ability in focus["abilities"])
        lines.append(
            f"- Shared documented **{focus['channel']}** language: {items}; kit references: {abilities}."
        )
    if focuses:
        lines.extend([
            "",
            "This is a text-based mechanics explanation, not measured synergy. Exact descriptions and asset references are in the JSON.",
            "",
        ])
    path = row["path"]
    if not path["order"]:
        return [*lines, f"No supported order: {path['reason']}.", ""]
    for fold, evidence in (
        ("Discovery", path["discovery"]),
        ("Selection", path["selection"]),
        ("Validation", row["order_validation"]),
    ):
        lines.append(
            f"{fold} full core order: {evidence['ordered_owners']:,}/{evidence['owners']:,} owners ({percent(evidence['share'])})."
        )
    lines.extend([
        "",
        "| Step | Purchase | Role | Incremental souls | Observed minutes (IQR) | Observed net worth (IQR) |",
        "| ---: | --- | --- | ---: | --- | --- |",
    ])
    for index, action in enumerate(path["actions"], 1):
        timing = action["timing"]
        lines.append(
            f"| {index} | {action['name']} | {action['role']} | {action['incremental_cost']:,} | {window(timing['time_seconds_q25_q50_q75'], 60)} | {window(timing['net_worth_q25_q50_q75'])} |"
        )
    lines.extend([
        "",
        "Core ordering is observed; component ordering follows catalog dependencies. Timing ranges describe discovery owners and may overlap. They are not optimal buying windows, and net worth is not spendable souls.",
        "",
    ])
    return lines


def render(report: dict, runs: Path) -> None:
    lines = [
        "# Automatic identities and core purchase paths",
        "",
        "Local exploratory comparison. No Steam or production build was changed.",
        "",
        f"{report['unique_hypotheses']} unique frozen hero/core hypotheses; {report['unique_validated_cores']} passed the corrected later core gate.",
        "",
        "| Configuration | Nominees | Core gate | Explained identities | Sequence gate | Legal paths | Complete previews | Core coverage |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for arm, result in report["arms"].items():
        lines.append(
            f"| {arm} | {result['nominated']} | {result['validated_cores']} | {result['explained_identities']} | {result['supported_orders']} | {result['legal_paths']} | {result['complete_previews']} | {percent(result['coverage'])} |"
        )
    lines.extend([
        "",
        "A uses Eclat with pairwise ordering; B adds Leiden consolidation; C replaces pairwise ranking with PrefixSpan full-order support. Coverage is deduplicated within each arm. Different arms can cover different populations; observed win rates do not rank policies.",
        "",
        "## Hero coverage",
        "",
    ])
    for hero, (name, _) in report["heroes"].items():
        rows = [row for row in report["previews"] if row["hero_id"] == int(hero)]
        completed = {row["identity_id"] for row in rows if row["complete_preview"]}
        lines.append(
            f"- **{name}:** {len(rows)} arm nominations; {len(completed)} unique complete previews."
            + (" No core cleared selection." if not rows else "")
        )
    lines.extend(["", "## Detailed previews", ""])
    for row in report["previews"]:
        lines.extend(preview(row))
    lines.extend([
        "## Limits",
        "",
        "This is a fixed 20-minute survivor cohort from a snapshot spanning balance changes. Later validation was examined in earlier research. Wealth adjustment may condition on earlier item effects and does not remove all confounding. Core membership conditions the historical purchase sample; no causal purchase or timing effect is estimated. Mechanic text overlap requires tactical scrutiny. Standalone optional openings, late-game completion and contextual item choices are not included.",
        "",
    ])
    (runs / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    for hero, name in ((6, "Abrams"), (12, "Kelvin")):
        detail = [
            f"# {name} core purchase-path previews",
            "",
            "These are local research previews through a midgame core, not complete match guides.",
            "",
        ]
        selected = [row for row in report["previews"] if row["hero_id"] == hero]
        for row in selected:
            detail.extend(preview(row))
        if not selected:
            detail.extend(["No candidate passed selection. No build was forced.", ""])
        (runs / f"{name.upper()}.md").write_text("\n".join(detail), encoding="utf-8")
