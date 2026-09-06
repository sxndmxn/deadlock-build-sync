# Purchase guidance handoff — 2026-09-06

The purchase-guidance milestone now includes normal application integration.
Use branch `feat/build-purchase-guidance` in `/Users/sandmac/code/deadlock-build-sync-qdfm`.
Do not reset or replace this checkout.

## Normal application integration

`uv run build --hero kelvin` and `uv run deadlock-build-sync build --hero kelvin`
generate the normal admitted build with Markdown and JSON purchase guidance.
They share artifact generation with `sync`, and do not discover or access Steam.
`preview --format markdown` also renders this guidance. The runtime code is in
`src/deadlock_build_sync/purchase_*.py` and has no experiment imports.

The offline producer exports a validated training-only purchase timing extension.
Older evidence shows unknown timing. The integration keeps normal core admission
and conditional outcome gates; experimental core discovery is not promoted.
Steam categories and the default Queue retain their existing contract. Complete
purchase guidance is exported with the build for review.

A parity audit matched all 714 legal research branches against the runtime
planner: positions, actions, component costs, rebuys, and ending inventories.
It checked 734 pool entries in 20 guides and 3,588 item-purpose results. Three
research guides with infeasible defaults were excluded from this runtime replay.
Their research artifacts and admission flags remain unchanged.
The report is `generated/build-guides/integration-checks/parity.json`.

Deptry and Tach are installed in the development group and run in CI.
Negative probes confirmed that undeclared dependencies and direct imports from
runtime code into the offline producer fail. See `docs/quality-gates.md` for the
checked boundaries.

Final integration checks: 1,161 repository tests and 69 affected experiment tests
passed. All 16 fast commands passed, including dependency, type, coverage,
complexity, dead-code, duplicate-code, and packaging checks. The wheel was
inspected and exercised outside the checkout without analysis dependencies.
The final gate logs are under `generated/build-guides/integration-checks/gates/`.

## Product direction

The system discovers build identities from supported cores. Users do not invent
or select an identity before discovery. The next stages will validate more cores
and then evaluate purchases against enemy threats and relative wealth.

Tier lists are the full item pool. A build also needs its core purchase path,
optional decisions, component routes, costs, and remaining purchases.
Show every matching option. Do not apply a shortlist limit.
The user reads Markdown on a phone through tmux and Termius.
Use ASD-STE100 Simplified Technical English in user responses.

## Completed behavior

- Guides use schema version 2 and explicit OPTIONAL, PICK ONE, and UPGRADE decisions.
- Need groups use the main documented effect. Minor bonus stats do not select the group.
- Components and parents form routes. They do not compete as PICK ONE alternatives.
- Routes show intermediate stopping costs and shared-component rebuys.
- Unsupported purchase timing stays unknown. It does not move after the core.
- State files accept explicit `placement_overrides` for selected items.
- The planner checks actual inventory, cash, component order, slots, and active limits.
- The loader verifies fingerprints before adapting version 1 guides in memory.
- `show --guide ... --format markdown` prints the phone view. `--details` prints complete branches.
- HTML uses the same decisions as Markdown.

The experiment README contains the commands and schema contract.
The main policy requirements document records the presentation rules.
Frozen discovery, core nominations, default paths, evidence flags, and pools remain unchanged.

## Artifacts and evidence

The final output is `generated/build-guides/review-v4/`.
Earlier reviews remain available, including the comparison baseline `review-v2/`.
The final manifest records producer and artifact fingerprints. All fingerprints matched at handoff.

- 23 guides and 849 pool entries are preserved.
- 714 individual purchase branches passed independent replay and cost checks.
- 26 pool entries have unknown timing.
- 109 entries have a position but no executable branch because the default path fails timing constraints.
- The audit found no errors and independently verified all pool buyer counts from SQL.
- A pair audit checked 12,633 combinations. It replayed 12,631 legal combinations.
- Two combinations were rejected because the selected component followed its upgrade.
- All 69 affected experiment tests passed.
- All 14 repository fast gates passed, including 1,125 repository tests.
- The experiment complexity check and `git diff --check` passed.
- DOM checks passed for 46 guide views and 1,698 item clicks. No real-browser visual check was available.

Reports are in `generated/build-guides/gates-v4/` and the final review's `audit.json`.
Four actual-inventory examples are in `generated/build-guides/examples-v4/`.
These cover Kelvin's Trophy Collector detour, Abrams's Spirit Snatch upgrade,
an explicit McGinnis timing choice, and both Viscous component forks.

## Hero examples and remaining limits

- Kelvin: `12-8c4e6b175aa94f55`, candidate.
- Abrams: `6-f40527b18532004c`, supported core and order.
- McGinnis: `8-3b4401a5a63cb513`, candidate.
- Viscous: `35-053119a2038402d0`, candidate.

Abrams remains the only automatically admitted default in this frozen experiment.
Legal purchase execution does not prove an outcome benefit. Optional outcome
preferences and the complete policy remain unvalidated.
The data span balance changes and contain an already inspected validation period.
The test fold was not read for this work.
No new models were fitted. No Steam files were changed.

Next, validate additional cores on fresh, patch-compatible data. Then evaluate
enemy and wealth decisions with the existing conditional evidence gates.
