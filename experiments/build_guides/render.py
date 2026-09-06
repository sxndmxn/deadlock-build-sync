"""Full readable item pools, interleaved choices, and inspectable purchase paths."""

from __future__ import annotations

import json
from html import escape
from pathlib import Path


def name(guide: dict, item: int | None) -> str:
    return guide["catalog"][str(item)]["name"] if item is not None else "core complete"


def chain(guide: dict, items: list[int]) -> str:
    return " → ".join(name(guide, item) for item in items) or "Core complete"


def anchor(guide: dict, card: dict) -> str:
    path = guide["default_path"]["actions"]
    index = card["placement"]["after_step"]
    if index is None:
        return "Timing unknown"
    if index == 0:
        return f"Before {path[0]['name']}" if path else "No default path"
    if index == len(path):
        return f"After {path[-1]['name']} (core complete)"
    return f"Between {path[index - 1]['name']} and {path[index]['name']}"


def card_lines(guide: dict, card: dict) -> list[str]:
    title = f"### {card['name']} — {anchor(guide, card)}"
    lines = [title, "", "**Consider when:** " + "; ".join(card["triggers"]) + "."]
    lines.append("**Mechanic:** " + card["mechanics"] + ".")
    if card["blocked_reason"]:
        return [*lines, "**Blocked:** " + card["blocked_reason"] + ".", ""]
    branch = card["branch"]
    upgraded = card["upgrades_core"]
    lines.extend([
        "**UPGRADE CORE:** " + chain(guide, upgraded) + " → " + card["name"] + "."
        if upgraded
        else "**Change:** add this choice; keep the core.",
        f"**Budget:** +{card['extra_path_cost']:,} souls over the default path. "
        + (
            f"Delays {name(guide, card['delays_item'])}; then resume the remaining core."
            if card["delays_item"] is not None
            else "This is an extension after the core."
        ),
    ])
    if card["rebought_components"]:
        lines.append(
            "**Shared component cost:** buy "
            + chain(guide, card["rebought_components"])
            + " again after it is consumed; this choice does not replace the core's other upgrade."
        )
    lines.extend([
        "**Path with this choice:** "
        + chain(guide, [x["item_id"] for x in branch["actions"]])
        + ".",
        "**Ending inventory:** "
        + ", ".join(name(guide, item) for item in branch["final_inventory"])
        + ".",
        "**Skip:** " + card["skip"] + ".",
        f"Placement: {card['placement']['basis']}; {card['placement']['support']}/{card['placement']['buyers']} buyers in the observed interval.",
        "",
    ])
    return lines


def option_line(guide: dict, option: dict, cards: dict) -> str:
    card = cards[option["item_id"]]
    route = chain(guide, option["route"])
    title = ("UPGRADE " if option["kind"] == "upgrade" else "") + route
    next_step = (
        f"then {name(guide, card['delays_item'])}"
        if card["delays_item"] is not None
        else "after the core"
    )
    line = f"- **{title}** — +{card['extra_path_cost']:,} souls; {next_step}."
    if card["rebought_components"]:
        line += " Includes another " + chain(guide, card["rebought_components"]) + "."
    if len(option["stages"]) > 1:
        stops = ", ".join(
            f"{name(guide, stage['item_id'])} (+{stage['extra_path_cost']:,} total)"
            for stage in option["stages"][:-1]
        )
        line += " You can stop at " + stops + "."
    line += " " + "; ".join(card["triggers"]) + "."
    return line


def purchase_lines(guide: dict) -> list[str]:
    lines = ["## Purchase path and choices", ""]
    path = guide["default_path"]["actions"]
    cards = {card["item_id"]: card for card in guide["choices"]}
    for checkpoint in guide["checkpoints"]:
        index = checkpoint["after_step"]
        if index:
            action = path[index - 1]
            lines.extend([
                f"**{index}. {action['name']} — {action['incremental_cost']:,} souls**",
                "",
            ])
        for decision in checkpoint["decisions"]:
            label = decision["kind"].replace("_", " ").upper()
            if decision["relationship"] == "upgrade_fork":
                label += " UPGRADE"
            lines.extend([f"**{label} — {decision['purpose']}**", ""])
            lines.extend(
                option_line(guide, option, cards) for option in decision["options"]
            )
            lines.append("")
    return lines


