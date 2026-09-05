"""Render reproducible core-discovery evidence and contextual observations."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


def rate(value: float | None) -> str:
    return "insufficient data" if value is None else f"{value:.1%}"


def render(report: dict, output: Path) -> None:
    lines = [
        "# Five automatic core-discovery algorithms",
        "",
        "Core identities are discovered from match data. Existing build labels and pools are not inputs.",
        "Outcome and support gates are shared by all five methods. Passing identifies an observational candidate for tactical review, not a causal win-rate improvement or a ready-to-install guide.",
        "",
        "## Algorithm comparison",
        "",
        "| Method | Fits | Candidate triples | Selection nominees | Later replicas | Validation coverage | Observed win rate in covered matches | Runtime |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for method, row in report["methods"].items():
        lines.append(
            f"| {method} | {row['fits_completed']} | {row['discovery_candidates_across_heroes']} | {row['nominated']} | {row['replicated']} | {row['coverage']:.1%} | {rate(row['covered_observed_win_rate'])} | {row['runtime_s']:.1f}s |"
        )
    lines += [
        "",
        "Coverage counts each hero-match once within a method, even when several cores overlap. Covered match win rates refer to different selected populations and cannot rank policy performance.",
        f"Across methods: {report['union_nominated_hypotheses']} unique nominated hero/core hypotheses; {report['union_replicated_cores']} pass the later validation gate.",
        "Two testing families each use Bonferroni alpha 0.025 across all unique nominated hypotheses. State-adjusted inference uses an approximate normal test.",
        "",
        "## Hero coverage",
        "",
        "| Hero | Group | Discovery | Selection | Validation | Eclat replicas | PrefixSpan replicas | NMF replicas | Bernoulli replicas | Leiden replicas |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for hero, (name, group) in report["hero_groups"].items():
        counts = report["data"]["heroes"][str(hero)]["rows"]
        replicas = [
            sum(
                core["hero_id"] == int(hero)
                and core["passes_observational_gate"]
                and method in core["methods"]
                for core in report["cores"].values()
            )
            for method in report["methods"]
        ]
        lines.append(
            f"| {name} | {group} | {counts['discovery']} | {counts['selection']} | {counts['validation']} | "
            + " | ".join(str(value) for value in replicas)
            + " |"
        )
    lines += [
        "",
        "## All frozen nominees",
        "",
        "Raw win intervals are ordinary 95% lower bounds. The gate also applies the family correction and comparable-state overlap requirements.",
        "",
        "| Hero | Core | Methods | Cost | Validation owners | Observed win | Win lower 95% | Adjusted difference | Gate |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for core in report["cores"].values():
        row = core["validation"]
        delta = row["adjusted"]["difference"]
        difference = (
            "insufficient overlap" if delta is None else f"{delta * 100:+.1f} pp"
        )
        state = (
            "passes"
            if core["passes_observational_gate"]
            else "; ".join(core["validation_rejections"])
        )
        lines.append(
            f"| {core['hero']} | {' + '.join(core['names'])} | {', '.join(core['methods'])} | {core['cost']} | {row['owners']} | {rate(row['win_rate'])} | {rate(row['win_lower_95'])} | {difference} | {state} |"
        )
    lines += [
        "",
        "## Context of replicated cores",
        "",
        "Ahead/even/behind use own wealth relative to the lobby mean at 20 minutes (+/-10%). These rates do not establish what to buy or which core to switch to. Cells with fewer than 50 core owners are omitted. Enemy-hero cells and order diagnostics are retained in evaluation.json.",
        "",
        "| Hero | Core | Behind | Even | Ahead |",
        "| --- | --- | --- | --- | --- |",
    ]
    for core in report["cores"].values():
        if not core["passes_observational_gate"]:
            continue
        cells = []
        for name in ("behind", "even", "ahead"):
            cell = core["context_cells"].get(name)
            cells.append(
                "<50 owners"
                if cell is None
                else f"{cell['win_rate']:.1%} (n={cell['owners']})"
            )
        lines.append(
            f"| {core['hero']} | {' + '.join(core['names'])} | "
            + " | ".join(cells)
            + " |"
        )
    lines += ["", "## Limitations", ""] + [f"- {limit}" for limit in report["limits"]]
    (output / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
