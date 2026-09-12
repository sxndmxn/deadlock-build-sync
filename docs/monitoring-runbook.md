---
title: "Deadlock monitoring and recovery runbook"
status: current-operations-and-proposed-monitoring
---

# Monitoring and recovery runbook

## Implemented operations

The Rust CLI provides explicit commands and artifact validation.
It does not run a continuous monitoring service or automatic policy rollback.

| Command or boundary | Current behavior |
| --- | --- |
| `status` | Reports freshness stages using artifacts, API inputs, and the selected Steam location. |
| `quality-report` | Reports evidence support, compatibility, purchase windows, and optional runtime-policy replay results. |
| `trace-summary` | Summarizes recorded operation traces. |
| Artifact admission | Rejects malformed, incomplete, stale, or incompatible artifacts. |
| Artifact installation | Preserves the previous bundle on handled installation failures or reports its recovery location. |
| Steam installation and restoration | Checks the running process, creates recovery backups, and validates replacement data. |

`quality-report` returns zero for `pass`, one for `fail`, and two for `unevaluated`.
Replay requires pinned assets and compatible replay records.
These checks do not establish improved match outcomes or causal item effects.

## Investigation and recovery

- Record the rejected snapshot, policy identifiers, and command output.
- Preserve source manifests, artifacts, traces, and Steam backups.
- Compare rank, patch, client version, cutoff, and fingerprints before reusing artifacts.
- Stop writes if preservation or restoration fails.
- Inspect recovery files before another restoration attempt.
- Do not weaken a validator to accept rejected artifacts.

The `restore --latest` command writes Steam data.
A backup inspection must establish compatibility before recovery.
Do not delete backup files during an investigation.

## Proposed monitoring requirements

The following requirements do not describe implemented Rust telemetry or automatic actions:

- Continuous exposure, adoption, deviation, and recalculation counts.
- Continuous invalid-state monitoring, concentration drift alerts, and calibration alerts.
- Automatic policy rollback and automatic predictive-claim disabling.
- A recommendation-event collection service with a 90-day retention limit.

The [decision-log schema](../schemas/decision-log.schema.json) describes proposed event records.
Its existence does not establish event collection or retention enforcement.
Purchase-event volume is not an exposure or adoption count.

## References

- Current [Rust quality report](../crates/deadlock-guides/src/quality_report.rs) and [replay evaluation](../crates/deadlock-guides/src/quality_evaluation.rs).
- Historical [coverage manifest](evaluation-coverage.json) and [illustrative evaluation report](evaluation-sample-report.json).
- Archived [Python evaluation module](https://github.com/sxndmxn/deadlock-build-sync/blob/d603d6b53bb110d0ac48a689f037861e6453b243/src/deadlock_build_sync/evaluation.py).
- Archived [Python regression suite](https://github.com/sxndmxn/deadlock-build-sync/blob/d603d6b53bb110d0ac48a689f037861e6453b243/tests/test_evaluation.py).

Historical evaluation results do not certify the Rust executable or current live builds.
