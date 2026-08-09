---
title: "Evidence-Grounded Deadlock Build Policy Requirements"
date: 2026-08-08
status: implementation-checklist
authority: companion-to-research
research: deadlock-strategy-description-research.md
---

# Evidence-grounded Deadlock build policy requirements

> [!IMPORTANT]
> This document is the implementation and verification checklist for
> `deadlock-build-sync`. The [research report](deadlock-strategy-description-research.md)
> remains the authoritative source for rationale, measurements, and external evidence.
> A checked requirement means its stated proof exists and passes; code presence or intent
> alone is not proof.

## 1. Purpose and normative language

The desired end state is a Linux-first CLI that creates patch-specific,
cohort-specific, mechanically legal, evidence-grounded Deadlock build policies and
installs their safe Valve-schema projection under Steam **My Builds** without changing
user-owned data outside the managed entries.

The key words **MUST**, **MUST NOT**, **REQUIRED**, **SHOULD**, **SHOULD NOT**, and
**MAY** are normative:

- **MUST/MUST NOT** — required for the named delivery gate.
- **SHOULD/SHOULD NOT** — required unless a documented exception contains equivalent
  evidence and is approved in review.
- **MAY** — optional behavior that must still satisfy all applicable safety and evidence
  requirements.

### 1.1 Status vocabulary

| Status | Meaning |
|---|---|
| `Pending` | Required proof is absent. |
| `Partial` | Some implementation or indirect evidence exists, but one or more acceptance criteria are unproved. |
| `Verified` | Every acceptance criterion has direct, passing proof at the current commit. |

### 1.2 Delivery stages

| Stage | Intent | Release rule |
|---|---|---|
| `P0` | Correct source semantics, mechanics, artifacts, and Steam behavior | No build may be installed without every P0 requirement verified. |
| `P1` | Conditional item/ability/matchup policy and full path validation | Required before claiming the project implements the research-defined build policy. |
| `P2` | Evaluation, decision logging, causal/OPE support, and production monitoring | Required before claiming learned recommendations improve decisions rather than imitate history. |

## 2. Source snapshots and provenance

### REQ-SRC-001 — Resolve and pin one client version

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Every generation run **MUST** resolve exactly one available Deadlock
  client version before fetching assets. Every hero, item, rank, map, generic-data, and
  Steam-schema asset request **MUST** carry that version. The resolved version **MUST**
  appear in every exported artifact.