def unplaced_lines(guide: dict) -> list[str]:
    cards = {card["item_id"]: card for card in guide["choices"]}
    lines = []
    if guide["unplaced_choices"]:
        lines.extend([
            "## Timing unknown",
            "",
            "These items remain in the pool. Choose a legal purchase position before adding one to the path.",
            "",
        ])
        for item in guide["unplaced_choices"]:
            card = cards[item]
            lines.append(
                f"- **{card['name']}** — {card['purpose']}; catalog cost {card['catalog_cost']:,} souls. {card['placement']['support']}/{card['placement']['buyers']} buyers in the most common interval."
            )
        lines.append("")
    if guide["blocked_choices"]:
        lines.extend(["## Purchases blocked", ""])
        for item in guide["blocked_choices"]:
            card = cards[item]
            lines.append(f"- **{card['name']}** — {card['blocked_reason']}.")
        lines.append("")
    return lines


def markdown(guide: dict, *, details: bool = False) -> str:
    status = (
        "Supported core and order; optional choices need outcome validation"
        if guide["core_path_supported"]
        else "Candidate for review — core/order evidence is insufficient"
    )
    lines = [
        f"# {guide['hero']} — {', '.join(guide['core_names'])}",
        "",
        f"**{status}.**",
        "",
        "Follow the core unless you need an optional effect. PICK ONE means the next purchase for that need. You can make other choices later.",
        "",
        "Core prices are incremental. Optional +cost is the extra total path cost, including required components and rebuys. An upgrade consumes its component and credits its cost.",
        "",
    ]
    if guide["default_path"]["reason"]:
        lines.extend(["Path limit: " + guide["default_path"]["reason"] + ".", ""])
    lines.extend(purchase_lines(guide))
    lines.extend(unplaced_lines(guide))
    lines.extend([
        "## Item pool",
        "",
        "These tiers contain the full pool. They are not a purchase order.",
        "",
    ])
    for tier, items in guide["item_pool"].items():
        lines.append(
            f"- **Tier {tier}:** "
            + (", ".join(name(guide, item) for item in items) or "No eligible items")
            + "."
        )
    forks = [group for group in guide["upgrade_groups"] if len(group["parents"]) > 1]
    if forks:
        lines.extend(["", "## Shared component forks", ""])
        for group in forks:
            options = " / ".join(name(guide, item) for item in group["parents"])
            lines.append(
                f"- **{name(guide, group['component'])} → {options}.** {group['note']}."
            )
    if details:
        lines.extend(["", "## What each choice changes", ""])
        for card in guide["choices"]:
            lines.extend(card_lines(guide, card))
        if guide["rejections"]:
            lines.extend([
                "Evidence limits: " + "; ".join(guide["rejections"]) + ".",
                "",
            ])
    lines.extend([
        "",
        "## Evidence and use",
        "",
        f"Each pool item has at least 20 discovery buyers; each tier has at most ten items. This guide uses {guide['discovery_owners']:,} discovery core owners.",
        "",
        "Choice timing describes past purchases. Groups describe item mechanics. Adoption order does not predict wins. Enemy and ahead/behind preferences remain unvalidated.",
        "",
        "Each option shows one complete route. Components shown at an earlier step keep their purchase position. Recalculate from actual inventory and cash when combining choices. Slots and active-item limits still apply.",
        "",
    ])
    return "\n".join(lines)


def html(guides: list[dict], title: str) -> str:
    template = Path(__file__).with_name("template.html").read_text(encoding="utf-8")
    payload = json.dumps(guides, allow_nan=False).replace("<", "\\u003c")
    return template.replace("__TITLE__", escape(title)).replace("__GUIDES__", payload)


def render(guides: list[dict], output: Path) -> None:
    for guide in guides:
        (output / f"{guide['identity_id']}.md").write_text(
            markdown(guide), encoding="utf-8"
        )
        (output / f"{guide['identity_id']}.details.md").write_text(
            markdown(guide, details=True), encoding="utf-8"
        )
        (output / f"{guide['identity_id']}.html").write_text(
            html([guide], guide["hero"]), encoding="utf-8"
        )
    for hero in sorted({guide["hero"] for guide in guides}):
        rows = [guide for guide in guides if guide["hero"] == hero]
        (output / f"{hero.upper().replace(' ', '_')}.html").write_text(
            html(rows, hero), encoding="utf-8"
        )
    index = [
        "# Discovered builds and item pools",
        "",
        "Local research guides. Supported cores and unvalidated choices are labeled separately.",
        "",
    ]
    for guide in guides:
        label = ", ".join(guide["core_names"])
        status = "supported core/path" if guide["core_path_supported"] else "candidate"
        index.append(
            f"- [{guide['hero']}: {label}]({guide['identity_id']}.md) — {status}; {len(guide['choices'])} pool choices."
        )
    (output / "INDEX.md").write_text("\n".join(index) + "\n", encoding="utf-8")
