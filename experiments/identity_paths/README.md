# Automatic identities and core purchase paths

This local experiment implements the accepted Eclat → Leiden → PrefixSpan
plan. Build identities are discovered outputs. It compares Eclat/pairwise,
grouped/pairwise, and grouped/PrefixSpan configurations on all nine pilot heroes.
The original five-method implementation, artifacts and production interfaces
remain unchanged. Read [PROTOCOL.md](PROTOCOL.md) for fixed choices and limits.
Read [RESULTS.md](RESULTS.md) for the completed comparison and concrete findings.

## Reproduce

Run from the repository root with the documented uv version `>=0.12,<0.13`.
On a host with an older uv, prefix commands with
`uv tool run --from 'uv>=0.12,<0.13' uv` instead of `uv`.

```bash
uv sync --project experiments/identity_paths --frozen
uv run --project experiments/identity_paths python -m experiments.identity_paths.run fit \
  --directory generated/core-discovery/data --output generated/identity-paths/trial-v1
uv run --project experiments/identity_paths python -m experiments.identity_paths.run evaluate \
  --output generated/identity-paths/trial-v1
uv run --project experiments/identity_paths python -m experiments.identity_paths.audit \
  --runs generated/identity-paths/trial-v1
uv run --project experiments/identity_paths python -m experiments.identity_paths.synthetic \
  --output generated/identity-paths/synthetic-v1
uv run --project experiments/identity_paths python -m pytest experiments/identity_paths -W error
```

Use new output paths when repeating a fit or synthetic run. Evaluation refuses
to replace a prior evaluation. Verify the source snapshot is still present at
the location recorded in the frozen data manifest. No API key, network analytics
fetch or Steam session is required. The environment installs the local repository
as an editable dependency to reuse its component mechanics and pairwise baseline.

## Artifacts and admission

- `hero-*.json`: Eclat candidates and parent retention, discovery graph edges,
  Leiden seeds, complete-link groups, all selection scores/rejection reasons.
- `nominations.json`: exact representative cores, source-backed mechanic
  descriptions, fixed orders, component actions and discovery timing evidence.
- `manifest.json`: source/data/code hashes fixed before later evaluation.
- `evaluation.json`: separate core, explanation, sequence and complete-preview
  gates plus all three arms' coverage, duplicate overlap and runtimes.
- `REPORT.md`, `ABRAMS.md`, `KELVIN.md`: readable comparisons and purchase paths.
- `audit.json`: independent SQL outcomes/adjustment/order counts, original-event
  inventory replays, component arithmetic, and partition checks.
- Synthetic `report.json`: planted-core recovery and all three arms, with
  generator/implementation fingerprints. It reuses the documented test fixtures.

JSON artifacts use schema version 1; identity IDs bind hero and sorted exact
core IDs. Group membership never changes which items define that exact core.
Grouping represents strong co-ownership similarity, not proof of one playstyle.
The mechanics screen reports shared documented vocabulary with the hero kit,
not a measured synergy effect; previews remain research candidates for review.

Only 4–6-item midgame cores and their necessary component purchases are included.
Standalone optional openings, late-game extensions and opponent/wealth-dependent
choices are deferred. Timing ranges are observational and may overlap. They
are not a schedule guaranteed affordable from liquid souls. An unsupported
core or order produces explicit abstention rather than a fabricated guide.

Run the full repository fast gate from `docs/quality-gates.md` and the experiment
lock, dependency, lint/complexity and test checks before handoff. Unit tests and
synthetic recovery do not certify live builds or causal purchase improvements.