- **Research basis:** [Client and assets](deadlock-strategy-description-research.md#client-and-assets), F-02.
- **Acceptance:** A fixture in which the latest version changes between requests still
  produces one-version assets; an unavailable explicit version fails before analytics.
- **Proof:** API-client unit tests plus a manifest fixture containing the resolved version
  on all asset records.
- **Dependencies:** None.

### REQ-SRC-002 — Hash exact source responses

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** The client **MUST** record request path, normalized parameters,
  fetch time, byte length, and SHA-256 of the exact response bytes for every input used by
  a policy. Canonical reserialization **MUST NOT** replace the raw-response digest.
- **Research basis:** [Asset fingerprints](deadlock-strategy-description-research.md#asset-fingerprints), F-02.
- **Acceptance:** Changing whitespace in raw JSON changes the raw digest while semantic
  parsing still succeeds; artifacts retain both identity and request metadata.
- **Proof:** Recorder tests using byte-distinct equivalent JSON and an exported snapshot
  manifest fixture.
- **Dependencies:** REQ-SRC-001.

### REQ-SRC-003 — Use stable patch identity

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Patch discovery **MUST** use the unified v2 feed and identify entries
  by source, GUID, publication timestamp, link, and normalized-content SHA-256. Title
  alone **MUST NOT** define freshness or artifact compatibility.
- **Research basis:** [Patch identity](deadlock-strategy-description-research.md#patch-identity), F-02.
- **Acceptance:** Two entries with equal titles but different GUID/content produce
  different patch identities and invalidate affected evidence.
- **Proof:** Patch parsing/fingerprint regression tests.
- **Dependencies:** REQ-SRC-002.

### REQ-SRC-004 — Record independent epoch boundaries

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** A snapshot **MUST** record mechanics, matchmaking, map/objective, and
  telemetry epochs separately. The analysis start **MUST** be no earlier than the latest
  boundary relevant to the claim unless an explicitly modelled multi-regime analysis is
  used.
- **Research basis:** [Patch identity](deadlock-strategy-description-research.md#patch-identity), F-01, F-02.
- **Acceptance:** A matchmaking-only update invalidates cohort evidence without falsely
  changing the mechanics digest; a mechanics update invalidates mechanical claims.
- **Proof:** Epoch compatibility and fingerprint tests.
- **Dependencies:** REQ-SRC-003.

### REQ-SRC-005 — Freeze a coherent as-of cutoff

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** One immutable `as_of_timestamp` **MUST** be captured before analytics
  collection and passed as the upper bound to all compatible queries. Requested and
  server-resolved time bounds **MUST** be recorded. Data fetched after the cutoff **MUST
  NOT** enter the run.
- **Research basis:** [Freeze patch, client, queue, cohort, and analytic grain](deadlock-strategy-description-research.md#freeze-patch-client-queue-cohort-and-analytic-grain), F-02, F-15.
- **Acceptance:** Delayed sequential requests share the same upper bound; exact-hour
  bounds do not silently expand in local logic.
- **Proof:** Fake-clock API tests and manifest assertions.
- **Dependencies:** REQ-SRC-002.

### REQ-SRC-006 — Declare route grain and fallback

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Every analytic record **MUST** declare its unit, temporal grain,
  endpoint, relevant table/materialized-view provenance when exposed, and known fallback
  behavior. A route that changes population or grain **MUST** produce a different evidence
  identity.
- **Research basis:** [Analytic grain](deadlock-strategy-description-research.md#analytic-grain), F-02.
- **Acceptance:** The exported evidence differentiates day-grained aggregate and
  base-table responses; missing provenance is a validation error, not an empty string.
- **Proof:** Evidence-schema validation tests and route fixtures.
- **Dependencies:** REQ-SRC-002.

## 3. Cohort, outcome, and analytic-unit contracts

### REQ-COH-001 — Separate Ranked and Unranked

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** `match_mode` **MUST** be a typed, explicit value on every analytic
  request, snapshot, fingerprint, artifact, guide description, preview, and install.
  Ranked and Unranked **MUST NOT** be pooled silently or used as fallbacks for each other.
- **Research basis:** [Queue and mode](deadlock-strategy-description-research.md#queue-and-mode), F-01.
- **Acceptance:** Request-capture tests prove every analytics call contains one mode; an
  artifact from the other mode is rejected.
- **Proof:** API, CLI, context, narrative-admission, and installation tests.
- **Dependencies:** None.

### REQ-COH-002 — Keep game mode distinct from match mode

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** `game_mode=normal` **MUST** identify the ruleset only and **MUST NOT**
  be presented as evidence that a cohort is Standard/Unranked. Street Brawl assets and
  analytics **MUST NOT** enter a normal-mode guide.
- **Research basis:** [Queue and mode](deadlock-strategy-description-research.md#queue-and-mode), F-01.
- **Acceptance:** Mixed or Street Brawl rows/assets are rejected by cohort validation.
- **Proof:** Negative cohort and asset-filter tests.
- **Dependencies:** REQ-COH-001.

### REQ-COH-003 — Derive rank labels from pinned assets

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Numeric badge IDs **MUST** be rank identity. Display labels and symbolic
  CLI parsing **MUST** be validated against the pinned rank asset; obsolete aliases MAY
  parse only when they map unambiguously and are reported as aliases.
- **Research basis:** [Rank labels](deadlock-strategy-description-research.md#rank-labels), F-03.
- **Acceptance:** Current tiers 3–7 resolve to Acolyte, Sentinel, Mystic, Ritualist, and
  Emissary; a numeric range survives label renames; the mapping hash is fingerprinted.
- **Proof:** Rank-catalog, alias, CLI, and artifact tests. Current baseline type errors must
  be fixed before verification.
- **Dependencies:** REQ-SRC-001.

### REQ-COH-004 — Encode outcome eligibility

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Every outcome-dependent analysis **MUST** state and enforce its policy
  for not-scored, penalized, party-penalized, abandoned, unrewarded, low-priority, and
  new-player rows. If the source cannot enforce the policy, the evidence **MUST** be
  descriptive-only or rejected; `won=true` **MUST NOT** override ineligibility.
- **Research basis:** [Outcome eligibility](deadlock-strategy-description-research.md#outcome-eligibility), F-01.
- **Acceptance:** Fixtures containing winning penalized players and voided outcomes are
  excluded or downgrade the claim exactly as declared.
- **Proof:** Eligibility-filter and claim-ceiling tests.
- **Dependencies:** REQ-SRC-006.

### REQ-COH-005 — Name the real analytic unit

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Fields and prose **MUST** distinguish purchase events, unique
  player-match appearances, unique accounts, ability paths, ability decisions reached,
  hero–enemy pair rows, adjacent-phase item pairs, and games. A field named `matches` or
  `pick_rate` **MUST NOT** cross these units without a typed conversion.
- **Research basis:** [Analytic grain](deadlock-strategy-description-research.md#analytic-grain), F-06, F-10, F-11.
- **Acceptance:** Serializers emit the unit beside every denominator; misleading
  `relative_pick_rate` output is removed or renamed.
- **Proof:** Typed-model and serialized-context tests.
- **Dependencies:** REQ-SRC-006.

### REQ-COH-006 — Widen sparse cohorts explicitly

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Sparse evidence MAY widen adjacent rank bands or time windows only by
  a declared deterministic policy. It **MUST NOT** cross match modes or incompatible
  epochs. Original and widened support **MUST** both be reported.
- **Research basis:** [Limits](deadlock-strategy-description-research.md#limits), [Queue and mode](deadlock-strategy-description-research.md#queue-and-mode).
- **Acceptance:** Sparse fixtures widen ranks in the documented order and abstain before
  crossing queue/epoch boundaries.
- **Proof:** Cohort-expansion property tests.
- **Dependencies:** REQ-COH-001, REQ-SRC-004.

### REQ-COH-007 — Require current-roster completeness

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** An `--all` run **MUST** compare generated policies with the pinned
  eligible hero roster. Every omission **MUST** have a structured reason. Installation
  **MUST** fail when any eligible hero is missing unless the user explicitly selected a
  subset.
- **Research basis:** F-18, [Final specification](deadlock-strategy-description-research.md#final-specification).
- **Acceptance:** Adding a hero to the asset fixture without evidence prevents all-hero
  installation and reports the hero/reason.
- **Proof:** Service, CLI, and install regression tests.
- **Dependencies:** REQ-SRC-001.

## 4. Mechanical truth and legal state

### REQ-MEC-001 — Preserve structured hero descriptions

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Hero lore, role, and playstyle objects **MUST** be normalized without
  dropping non-empty fields. Sanitization **MUST** remove markup/tokens while retaining
  distinct semantic fields.
- **Research basis:** [Mechanical kit record](deadlock-strategy-description-research.md#mechanical-kit-record), F-04.
- **Acceptance:** Current object-shaped hero descriptions export non-null role/playstyle;
  HTML/token fixtures sanitize deterministically.
- **Proof:** Mechanics/context regression tests.
- **Dependencies:** REQ-SRC-001.

### REQ-MEC-002 — Preserve complete ability/item property semantics

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Exported mechanics **MUST** preserve every labelled nonzero property,
  value, prefix/postfix, condition, usage flag, scale function, stat coefficient, scaling
  stat list, tooltip importance, and upgrade delta required to explain a claim. Unknown
  qualified mechanics **MUST** fail closed rather than be guessed.
- **Research basis:** [Mechanical kit record](deadlock-strategy-description-research.md#mechanical-kit-record), F-04.
- **Acceptance:** Fixtures cover single-stat, multi-stat, conditional, charge, cooldown,
  and upgrade properties with lossless structured output.
- **Proof:** Golden mechanics-schema tests against pinned asset fixtures.
- **Dependencies:** REQ-SRC-001.

### REQ-MEC-003 — Preserve hero-level scaling

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Hero `scaling_stats`, starting stats, standard level upgrades, and
  level-specific mechanics **MUST** be present in kit evidence when supplied by assets.
- **Research basis:** [Scaling is multidimensional](deadlock-strategy-description-research.md#scaling-is-multidimensional), F-04.
- **Acceptance:** A scaling hero fixture exports all coefficients and produces a different
  mechanics fingerprint when one changes.
- **Proof:** Scaling extraction/fingerprint tests.
- **Dependencies:** REQ-MEC-002.

### REQ-MEC-004 — Build the component/upgrade graph

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Current `component_items` relationships **MUST** resolve by class name
  to a directed acyclic item graph. The system **MUST** compute transitive components,
  child alternatives, incremental cash cost, total tree investment, and upgrade
  consumption without treating a component as proof of one child.
- **Research basis:** [Components, branches, and investment bonuses](deadlock-strategy-description-research.md#components-branches-and-investment-bonuses), F-04.
- **Acceptance:** Multi-child, nested, missing-reference, and cycle fixtures are handled;
  cycles/missing required components reject the snapshot.
- **Proof:** Graph and cost property tests.
- **Dependencies:** REQ-MEC-002.

### REQ-MEC-005 — Model category investment breakpoints

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Weapon, Vitality, and Spirit `cost_bonuses` **MUST** be read from the
  pinned hero/assets, and cumulative spend **MUST** cross each threshold at most once.
  Legacy/current bonus sources **MUST NOT** be added together unless the schema proves
  both apply.
- **Research basis:** [Components, branches, and investment bonuses](deadlock-strategy-description-research.md#components-branches-and-investment-bonuses), F-04.
- **Acceptance:** Threshold-boundary fixtures prove correct before/after bonuses and no
  double counting.
- **Proof:** Economy-state tests.
- **Dependencies:** REQ-MEC-004.

### REQ-MEC-006 — Validate the real level/AP timeline

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Ability actions **MUST** be simulated against pinned `level_info`,
  unlock currency, AP grants, and `1/2/5` (or current asset-defined) upgrade costs. AP
  **MUST NOT** become negative, prerequisites **MUST** hold, and price-tier “quarters”
  **MUST NOT** be emitted.
- **Research basis:** [Ability points and level gates](deadlock-strategy-description-research.md#ability-points-and-level-gates), F-05, F-10.
- **Acceptance:** Legal and illegal paths at levels 1–36 are tested; context exports exact
  earliest legal levels and AP balances without a `quarter` field.
- **Proof:** Timeline property tests and context schema tests.
- **Dependencies:** REQ-MEC-002.

### REQ-MEC-007 — Validate inventory, flex, active, and uniqueness limits

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Every realized path **MUST** respect nine base slots, at most three
  currently unlocked flex slots, twelve total slots, four active bindings, current
  uniqueness/duplicate rules, component consumption, and item availability.
- **Research basis:** [Inventory and slot pressure](deadlock-strategy-description-research.md#inventory-and-slot-pressure), F-09.
- **Acceptance:** Boundary fixtures for 9/12 slots, 4/5 actives, locked/unlocked flex, and
  component replacement either pass or fail deterministically.
- **Proof:** All-path validator property tests.
- **Dependencies:** REQ-MEC-004.

### REQ-MEC-008 — Validate imbue targets and item qualifiers

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** An imbue or charged/channeled/qualified ability interaction **MUST**
  reference a current learned eligible ability whose mechanics prove the qualification.
  Ultimate restrictions and other item-specific target rules **MUST** be enforced.
- **Research basis:** [Steam build semantics are mechanics](deadlock-strategy-description-research.md#steam-build-semantics-are-mechanics), F-04, F-09.
- **Acceptance:** Eligible and ineligible charge, channel, and ultimate fixtures are
  accepted/rejected correctly.
- **Proof:** Mechanics and renderer tests.
- **Dependencies:** REQ-MEC-002, REQ-MEC-006.

## 5. Analytics and estimands

### REQ-ANA-001 — Calculate true item adoption

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Adoption **MUST** use unique eligible player-match appearances as the
  denominator and unique first ownership of the item as the numerator. Purchase-event
  volume and unique-account count **MUST** remain separate fields.
- **Research basis:** [Separate four item questions](deadlock-strategy-description-research.md#separate-four-item-questions), F-06.
- **Acceptance:** Rebuy, duplicate event, and repeat-account fixtures produce one adoption
  per player-match while preserving raw event counts.
- **Proof:** Telemetry aggregation tests.
- **Dependencies:** REQ-COH-004, REQ-COH-005.

### REQ-ANA-002 — Estimate first-purchase timing from risk sets

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Timing evidence **MUST** use first-purchase cause-specific risk sets or
  cumulative incidence with substitute purchase, ineligibility, and game end represented
  as competing events. Median timing among eventual buyers alone **MUST NOT** define a
  recommendation window.
- **Research basis:** [First-purchase hazards](deadlock-strategy-description-research.md#first-purchase-hazards), F-07.
- **Acceptance:** Synthetic censoring/competing-event fixtures match hand-calculated
  hazards and cumulative incidence.
- **Proof:** Estimand unit tests and serialized timing-evidence fixture.
- **Dependencies:** REQ-ANA-001.

### REQ-ANA-003 — Quarantine invalid pre-180-second net worth

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Purchase net worth before 180 seconds **MUST** be null unless a trusted
  preceding observation exists. Values equal to an implausible final-snapshot fallback
  **MUST** trigger a telemetry-quality error. Clock-time opening evidence MAY remain.
- **Research basis:** [Critical telemetry finding](deadlock-strategy-description-research.md#critical-telemetry-finding-pre-180-net-worth), F-08.
- **Acceptance:** The documented corrupt pattern is rejected; a valid preceding sample
  with source time and acceptable age is retained.
- **Proof:** Telemetry regression fixtures.
- **Dependencies:** REQ-SRC-004.

### REQ-ANA-004 — Reconstruct upgrades and discretionary sells

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** A component consumed by a child purchase **MUST NOT** be classified as
  a discretionary sell. Classification **MUST** combine current graph membership, event
  flags, and time proximity. Equal-time accounting **MUST** apply component credit before
  child investment.
- **Research basis:** [Upgrade and sell reconstruction](deadlock-strategy-description-research.md#upgrade-and-sell-reconstruction).
- **Acceptance:** True sell, upgrade consumption, direct child purchase, nested upgrade,
  and equal-time fixtures reconstruct ownership and spend correctly.
- **Proof:** Event reconstruction property tests.
- **Dependencies:** REQ-MEC-004.

### REQ-ANA-005 — Keep item win rate descriptive by default

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Raw and net-worth-standardized item outcome rates **MUST** be labelled
  observational and include cohort, unit, numerator, denominator, and comparison baseline.
  They **MUST NOT** be rendered as item impact, added win rate, or causation.
- **Research basis:** [Item win rates](deadlock-strategy-description-research.md#item-win-rates-useful-signal-dangerous-ranking), F-06, F-07.
- **Acceptance:** Semantic validation rejects causal/promotional phrasings when evidence is
  descriptive.
- **Proof:** Claim-language and narrative validator tests.
- **Dependencies:** REQ-COH-005.

### REQ-ANA-006 — Report uncertainty and partial pooling

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Published proportions/comparisons **MUST** include an interval and
  support. Sparse item, rank, time, and matchup effects **SHOULD** use a documented
  hierarchical or empirical-Bayes shrinkage method rather than raw cell ranking.
- **Research basis:** [Uncertainty and shrinkage](deadlock-strategy-description-research.md#uncertainty-and-shrinkage).
- **Acceptance:** Hand-calculated interval fixtures pass; smaller cells shrink more toward
  the declared baseline; effective support is exported.
- **Proof:** Statistical unit tests and golden evidence cards.
- **Dependencies:** REQ-COH-005.

### REQ-ANA-007 — Control search multiplicity and winner’s curse

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Time windows and top-item claims selected from many candidates **MUST**
  be evaluated on a later/held-out sample or use a declared multiplicity correction. The
  production path **MUST NOT** select local outcome peaks from the same sample it reports.
- **Research basis:** [Multiple comparisons and winner’s curse](deadlock-strategy-description-research.md#multiple-comparisons-and-winners-curse), F-07.
- **Acceptance:** A null simulation does not publish systematically inflated selected
  effects; selection and estimation folds are disjoint.
- **Proof:** Seeded simulation and temporal-split tests.
- **Dependencies:** REQ-ANA-006.

### REQ-ANA-008 — Use half-open duration intervals

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Integer-second duration buckets **MUST** be disjoint and exhaustive,
  implemented as half-open intervals or equivalent inclusive bounds without duplication.
- **Research basis:** [Better game-time estimands](deadlock-strategy-description-research.md#better-game-time-estimands), F-14.
- **Acceptance:** Exact 25/30/35/40/45/50-minute fixtures occur in one bucket each.
- **Proof:** Boundary property tests and API request-capture assertions.
- **Dependencies:** None.

### REQ-ANA-009 — Distinguish ending-duration and landmark estimates

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Final-duration-conditioned outcomes **MUST** be called an
  `ending_duration_profile`, never a live power curve. Live game-time claims **MUST** use
  landmark risk sets among active games with uncertainty and at-risk counts.
- **Research basis:** [Ending-duration win rate is not a power curve](deadlock-strategy-description-research.md#ending-duration-win-rate-is-not-a-power-curve), F-11.
- **Acceptance:** Existing shape output is renamed; no narrative derives “strong at minute
  X” from final-duration buckets; landmark fixtures condition only on active games.
- **Proof:** Power-curve/context/narrative tests.
- **Dependencies:** REQ-ANA-008.

### REQ-ANA-010 — Model ability decisions by prefix and legal state

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Ability recommendations **MUST** aggregate all valid observed prefixes
  at each reached legal decision. All-appearance, decision-reached, valid-telemetry,
  complete-path, and retained-path denominators **MUST** remain separate. One exact
  complete path **MUST NOT** be presented as universal.
- **Research basis:** [Ability order and ability scaling](deadlock-strategy-description-research.md#ability-order-and-ability-scaling), F-10.
- **Acceptance:** Variable-length and branching fixtures retain early observations and
  expose branch probabilities; illegal IDs/AP states are rejected.
- **Proof:** Prefix aggregation and AP-validation tests.
- **Dependencies:** REQ-MEC-006, REQ-COH-005.

### REQ-ANA-011 — Separate lane and whole-team matchups

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Matchup evidence **MUST** declare same-lane or whole-enemy-team scope.
  Counts **MUST** be hero–enemy pair rows. Interactions **SHOULD** be adjusted for hero
  main effects and shrunk; uncertainty **MUST** be clustered by match where raw data
  permits.
- **Research basis:** [Define matchup scope first](deadlock-strategy-description-research.md#define-matchup-scope-first), F-12.
- **Acceptance:** One focal appearance against six enemies yields six whole-team pair rows
  but one appearance denominator; lane and team rankings can differ without collision.
- **Proof:** Matchup-model and serialization tests.
- **Dependencies:** REQ-COH-005, REQ-ANA-006.

### REQ-ANA-012 — Require mechanics-first counter evidence

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** A counter purchase **MUST** identify an observed threat, a current item
  mechanic that can answer it, legal timing, a comparable alternative or save action,
  replacement/sell behavior, execution mode, and failure condition. Matchup rate alone
  **MUST NOT** justify a counter item.
- **Research basis:** [Counter purchases and situational branches](deadlock-strategy-description-research.md#counter-purchases-and-situational-branches), F-12.
- **Acceptance:** Counter cards lacking any contract field are rejected; hard-control,
  healing, bullet, spirit, mobility, and ally-protection fixtures map only to mechanically
  valid responses.
- **Proof:** Threat-classifier, evidence-ladder, and policy validation tests.
- **Dependencies:** REQ-MEC-002, REQ-ANA-011.

### REQ-ANA-013 — Represent spikes as state transitions

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Every spike **MUST** record prerequisites, acquisition state, verified
  mechanical delta, conversion window, failure conditions, counterplay, evidence class,
  and confidence. A smoothed/local outcome maximum alone **MUST NOT** create a spike.
- **Research basis:** [Spike card](deadlock-strategy-description-research.md#spike-card).
- **Acceptance:** Mechanical unlock, component, investment, flex, active, objective, and
  counter-completion fixtures serialize complete spike cards; outcome-only peaks abstain.
- **Proof:** Spike construction and schema tests.
- **Dependencies:** REQ-MEC-005, REQ-MEC-006, REQ-ANA-009.

### REQ-ANA-014 — Prevent future leakage

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Every state feature **MUST** declare source event, `available_at`, and
  staleness. Final net worth/duration, future items, eventual-buyer identity, and other
  post-decision values **MUST NOT** enter a pre-decision feature or policy fingerprint.
- **Research basis:** [Control leakage](deadlock-strategy-description-research.md#control-leakage), F-08.
- **Acceptance:** Known final-net-worth, normalized-duration, future-item, and eventual-
  buyer fixtures fail validation.
- **Proof:** Feature-availability and leakage tests.
- **Dependencies:** REQ-ANA-003.

## 6. Build-policy model and claim control

### REQ-POL-001 — Use a typed policy IR

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** The canonical build **MUST** be a versioned policy graph, not an item
  tier dictionary. Supported node kinds **MUST** include `purchase`, `choice`, `sell`,
  `ability`, `wait`, `objective_gate`, and `end`.
- **Research basis:** [Build policy intermediate representation](deadlock-strategy-description-research.md#the-build-policy-intermediate-representation).
- **Acceptance:** Every node round-trips through the artifact schema and invalid/unknown
  node kinds are rejected.
- **Proof:** IR schema and round-trip tests.
- **Dependencies:** None.

### REQ-POL-002 — Restrict guards to observable versioned state

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Guards **MUST** reference only declared observable fields available at
  decision time: current heroes/threats/items, inventory/components, clock, level/AP,
  valid economy, slots/actives/flex, shops/objectives/cooldowns, queue/cohort, and epoch.
- **Research basis:** [State and guards](deadlock-strategy-description-research.md#state-and-guards).
- **Acceptance:** Unknown, future, unversioned, or type-incompatible guard paths fail
  schema validation.
- **Proof:** Guard parser/type-checker tests.
- **Dependencies:** REQ-ANA-014.

### REQ-POL-003 — Require exclusive choices and safe defaults

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Every choice **MUST** define mutual-exclusion semantics and a default or
  abstain branch. Save/wait **MUST** be representable. Ambiguous overlapping guards **MUST**
  be rejected unless deterministic precedence is explicit.
- **Research basis:** [Example IR](deadlock-strategy-description-research.md#example-ir).
- **Acceptance:** Missing-default, overlapping, unreachable, and explicit-priority choice
  fixtures behave deterministically.
- **Proof:** Symbolic branch-validation tests.
- **Dependencies:** REQ-POL-001, REQ-POL-002.

### REQ-POL-004 — Attach evidence IDs and claim classes

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Every recommendation and analytic sentence **MUST** reference a current
  evidence object with claim class (`mechanical`, `descriptive`, `predictive`, or
  `causal`), cohort, unit, support, estimate/interval where applicable, mechanics refs,
  and language ceiling.
- **Research basis:** [Claim classes and evidence hierarchy](deadlock-strategy-description-research.md#claim-classes-and-evidence-hierarchy), F-13.
- **Acceptance:** Missing/stale evidence IDs or prose stronger than the language ceiling
  reject the artifact.
- **Proof:** Evidence registry and semantic validator tests.
- **Dependencies:** REQ-SRC-002, REQ-COH-005.

### REQ-POL-005 — Abstain on failed hard gates

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** The policy **MUST** abstain with a structured reason when mechanics are
  stale/incomplete, support or overlap is inadequate, evidence conflicts, a path is
  illegal, a threat is unclear, the state is out of distribution, or telemetry fails.
  Validators **MUST NOT** be weakened to admit output.
- **Research basis:** [Overlap, calibration, and abstention](deadlock-strategy-description-research.md#overlap-calibration-and-abstention), [Final specification](deadlock-strategy-description-research.md#final-specification).
- **Acceptance:** Each abstention reason has a fixture and survives serialization/preview.
- **Proof:** Policy and CLI negative tests.
- **Dependencies:** REQ-POL-004.

### REQ-POL-006 — Separate invariant kit, role, and variant

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Policies **MUST** distinguish invariant hero mechanics, composition-
  dependent strategic role, and build variant. Evidence from incompatible variants
  **MUST NOT** be averaged into one universal path.
- **Research basis:** [Hero identity and build variants](deadlock-strategy-description-research.md#hero-identity-and-build-variants).
- **Acceptance:** Weapon/spirit/control variants retain distinct cores and branch evidence;
  variant identity participates in fingerprints.
- **Proof:** Variant clustering/selection and artifact tests.
- **Dependencies:** REQ-MEC-003, REQ-ANA-001.

### REQ-POL-007 — Support deviation and recalculation

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Given current owned items/abilities and state, evaluation **MUST** enter
  the nearest valid policy state rather than restart an immutable sequence. Missed timing
  **MUST** permit skip, stabilize, wait, or abstain behavior.
- **Research basis:** [Lessons from Dota 2](deadlock-strategy-description-research.md#dota-plus-recalculate-from-current-state), [Example D](deadlock-strategy-description-research.md#example-d--missed-purchase-timing).
- **Acceptance:** Out-of-order purchases and missed-window fixtures recalculate to legal
  actions without recommending already-owned or expired actions.
- **Proof:** Policy evaluator state-transition tests.
- **Dependencies:** REQ-POL-001, REQ-MEC-007.

### REQ-POL-008 — Keep models outside deterministic decisions

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Models MAY interpret and explain exported evidence, but **MUST NOT**
  collect data, select a stronger estimand, alter mechanics, approve illegal paths,
  calculate fingerprints, serialize Valve data, or mutate Steam files.
- **Research basis:** [Claim classes and evidence hierarchy](deadlock-strategy-description-research.md#claim-classes-and-evidence-hierarchy), repository invariants.
- **Acceptance:** The generation script accepts a closed evidence/policy packet; deterministic
  validation rejects changed IDs/mechanics/claims; no model call is reachable from the
  install mutation function.
- **Proof:** Architecture/import tests and adversarial narrative fixtures.
- **Dependencies:** REQ-POL-004.

### REQ-POL-009 — Produce a rich sidecar and compact projection

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** One policy **MUST** produce a rich reviewable sidecar containing guards,
  evidence, uncertainty, and all legal branches, plus a deterministic compact Steam
  projection containing only schema-executable behavior.
- **Research basis:** [Two products from one policy](deadlock-strategy-description-research.md#two-products-from-one-policy).
- **Acceptance:** Both artifacts reference the same policy fingerprint; projection loss is
  declared and never changes core semantics silently.
- **Proof:** Renderer projection/round-trip tests.
- **Dependencies:** REQ-POL-001, REQ-POL-004.

### REQ-POL-010 — Validate every reachable path

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** The validator **MUST** prove every reachable bounded path terminates and
  satisfies current item existence, components, slots/flex/actives, sells, duplicates,
  imbues, AP, evidence, and branch-default constraints. Validating listed items one at a
  time is insufficient.
- **Research basis:** [Path validation](deadlock-strategy-description-research.md#path-validation).
- **Acceptance:** Property and symbolic tests find errors hidden in one branch of an
  otherwise valid menu and reject cycles/unreachable ends.
- **Proof:** All-path validator suite.
- **Dependencies:** REQ-MEC-006, REQ-MEC-007, REQ-POL-003.

## 7. Valve rendering and guide UX

### REQ-RND-001 — Separate queued core from optional menus

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Only the minimal coherent default path **MUST** be in non-optional
  categories. Alternatives/counters **MUST** be in named optional categories and **MUST
  NOT** all enter Queue. Prose such as “choose one” is not an executable substitute.
- **Research basis:** [Machine semantics before prose](deadlock-strategy-description-research.md#machine-semantics-before-prose), F-09.
- **Acceptance:** Decoded output shows optional flags and a default Queue that does not
  contain all alternatives.
- **Proof:** Protobuf field and Queue-projection tests.
- **Dependencies:** REQ-POL-003.

### REQ-RND-002 — Encode item-level Valve semantics

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** The domain model and protobuf encoder **MUST** support and preserve
  `required_flex_slots`, `sell_priority`, and `imbue_target_ability_id` on item entries,
  plus category `optional`.
- **Research basis:** [Steam build semantics are mechanics](deadlock-strategy-description-research.md#steam-build-semantics-are-mechanics), F-09.
- **Acceptance:** Each field is present at the official wire number and round-trips through
  the parser; omitted versus zero values remain distinguishable where Valve does.
- **Proof:** Exact protobuf decode fixtures, including a public-build-compatible blob.
- **Dependencies:** REQ-MEC-008.

### REQ-RND-003 — Encode valid sell behavior

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Positive sell priority **MUST** refer to an item owned on that branch,
  use deterministic ordering, and agree with replacement annotations. Upgrade consumption
  **MUST NOT** create a sell badge.
- **Research basis:** [Counter branch contract](deadlock-strategy-description-research.md#counter-branch-contract), F-09.
- **Acceptance:** Decoded branch fixtures show intended sell order; invalid ownership
  rejects rendering.
- **Proof:** Policy-to-protobuf and event reconstruction tests.
- **Dependencies:** REQ-ANA-004, REQ-POL-010.

### REQ-RND-004 — Encode valid imbues

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Suggested imbue targets **MUST** be encoded on the correct item and agree
  with the policy/ability mechanics. A narrative-only target or invalid ability **MUST**
  reject projection.
- **Research basis:** [Steam build semantics are mechanics](deadlock-strategy-description-research.md#steam-build-semantics-are-mechanics), F-09.
- **Acceptance:** Valid/invalid imbue targets round-trip or fail as expected.
- **Proof:** Renderer and mechanics tests.
- **Dependencies:** REQ-MEC-008, REQ-RND-002.

### REQ-RND-005 — Encode flex gates

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Items whose branch requires flex capacity **MUST** encode the minimum
  required flex slots. The renderer **MUST NOT** use a flex gate as a substitute for a
  different objective condition it cannot represent.
- **Research basis:** [Inventory and slot pressure](deadlock-strategy-description-research.md#inventory-and-slot-pressure), F-09.
- **Acceptance:** Locked/unlocked flex paths decode with correct gates and pass all-path
  validation.
- **Proof:** Renderer/validator tests.
- **Dependencies:** REQ-MEC-007, REQ-RND-002.

### REQ-RND-006 — Keep annotations actionable and bounded

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Optional-item annotations **MUST** name trigger, choice/replacement,
  proactive/reactive execution where relevant, and failure condition within Valve UI
  limits. Statistical caveats belong in the guide description/sidecar, not duplicated on
  every tile.
- **Research basis:** [Keep the menu small and actionable](deadlock-strategy-description-research.md#keep-the-menu-small-and-actionable).
- **Acceptance:** Golden annotations fit length/encoding limits and preserve required
  tactical fields.
- **Proof:** Renderer snapshot and Unicode/length tests.
- **Dependencies:** REQ-ANA-012.

### REQ-RND-007 — Identify snapshot and cohort in the build

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** The build description **MUST** identify patch, client version,
  matchmaking mode, current rank labels/IDs, policy fingerprint, and observational claim
  limit within format limits.
- **Research basis:** [Guide rendering](deadlock-strategy-description-research.md#guide-rendering-and-steam-schema-semantics), F-01, F-02, F-03.
- **Acceptance:** A decoded guide exposes each identity and rejects stale/mismatched input.
- **Proof:** Protobuf description and admission tests.
- **Dependencies:** REQ-SRC-001, REQ-COH-001, REQ-COH-003.

## 8. Artifacts, fingerprints, and freshness

### REQ-ART-001 — Separate fingerprint layers

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Artifacts **MUST** have separate fingerprints for mechanics, analytics,
  policy basis, narrative/explanation, and installation projection. Changing any claim-
  relevant count, estimate, mode, epoch, mechanics field, guard, or rendered behavior
  **MUST** invalidate the applicable downstream layer.
- **Research basis:** F-13, [Evidence object](deadlock-strategy-description-research.md#evidence-object).
- **Acceptance:** Mutation tests change one field in each layer and assert the exact
  invalidation boundary.
- **Proof:** Fingerprint dependency tests.
- **Dependencies:** REQ-SRC-002, REQ-POL-004.

### REQ-ART-002 — Require exact artifact compatibility

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Reuse **MUST** require compatible schema, prompt/model policy where
  relevant, patch/epochs, client, mode, ranks, mechanics, analytic/policy basis, and hero
  identity. Bypassing full context comparison **MUST NOT** admit changed evidence claims.
- **Research basis:** F-13.
- **Acceptance:** Stale mode/count/estimate/epoch/mechanic/prompt fixtures are regenerated
  or rejected; reuse reason is recorded.
- **Proof:** Narrative reuse/admission matrix tests.
- **Dependencies:** REQ-ART-001.

### REQ-ART-003 — Validate document completeness

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Context, policy, and narrative artifacts **MUST** contain exactly the
  requested current heroes or structured subset exclusions, unique IDs, all referenced
  mechanics/evidence, and no malformed/stale entry.
- **Research basis:** F-18, repository invariants.
- **Acceptance:** Missing, duplicate, extra, incomplete, and reference-dangling hero
  fixtures fail before preview/install.
- **Proof:** Artifact schema and service tests.
- **Dependencies:** REQ-COH-007, REQ-POL-004.

### REQ-ART-004 — Write reusable artifacts atomically

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Context, policy, kit, and narrative artifacts **MUST** be written to a
  same-directory temporary file, flushed and file-fsynced, atomically replaced, and parent-
  directory-fsynced. A failed write **MUST** leave the prior valid artifact intact.
- **Research basis:** F-16 and the mutation-boundary durability rationale.
- **Acceptance:** Injected failures before/after replace preserve either the old or complete
  new artifact, never a partial file.
- **Proof:** Fault-injection filesystem tests.
- **Dependencies:** None.

### REQ-ART-005 — Persist the complete run manifest

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** The snapshot manifest **MUST** be embedded or referenced by every
  artifact and copied into the backup/install manifest. Its snapshot ID **MUST** derive
  from all identity-bearing fields and exact source records.
- **Research basis:** [Recommended future manifest](deadlock-strategy-description-research.md#recommended-future-manifest), F-02.
- **Acceptance:** Context, policy, narrative, backup, preview, and installed description
  resolve to the same snapshot/policy identities.
- **Proof:** End-to-end artifact fixture tests.
- **Dependencies:** REQ-SRC-001 through REQ-SRC-006.

## 9. Steam mutation safety

### REQ-SAF-001 — Refuse writes while Deadlock is running

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Sync, install, and restore **MUST** check the process immediately before
  mutation and refuse when Deadlock is running. Earlier orchestration checks **MUST NOT**
  replace the boundary check.
- **Research basis:** Repository invariant and [Mutation-boundary checklist](deadlock-strategy-description-research.md#mutation-boundary-checklist).
- **Acceptance:** A process-state fixture changing between generation and mutation is
  refused without touching the cache.
- **Proof:** Boundary race regression test.
- **Dependencies:** None.

### REQ-SAF-002 — Create a recoverable backup before replacement

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Installation **MUST** back up the original KV3 cache and available
  `remotecache.vdf` before replacement and record account, source path, time, IDs, cohort,
  snapshot, and fingerprints.
- **Research basis:** Repository invariant.
- **Acceptance:** Backup precedes replacement and contains restorable original files and
  manifest.
- **Proof:** `tests/test_cache.py::test_install_creates_backup_and_restore_recovers_original`
  proves file backup/recovery; manifest metadata must be rechecked when REQ-ART-005 lands.
- **Dependencies:** REQ-ART-005 for complete metadata.

### REQ-SAF-003 — Validate, atomically replace, and fsync the directory

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Replacement **MUST** be written in the target directory, flushed,
  file-fsynced, fully decoded/validated, atomically renamed, and followed by parent-
  directory fsync. The installed file **MUST** be decoded again.
- **Research basis:** F-16.
- **Acceptance:** Fault injection covers write, file fsync, decode, rename, directory
  fsync, and post-read failures with deterministic restore/reporting.
- **Proof:** Filesystem syscall-order/failure tests.
- **Dependencies:** REQ-POL-010.

### REQ-SAF-004 — Prove out-of-scope data preservation

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Before mutation the installer **MUST** fingerprint Favorites,
  SavedLastUsed, LastUsedBuilds/selected state, unrelated private builds, unknown root
  fields, and unmodified managed heroes. The decoded installed cache **MUST** match those
  fingerprints exactly.
- **Research basis:** F-17 and repository invariant.
- **Acceptance:** Deeply nested/unknown-field fixtures remain byte- or semantic-equivalent;
  any out-of-scope difference restores and fails.
- **Proof:** Projection-hash and corruption-injection tests.
- **Dependencies:** REQ-SAF-003.

### REQ-SAF-005 — Restore automatically and explicitly

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Any failed install after backup **MUST** restore the original cache or
  report both install and restore failures with the backup path. Restore **MUST** validate
  its source and obey the running-process guard.
- **Research basis:** Repository invariant.
- **Acceptance:** Recovery returns exact original KV3; double-failure reporting retains the
  backup location.
- **Proof:** Existing backup/restore test plus required injected double-failure test.
- **Dependencies:** REQ-SAF-001, REQ-SAF-002.

### REQ-SAF-006 — Preserve managed idempotence and ownership

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Only entries with the managed marker for the same hero/account **MAY**
  be updated. Reruns **MUST** retain safe build IDs, create no duplicates, and report
  created/updated counts.
- **Research basis:** Repository invariants.
- **Acceptance:** Two identical runs create once and update thereafter; duplicate managed
  entries fail closed.
- **Proof:** `tests/test_cache.py::test_managed_update_is_idempotent_and_preserves_other_sections`
  and duplicate-entry coverage.
- **Dependencies:** None.

### REQ-SAF-007 — Never run a live sync implicitly

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Development, tests, evaluation, and PR automation **MUST NOT** run a
  live Steam sync. A user-authorized live run **MUST** report artifact directory, cache,
  backup, created/updated counts, snapshot/policy IDs, and skipped heroes.
- **Research basis:** AGENTS.md release bar.
- **Acceptance:** Tests use isolated temporary caches; no CI command reaches a discovered
  live cache.
- **Proof:** CLI dependency-injection tests and workflow inspection.
- **Dependencies:** REQ-COH-007, REQ-ART-005.

## 10. Evaluation, learning, and monitoring

### REQ-EVA-001 — Evaluate each layer separately

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Evaluation **MUST** report mechanics fidelity, path legality,
  next-action imitation, probability calibration, selective risk/coverage, comparative-
  outcome assumptions, tactical expert review, Valve round-trip, and user-data
  preservation separately. One aggregate score **MUST NOT** mask a failed hard gate.
- **Research basis:** [Offline evaluation matrix](deadlock-strategy-description-research.md#offline-evaluation-matrix).
- **Acceptance:** The evaluation report contains every layer and fails when any required
  hard gate fails despite high recommendation metrics.
- **Proof:** Evaluation-runner tests and a checked-in sample report/schema.
- **Dependencies:** Relevant subsystem requirements.

### REQ-EVA-002 — Use patch-forward, group-aware splits

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Model selection/evaluation **MUST** use later patch/time folds and avoid
  player/match leakage across folds. Popularity **MUST** be a reported baseline.
- **Research basis:** [Sequential recommendation research](deadlock-strategy-description-research.md#sequential-recommendation-research), [Multiplicity](deadlock-strategy-description-research.md#multiplicity-and-partial-pooling).
- **Acceptance:** Split validation proves chronological order and disjoint group IDs.
- **Proof:** Dataset splitter tests.
- **Dependencies:** REQ-SRC-004.

### REQ-EVA-003 — Measure calibration and selective risk

- **Priority/stage:** `P2`
- **Status:** `Verified`
- **Requirement:** Predictive policies **MUST** report log loss, Brier score, calibration,
  and risk–coverage by queue/rank/hero/patch. Deployment thresholds **MUST** permit
  abstention and **MUST NOT** be selected on the final test fold.
- **Research basis:** [Overlap, calibration, and abstention](deadlock-strategy-description-research.md#overlap-calibration-and-abstention).
- **Acceptance:** Miscalibrated and out-of-distribution fixtures reduce coverage or fail
  the gate; threshold selection uses validation only.
- **Proof:** Calibration/selective-classification tests.
- **Dependencies:** REQ-POL-005, REQ-EVA-002.

### REQ-EVA-004 — Cover archetypes, threats, and failure states

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** The suite **MUST** cover early/mid/late archetypes, weapon/spirit/
  vitality/hybrid/support/active variants, ahead/even/behind, major threat classes,
  sparse/OOD patches/heroes, component and equal-time events, deviations, missed timing,
  no-overlap abstention, slot/active/flex pressure, and incomplete assets.
- **Research basis:** [Evaluation cases](deadlock-strategy-description-research.md#evaluation-cases).
- **Acceptance:** A coverage manifest maps every named scenario to at least one deterministic
  or model-backed case.
- **Proof:** Test/eval coverage manifest checked in CI.
- **Dependencies:** REQ-POL-006, REQ-ANA-012.

### REQ-EVA-005 — Predeclare target trials for causal claims

- **Priority/stage:** `P2`
- **Status:** `Verified`
- **Requirement:** Any causal item/policy claim **MUST** predeclare eligibility, time zero,
  treatment alternatives including save, assignment model, follow-up, outcome, censoring,
  estimand, and sensitivity analysis. Inadequate overlap **MUST** abstain.
- **Research basis:** [Start from a target-trial specification](deadlock-strategy-description-research.md#start-from-a-target-trial-specification).
- **Acceptance:** Missing target-trial fields or poor-overlap fixtures cannot receive a
  causal claim class.
- **Proof:** Estimand-schema and overlap tests.
- **Dependencies:** REQ-POL-004, REQ-ANA-014.

### REQ-EVA-006 — Support defensible off-policy evaluation

- **Priority/stage:** `P2`
- **Status:** `Verified`
- **Requirement:** OPE **MUST** use logged exposure/candidate slate, behavior propensity,
  action, outcome, and support diagnostics. It **MUST NOT** evaluate actions outside logged
  support or report one estimator without sensitivity/diagnostics.
- **Research basis:** [Feedback loops](deadlock-strategy-description-research.md#feedback-loops).
- **Acceptance:** Known-policy simulations recover expected value within tolerance and
  abstain under zero support.
- **Proof:** Seeded OPE simulation tests.
- **Dependencies:** REQ-EVA-005, REQ-EVA-007.

### REQ-EVA-007 — Log recommendation feedback safely

- **Priority/stage:** `P2`
- **Status:** `Verified`
- **Requirement:** With explicit telemetry availability, the system **MUST** log policy/
  recommendation version, candidate order, exposure, adoption/deviation, recalculation,
  behavior propensity or experiment assignment, and intermediate/final outcomes without
  storing unnecessary personal data.
- **Research basis:** [Feedback loops](deadlock-strategy-description-research.md#feedback-loops).
- **Acceptance:** A decision-log schema validates complete events, rejects future leakage,
  and documents retention/privacy boundaries.
- **Proof:** Schema, privacy-field, and event-sequence tests.
- **Dependencies:** REQ-ANA-014, REQ-POL-007.

### REQ-EVA-008 — Monitor drift and define rollback

- **Priority/stage:** `P2`
- **Status:** `Verified`
- **Requirement:** Production monitoring **MUST** track snapshot freshness, invalid state,
  exposure/adoption/deviation, unhandled branches, calibration, concentration/feedback,
  path/render rejection, artifact reuse, and install/restore outcomes. Mechanics mismatch,
  material calibration failure, schema decode failure, or preservation change **MUST**
  trigger rollback/refusal.
- **Research basis:** [Production monitoring](deadlock-strategy-description-research.md#production-monitoring).
- **Acceptance:** Synthetic alerts exercise each rollback condition and identify the last
  compatible policy/snapshot.
- **Proof:** Monitoring-rule tests and runbook fixture.
- **Dependencies:** REQ-EVA-003, REQ-EVA-007.

### REQ-EVA-009 — Run model-backed evaluations when relevant

- **Priority/stage:** `P1`
- **Status:** `Verified`
- **Requirement:** Prompt, narrative-schema, or semantic-validator changes **MUST** run the
  relevant DeepEval suite against representative cases, or the PR **MUST** state the exact
  credential/environment reason it could not run. Deterministic input defects **MUST NOT**
  be waived by a passing model score.
- **Research basis:** AGENTS.md release bar, [Existing DeepEval coverage](deadlock-strategy-description-research.md#existing-deepeval-coverage).
- **Acceptance:** CI/local evidence records model, prompt, dataset, results, and failures.
- **Proof:** DeepEval output/artifact or explicit documented limitation.
- **Dependencies:** REQ-EVA-004.

## 11. CLI, release, and pull-request requirements

### REQ-OPS-001 — Keep the primary sync path obvious and explicit

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** `deadlock-build-sync sync` **MUST** remain the obvious primary path. It
  **MAY** default to Ranked and the latest available client version, but the resolved mode,
  version, as-of cutoff, rank range, and epochs **MUST** be explicit in artifacts/output.
  CLI overrides **MUST** be typed and fingerprinted.
- **Research basis:** Repository mission, F-01, F-02.
- **Acceptance:** Parser and end-to-end CLI tests cover defaults and overrides without
  unlabeled inference.
- **Proof:** CLI tests and preview fixture.
- **Dependencies:** REQ-SRC-001, REQ-COH-001.

### REQ-OPS-002 — Report every operational artifact and outcome

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Preview/sync/install **MUST** report artifact paths, snapshot/policy IDs,
  cohort, cache/backup paths when applicable, created/updated counts, and every skipped or
  abstained hero with reason. Machine-readable preview **MUST** keep diagnostics on stderr.
- **Research basis:** Repository release bar and UNIX boundary.
- **Acceptance:** CLI golden tests separate JSON stdout from diagnostics and include all
  required fields.
- **Proof:** CLI capture tests.
- **Dependencies:** REQ-ART-005, REQ-COH-007.

### REQ-OPS-003 — Preserve lower-level review/debug commands

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** `preview`, `export-context`, reviewed-artifact `install`, and `restore`
  **MUST** remain available so generation and mutation can be reviewed separately.
- **Research basis:** AGENTS.md architecture boundary.
- **Acceptance:** Parser/handler tests exercise each command without a live cache.
- **Proof:** Existing CLI tests; extend when policy artifacts are introduced.
- **Dependencies:** None.

### REQ-OPS-004 — Pass the complete local gate

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** Before handoff and PR, the exact lock, format, lint, type, test,
  dependency, and build commands in AGENTS.md **MUST** pass from a clean dependency state.
- **Research basis:** [Release gate](deadlock-strategy-description-research.md#release-gate).
- **Acceptance:** All seven commands exit zero at the final commit. The delivery gate
  passes with 167 tests and no lock, format, lint, type, dependency, or build failures.
- **Proof:** Captured final command output and CI checks.
- **Dependencies:** All implementation requirements in the claimed gate.

### REQ-OPS-005 — Smoke-test packaging when package contents change

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** When new modules/schemas are packaged, the built wheel **MUST** be
  inspected and installed into a temporary environment outside the checkout; CLI import,
  help, preview with fixtures, and required resource lookup **MUST** work there.
- **Research basis:** AGENTS.md release bar.
- **Acceptance:** Wheel contents include every runtime module/schema and the external smoke
  commands exit zero.
- **Proof:** Wheel listing and temporary-environment transcript.
- **Dependencies:** REQ-OPS-004.

### REQ-OPS-006 — Deliver through an unmerged feature PR

- **Priority/stage:** `P0`
- **Status:** `Verified`
- **Requirement:** All work **MUST** remain on `feat/evidence-grounded-build-policy` (or a
  clearly superseding feature branch), be committed and pushed, and be presented in an
  open pull request targeting `main`. The agent **MUST NOT** merge the PR.
- **Research basis:** User delivery instruction.
- **Acceptance:** Remote PR reports the intended head/base, open state, commits, and checks;
  `main` remains unchanged by this work.
- **Proof:** `git`/hosting-service PR metadata at handoff.
- **Dependencies:** REQ-OPS-004, REQ-OPS-005, REQ-EVA-009.

## 12. Delivery gates

### 12.1 P0 correctness gate

All of the following must be `Verified` before any live-install-capable implementation is
considered complete:

- [x] `REQ-SRC-001` through `REQ-SRC-006`
- [x] `REQ-COH-001` through `REQ-COH-005` and `REQ-COH-007`
- [x] `REQ-MEC-001` through `REQ-MEC-008`
- [x] `REQ-ANA-003`, `REQ-ANA-005`, `REQ-ANA-008`, `REQ-ANA-014`
- [x] `REQ-POL-004`, `REQ-POL-005`, `REQ-POL-008`
- [x] `REQ-RND-001` through `REQ-RND-005` and `REQ-RND-007`
- [x] `REQ-ART-001` through `REQ-ART-005`
- [x] `REQ-SAF-001` through `REQ-SAF-007`
- [x] `REQ-OPS-001` through `REQ-OPS-006`

### 12.2 P1 conditional-policy gate

- [x] `REQ-COH-006`
- [x] `REQ-ANA-001`, `REQ-ANA-002`, `REQ-ANA-004`, `REQ-ANA-006` through `REQ-ANA-013`
- [x] `REQ-POL-001` through `REQ-POL-010`
- [x] `REQ-RND-006`
- [x] `REQ-EVA-001`, `REQ-EVA-002`, `REQ-EVA-004`, `REQ-EVA-009`

### 12.3 P2 evaluated-learning gate

- [x] `REQ-EVA-003`
- [x] `REQ-EVA-005` through `REQ-EVA-008`

## 13. Research traceability

### 13.1 Finding register mapping

| Research finding | Governing requirements |
|---|---|
| F-01 Mixed matchmaking population | REQ-COH-001, REQ-COH-002, REQ-COH-004, REQ-OPS-001 |
| F-02 Snapshot incoherence | REQ-SRC-001–006, REQ-ART-005 |
| F-03 Stale rank labels | REQ-COH-003, REQ-RND-007 |
| F-04 Mechanics dropped from context | REQ-MEC-001–005, REQ-MEC-008 |
| F-05 Price-tier/ability-quarter conflation | REQ-MEC-006, REQ-ANA-010 |
| F-06 Event volume mislabeled as pick rate | REQ-COH-005, REQ-ANA-001, REQ-ANA-005 |
| F-07 Outcome peaks presented as buy windows | REQ-ANA-002, REQ-ANA-006, REQ-ANA-007 |
| F-08 Corrupted early net worth | REQ-ANA-003, REQ-ANA-014 |
| F-09 Steam Queue semantics contradict prose | REQ-MEC-007–008, REQ-RND-001–005 |
| F-10 Complete-path selection bias | REQ-MEC-006, REQ-ANA-010 |
| F-11 Duration estimand mismatch | REQ-ANA-008, REQ-ANA-009 |
| F-12 Missing matchup/counter evidence | REQ-ANA-011, REQ-ANA-012 |
| F-13 Narrow fingerprint semantics | REQ-POL-004, REQ-ART-001, REQ-ART-002 |
| F-14 Duration endpoints overlap | REQ-ANA-008 |
| F-15 Exact-hour timestamp expansion | REQ-SRC-005 |
| F-16 Directory durability | REQ-ART-004, REQ-SAF-003 |
| F-17 Preservation validation | REQ-SAF-004 |
| F-18 Artifact coverage/staleness | REQ-COH-007, REQ-ART-003 |

### 13.2 Final specification mapping

| Final rule | Governing requirements |
|---:|---|
| 1. Current | REQ-SRC-001–006, REQ-ART-005 |
| 2. Comparable | REQ-COH-001–006 |
| 3. Mechanical | REQ-MEC-001–008 |
| 4. Conditional | REQ-POL-001–010, REQ-ANA-001–013 |
| 5. Honest | REQ-ANA-005–007, REQ-ANA-014, REQ-POL-004–005 |
| 6. Tactical | REQ-ANA-012–013, REQ-RND-006 |
| 7. Executable | REQ-RND-001–007, REQ-POL-010 |
| 8. Reviewable | REQ-POL-009, REQ-ART-001–005, REQ-OPS-002 |
| 9. Evaluated | REQ-EVA-001–009 |
| 10. Safe | REQ-SAF-001–007, REQ-POL-008 |

## 14. Verification record

The status fields above must be updated only in the same change that adds or inspects the
named proof. At each delivery gate, record:

```yaml
commit: bc5544b400b99f5aef1a6a276fe3d434e24cd033
snapshot_fixture: f89b7120f99797a972a6185ab8c2ca78aac2af90c78295c9dea4372a691694a3
verified_rank_cohort: Emissary-I--Eternus-V
requirements_verified:
  - REQ-SRC-001..006
  - REQ-COH-001..007
  - REQ-MEC-001..008
  - REQ-ANA-001..014
  - REQ-POL-001..010
  - REQ-RND-001..007
  - REQ-ART-001..005
  - REQ-SAF-001..007
  - REQ-EVA-001..009
  - REQ-OPS-001..006
deterministic_gate:
  uv_lock_check: passed
  ruff_format: passed
  ruff_lint: passed
  ty: passed
  pytest: 167-passed
  uv_pip_check: passed
  uv_build: passed-wheel-and-sdist
model_eval:
  status: passed
  framework: DeepEval-with-production-validators
  prompt_version: 18
  kit_prompt_version: 3
  models: [gpt-5.6-luna, gpt-5.6-sol]
  reliability: 10-of-10-cases-and-30-of-30-production-budget-repetitions-admitted
wheel_smoke:
  status: passed
  environment: /tmp/deadlock-build-sync-wheel.5DfPNY
  checks: [wheel-contents, installed-import, cli-help, fixture-preview, schema-lookup]
live_steam_sync: not-authorized-and-not-run
pull_request: https://github.com/sxndmxn/deadlock-build-sync/pull/2
```

The final completion audit must inspect current files, decoded artifacts, test scope,
command output, and PR state requirement by requirement. Absence of an observed failure is
not completion evidence.
