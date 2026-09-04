# Build quality and independent replay

`quality-report` reads a frozen artifact bundle and reports each hero/build path
separately. It performs no Steam discovery, cache writes, or network requests.

```bash
deadlock-build-sync quality-report --artifacts /path/to/artifacts
deadlock-build-sync quality-report --artifacts /path/to/artifacts \
  --replay later-decisions.json --assets /path/to/offline/raw/items-all.json \
  > quality-report.json
```

The artifact directory must contain mutually compatible `build-evidence.json`,
`strategy-context.json`, and `policies.json`. Narratives are not required.
Replay requires item assets whose normalized Normal-mode list exactly matches the
evidence fingerprint. Old evidence/context contracts require regeneration.

## What a result means

| Status | Meaning |
| --- | --- |
| `pass` | Ability support/conditioning and the declared technical replay checks pass. |
| `fail` | An ability decision has fewer than 20 observations, a replay state is invalid, or the runtime recommends an illegal/incorrectly costed buy. |
| `unevaluated` | Build-conditioned ability evidence or independent replay coverage is insufficient. |

Exit codes are 0 for pass, 1 for failure or malformed inputs, and 2 for unevaluated.
Passing replay requires unambiguous buy/save/end decisions from at least 20
distinct match groups in each of six strata:
opening (before 9 minutes), midgame (9–20 minutes), later play, deficits,
unfinished CORE, and manual deviations. Coverage in one stratum cannot replace
missing evidence in another. The support floor is a minimum diagnostic bar,
not a statistical guarantee of strategic effectiveness.

Reports include the policy ID and content hash, context and evidence identity,
replay content hash, cohort, patch, CORE support by period, ability fallback reason,
purchase-window availability, action coverage, invalid states, illegal buys,
action agreement, and an affordable legal training-popularity baseline.
Abstentions and savings are reported explicitly. Ambiguous simultaneous purchases
remain in coverage counts but are excluded from action-agreement scoring.
The exact production `recommend` function handles component credit, current cash,
inventory and active limits, threats, and branch selection. Replay does not infer
available cash from a net-worth purchase window.

A pass does **not** prove improved win rate, optimal items, or causal item effects.
Action agreement measures imitation. These diagnostics do not simulate the
counterfactual result of following a different build through the whole match.

## Replay input

See `schemas/quality-replay.schema.json`. Each case contains:

- `policy_id`: exact frozen policy identity, which also identifies the build path.
- `match_group`: deidentified grouping token; never copied into the report.
- `match_start_timestamp`: Unix timestamp strictly after both the artifact evidence
  cutoff and recorded policy creation time.
- `policy_assigned_at`: Unix timestamp after that frozen cutoff and no later than
  match start. Assign paths before seeing match outcomes or final inventories.
- `feature_as_of_timestamp`: timestamp between match start and the decision time;
  all state fields must describe information available then.
- `state`: the same closed schema-2 state accepted by `recommend`, including actual
  liquid souls, components, flex slots, active bindings, and learned abilities.
- `observed_action`: `buy`, `save`, `end`, or `abstain`; `observed_item_id` is a
  positive item ID only for buys and null otherwise.
- `core_completed`, `behind`, `ambiguous_purchase`: explicit booleans.
  Completion is an evaluation-only label; it must never determine inclusion.

The root contains `schema_version: 1`,
`cohort_selection: "all_eligible_player_matches"`, and a `cases` list. Repeated
opportunities, crossed policies/evidence, and invalid time ordering are rejected.
The collector must preserve all eligible matches, including unfinished builds,
and accurately record the declared timestamps and labels. The evaluator validates
the supplied contract; it cannot independently authenticate collection history.

The existing offline purchase extract does not contain every required replay
state field. Supply independently collected complete states; do not synthesize
liquid cash, flex unlocks, ability knowledge, or unobserved save decisions from
ending wealth or purchase popularity. Without those states the report deliberately
remains unevaluated.

## Selection and release evidence

Training/validation statistics select optional CORE candidates and imbue targets.
All-period adoption and buyer outcome statistics remain descriptive displays.
Changing historical test rows cannot reorder the alternative shortlist or change
an imbue target. Path labels use a training numerator and training denominator.

The existing situational support and positive-advantage checks in the historical
`test` fold are retained. That fold is release-validation data for those branches,
not an untouched assessment of the shipped policy. Independent evaluation uses
later replay matches after freezing the entire policy. Hero-wide historical
sequence-model metrics are explicitly labeled baseline diagnostics; they do not
certify a particular build or its runtime graph.

Every hero, including single-path heroes, requests build-conditioned ability
telemetry. A fallback remains mechanically validated and carries its exact reason,
but is never labeled build-compatible merely because the global order is popular.
