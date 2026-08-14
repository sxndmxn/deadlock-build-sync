# Phase 0 — Truth and routing

Status: planned

## Outcome

The CLI detects stale evidence before generation or Steam access, refreshes the
offline evidence through one repository-owned command, and projects the tactical
information it already validates into truthful player-facing surfaces.

## Decisions

- Keep one repository and one `deadlock-build-sync` CLI. Move the existing offline
  producer under `deadlock_build_sync.offline` and load its heavy dependencies only
  through an `analysis` optional extra.
- Add read-only `status` and `refresh-evidence` commands. `status` returns 0 when the
  complete chain is current, 2 when regeneration is required, and 1 for malformed or
  unavailable inputs. `refresh-evidence` never reads or writes Steam.
- Introduce one immutable presentation value consumed by protobuf encoding. It owns
  the final title, tag IDs, description, categories/item annotations, and ability
  annotation; protobuf remains a pure encoder.
- Keep the managed marker and every snapshot/policy identity in the description, but
  place role, Queue usage, and fight/economy guidance first.
- Call the ability sequence a “state-composed observed default” and expose minimum and
  final decision support. Remove raw adopter outcome from its in-game annotation.
- Apply `core-1` through `core-8` narrative instructions only after exact node, item,
  evidence, and order validation. Analytics-only copy remains the explicit
  no-narratives fallback.

## Work

- Import the offline source/tests, consolidate configuration and locking, and expose
  one atomic evidence-refresh handoff.
- Add a typed freshness report for build evidence, strategy context, policies,
  narratives, and installed managed builds; reuse it in `status` and at the start of
  `sync`.
- Add the presentation mapper and complete narrative admission without changing
  `cache.py`, `kv3_binary.py`, or the install transaction.
- Update schemas, preview JSON, README workflow, and artifact fingerprints when any
  presentation input changes.

## Proof

- Synthetic current/stale/malformed/missing artifact-chain tests, including proof that
  stale `sync` stops before Codex and before cache access.
- Exact core-action identity tests, player-first description tests, UTF-8 limits, and a
  state-composed ability fixture that was never observed as one complete path.
- Offline refresh smoke test ending in `load_build_evidence`, plus the normal full
  repository gate.

Traceability: [usage audit](../deadlock-build-usage-audit.md#phase-0-truth-and-routing),
[artifact requirements](../deadlock-build-policy-requirements.md#8-artifacts-fingerprints-and-freshness),
and [CLI requirements](../deadlock-build-policy-requirements.md#11-cli-release-and-pull-request-requirements).
