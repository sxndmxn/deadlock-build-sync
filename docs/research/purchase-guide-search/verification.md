# Verification record

## Result

The complete fast local gate passed after the test-cohort correction.
All 1,459 tests passed with warnings treated as errors.
The purchase-search test files contain 38 regression cases.
Statement coverage is 97.24%; branch coverage is 92.08%.
These coverage figures apply to the configured product and script coverage scope.
They do not claim 90% coverage of the isolated experiment tools.

| Check | Result |
| --- | --- |
| `uv lock --check` | Passed |
| `uv sync --frozen` | Passed |
| `uv run ruff format --check .` | Passed |
| `uv run ruff check .` | Passed |
| `uv run ty check` | Passed |
| `uv run deptry .` | Passed |
| `uv run tach check` | Passed |
| `uv run complexipy` | Passed |
| `uv run coverage erase` | Passed |
| `uv run coverage run -m pytest -W error` | Passed; 1,459 tests |
| `uv run coverage json` | Passed |
| `uv run tools/quality_gate.py` | Passed |
| `uv run vulture` | Passed |
| `uv run pylint --disable=all --enable=duplicate-code src scripts` | Passed |
| `uv pip check` | Passed |
| `uv build` | Passed |

New experiment Python files were visible to the tracked-file numeric gate through Git intent-to-add entries.
No quality limit or validator was weakened.
The [machine-readable check record](results/quality-results.json) identifies the local logs.

## Experiment checks

- Width-one beam equals greedy under identical settings.
- A sufficiently wide beam equals exhaustive search on a small catalog.
- Beam preserves a lower immediate score that enables a better upgrade sequence.
- Independent mechanics replay verifies component consumption, prices, budgets, inventory limits, and active-item limits.
- Purchases preserve net worth unless the simulation adds income.
- Unsupported cells and patch mismatches fail safely.
- Candidate filtering preserves support in a reachable later wealth bin.
- Candidate filtering excludes unreachable wealth bins.
- Complete-core support uses exact ownership, not ancestor-expanded feasibility counts.
- Missing state cohorts remain unavailable instead of appearing as zero-owner evidence.
- Snapshot checkpoints use strictly earlier observations with the declared freshness limit.
- Duplicate hero appearances exclude the complete match.
- Duplicate ownership records still fail validation.
- Fixed Leiden seeds repeat connected communities in the regression fixture.
- Shared-core factoring reconstructs every complete variant.
- Shared ownership does not imply a shared purchase prefix.
- Display-size calculations include category gaps.
- Test access rejects missing freezes and changed code or data.
- Paired resampling preserves match groups and deterministic repetition.

The optimization comparison verified 35,910 validation query records across both benchmark modes and all nine method-width combinations.
Only time and attempted-action counts changed.
The corrected extraction preserved all training and validation counts and sampled queries.
It also preserved all 228 reconstructed inventory files across those two partitions.
Structure proposals remained identical apart from metadata and timing.

The corrected final test replay validated 162,264 emitted purchase actions across all methods and both benchmark modes.
Those action counts include repeated hypothetical actions across alternative paths and methods.
They are not distinct observed purchases.

## Packaging and execution scope

The built wheel contains the product package and excludes `tools/purchase_search`.
The experiment adds no production package dependency or Steam write path.
No live Steam sync was performed.
No live client layout was tested.
The slow mutation gate was not run because the Steam write boundary did not change.
Fixture and offline validation do not certify live builds.

## Failed attempt

The first frozen test attempt stopped at the duplicate-hero ownership guard.
The correction excludes one affected test match under a general cohort rule.
The [correction report](test-data-correction.md) records this failure and the subsequent fixed-configuration rerun.
No search parameter changed after test access.
