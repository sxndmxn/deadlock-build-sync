# Automatic identities and core paths: frozen comparison

Fixed before this experiment's fits and new outcome summaries, September 5,
2026. This implements the accepted plan. Existing identities and item pools
are never discovery inputs. All artifacts remain local; no production or
Steam installation is performed.

## Inputs and boundaries

Reuse `generated/core-discovery/data`: current inventory and latest acquisition
at strictly before 1,200 seconds, whole-match discovery/selection/validation
partitions, and discovery-only item eligibility max(100, 1% of hero rows).
Read original purchase events only for those observations, retaining both match
and player slot. Restrict discovery timing extraction to discovery members.
Sales and component consumption remain applied in the frozen replay; original
purchase logs retain sold items and rebuys. Verify data, source database/assets,
protocol, implementation, models and nominations by SHA-256.

The reserved test fold is never read. The existing validation period was
previously examined and spans balance changes; this is exploratory evidence.
No final wealth, future purchases, or outcome labels enter discovery, grouping
or order selection. Retrospective membership in a 20-minute core cohort does
not establish that the proposed earlier purchases improve outcomes.

## Candidates and identities

Eclat enumerates size 3–6 itemsets with at least 100 discovery owners. Each
item costs >=1,600, total cost <=19,200, joint lift >=1.1, and no ancestor pair.
Every extension must retain >=50% of at least one qualified parent’s owners;
parents are considered before the per-size reporting cap. Keep the top 50 per
size by joint prevalence times log joint lift, breaking ties by sorted IDs.
Triples are seeds only; representatives and grouping nodes have 4–6 items.

Leiden nodes are candidate cores. An edge requires >=2 shared items and owner
Jaccard >=0.70 on discovery observations; its weight is that Jaccard. Use
RBConfigurationVertexPartition, resolution 1, ten iterations, seeds 42/43/44.
An eligible pair must co-cluster in >=2 seeds. Starting with sorted singleton
nodes, greedily merge the highest mean-Jaccard eligible group pair only when
every cross-pair meets both the original edge and consensus conditions.
Break ties lexicographically by core IDs. This complete-link check prevents
transitive chains from asserting unsupported equivalence. A singleton is valid.

The existing shared selection gate requires >=100 owners, >=52% wins, ordinary
95% Wilson lower >50%, lift >=1.1 and positive standardized lower bound.
Strata and overlap requirements are unchanged from the five-method experiment.
Rank by adjusted lower bound, owner count, then IDs. Configuration A selects
the top three passing cores per hero. B/C select one passing representative
per group and the top three representatives per hero. Do not infer a union
core, force an identity for each hero, or replace nominees after validation.

Tactical evidence is reported separately from statistical admission. Reuse the
repository's controlled mechanic vocabulary, matching item descriptions with
the hero's signature-ability descriptions. At least two core items must share
one documented channel with the kit to provide a coherent-focus explanation.
Include exact asset references and matched text; this is a conservative text
screen, not a synergy score or proof of an interaction. Generic overlapping
language may remain ambiguous; missing explanation yields a statistical core,
not an admitted identity. This screen does not change outcome nominations or
their multiplicity denominator. No language model selects or installs builds.

## Three configurations and paths

A: Eclat + existing pairwise-agreement core-order ranking.
B: Eclat + Leiden + the same pairwise-order ranking.
C: Eclat + Leiden + PrefixSpan ordered core sequences.

Both order methods use latest acquisitions of the concurrently owned core,
strictly increasing timestamps, no order between same-second items. PrefixSpan
mines the full size-4–6 order within discovery owners, minimum support 20.
The pairwise baseline reuses the repository's exact agreement-order ranking.
Choose the first mechanically legal order in the method's fixed ranking;
PrefixSpan ranks by full sequence count, then IDs. Require >=20 and >=10% of
core owners in discovery and selection; a failed order remains unordered and
does not cause selection of a different core or validation-driven reranking.
Apply the same support floors to the frozen order in validation. Pairwise
agreement is a ranking baseline, not proof that the entire order is common.

Expand all required components using the existing scheduler. Validate every
action, direct component credit, duplicate ownership, active limits, zero flex
slots, and exact final inventory. Legal component rebuys after consumption are
allowed. Net worth is not cash; show incremental catalog cost separately.
For each action show discovery-only 25/50/75 percentiles of time and fresh
pre-purchase wealth (snapshot < purchase time, age <=300s), one latest matching
purchase per owner before their final core completion. Distinguish core-order
evidence from mechanics-required component ordering; missing timing is explicit.
Timing ranges are descriptions, not enforced optimal windows or affordability
claims. Standalone optional openings, late items and contextual choices are out.

## Validation, outputs and completion

Freeze candidates, groups, nominees, orders and discovery timing before opening
new validation summaries. Evaluate each unique nominated hero/core exactly once.
Reuse the two existing one-sided test families, Bonferroni alpha .025 each over
the union across A/B/C. Retain unsupported results and reasons. Core, tactical,
sequence and complete-preview admission are separate fields.

Report candidate/group counts, seed assignments, nomination/validation yield,
coverage without double-counting, within-hero owner overlap, sequence support,
legal path completion and stage runtimes. Report all nine heroes and detailed
Abrams/Kelvin previews including rejected or unordered candidates. Different
covered populations' raw win rates do not rank policies or establish causality.

Add synthetic/regression checks for losing cores, exact itemsets, complete-link
grouping, isolated identities, invalid unions, ties, source fingerprints,
sales/rebuys, components, limits and cross-fold isolation. Independently verify
sampled counts, inventories, orders and path cash accounting. Run the full fast
repository gate and affected experiment checks, without changing gate limits.
Success is a completed comparison, including honest negative findings.
