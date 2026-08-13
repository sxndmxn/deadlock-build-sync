---
title: "Deadlock build-policy monitoring and rollback runbook"
status: implementation-contract
---

# Monitoring and rollback runbook

> [!CAUTION]
> Current production recommendations remain mechanics-backed and descriptive. A
> decision log or OPE result does not by itself authorize a causal claim, automated
> learning, or a live Steam write.

## Signals

| Boundary | Required signals |
|---|---|
| Source | snapshot age, mechanics identity, schema decode status |
| Runtime policy | invalid-state rate, exposures, adoptions, deviations, recalculations, unhandled branches |
| Statistical | held-out calibration error, selective risk/coverage, recommendation concentration |
| Artifact | path/render rejection, exact-compatible reuse and regeneration |
| Steam mutation | install failures, restore attempts/failures, preservation fingerprint |

All counts use the unit printed beside them. `exposure`, `adoption`, and `deviation`
are never substituted for purchase-event volume.

## Decision precedence

```text
mechanics/schema/preservation/calibration/restore failure
  └─> ROLLBACK to the last compatible snapshot and policy set

stale snapshot/path rejection/render rejection/install failure
  └─> REFUSE the new policy; retain the last compatible artifact

invalid-state/unhandled-branch/concentration drift
  └─> ALERT and investigate; do not silently widen queues or epochs

no triggered rule
  └─> HEALTHY
```

## Mandatory rollback conditions

| Condition | Immediate action | Recovery evidence |
|---|---|---|
| Mechanics fingerprint mismatch | Stop admission and rollback. | Re-export from one pinned client; rerun mechanics and every-path tests. |
| Material held-out calibration failure | Disable predictive claim class and rollback. | Re-select threshold on validation only; pass later patch test fold. |
| Schema decode failure | Refuse artifact and rollback. | Decode, validate, and round-trip a regenerated artifact. |
| User-data preservation change | Stop all writes and restore backup. | Match pre-write out-of-scope fingerprint and decode restored cache. |
| Restore failure | Stop and surface backup path. | Manual recovery review; never overwrite the backup. |

## Investigation checklist

- [ ] Record the rejected snapshot and policy IDs.
- [ ] Identify the last exact-compatible snapshot and complete policy set.
- [ ] Preserve source manifests, evaluation report, cache backup, and failure output.
- [ ] Confirm queue, rank, epochs, client version, and cutoff before comparing metrics.
- [ ] Separate data drift, mechanics drift, rendering failure, and mutation failure.
- [ ] Add a regression fixture before re-enabling the boundary.
- [ ] Never weaken a validator to admit the failed artifact.

## Privacy and retention

Recommendation events use
[`schemas/decision-log.schema.json`](../schemas/decision-log.schema.json). They retain
candidate order, exposure, adoption/deviation, recalculation, propensity or experiment
assignment, and bounded outcomes for at most 90 days. Steam IDs, account IDs, player IDs,
persona names, email addresses, and IP addresses are prohibited.

## Verification references

- Coverage manifest: [`evaluation-coverage.json`](evaluation-coverage.json)
- Illustrative layer-separated report:
  [`evaluation-sample-report.json`](evaluation-sample-report.json)
- Deterministic implementation:
  [`evaluation.py`](../src/deadlock_build_sync/evaluation.py)
- Regression suite: [`test_evaluation.py`](../tests/test_evaluation.py)
