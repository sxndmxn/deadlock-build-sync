# Reproduction instructions

## Inputs

Use the saved source run `20260909T001949Z`, source snapshot version 64.
The source directory must contain `raw/analysis.duckdb`, `raw/items.json`, `raw/patches.json`, and the source manifest.
The source database opens read-only.
Large source and generated artifacts are not included in this research directory.

The default source is under the current user's `.local/state/deadlock-build-sync/offline/results/` directory.
Every data command accepts `--source` to use another location.
Run the commands from the repository root.
Use the documented Python and uv environment.

```bash
uv sync --frozen
uv run python -m tools.purchase_search.dataset train
uv run python -m tools.purchase_search.dataset validation
uv run python -m tools.purchase_search.structures \
  --output generated/purchase-guide-search/structures-corrected.json
```

The final cache is `generated/purchase-guide-search/data-corrected/`.
Its fingerprint is `d2cc62597d0bdbf081e57dc85694e7afb5373a95f31f56aa40d906239f06bbea`.
The cache before the duplicate-hero correction remains under `data-aligned/`.
Its fingerprint is `2c5c74ec15ce1f28577102999015b5075bd0214c0c0fe050aeb81b50ac54edb3`.
The two training and validation datasets have identical statistical contents.

## Validation studies

The sensitivity runner evaluates validation data only.
Its first 28 cases test individual settings.
Its final 16 cases test combinations of smoothing, support, depth, and cost weighting.
The `--cases` argument selects case-name prefixes.
The structure runner tests nine proposal settings.

```bash
uv run python -m tools.purchase_search.sensitivity \
  --structures generated/purchase-guide-search/structures-corrected.json \
  --output generated/purchase-guide-search/reproduction-sensitivity

uv run python -m tools.purchase_search.structure_sensitivity \
  --output generated/purchase-guide-search/reproduction-structures
```

The first two studies use 24 sampled decisions per hero and all 342 guide scenarios.
The final validation comparison uses 96 decisions per hero.
The saved final validation files have the older data fingerprint.
The [cache comparison](results/cohort-correction-verification.json) verifies their equivalence after the cohort correction.

## Freeze before test access

The saved research artifacts include the original and corrected freeze records.
The original freeze intentionally fails against the corrected extraction code.
The corrected freeze identifies the final implementation.
No implementation file changed after the corrected freeze.

A separate reproduction can require a new freeze when source paths or serialized training metadata change.
Use the same final settings for that reproduction.
Do not use repeated test runs to tune settings.

```bash
uv run python -m tools.purchase_search.freeze \
  --data generated/purchase-guide-search/data-corrected \
  --structures generated/purchase-guide-search/structures-corrected.json \
  --settings docs/research/purchase-guide-search/final-settings.json \
  --output generated/purchase-guide-search/reproduction-freeze.json

uv run python -m tools.purchase_search.dataset test \
  --frozen generated/purchase-guide-search/reproduction-freeze.json
```

The freeze rejects existing output files instead of replacing a prior record.
The final original test uses `docs/research/purchase-guide-search/frozen-specification-corrected.json`.

## Final benchmark commands

Use the following command for each mode, `guides` and `decisions`.
Use `--partition validation` without `--frozen` for a validation reproduction.

```bash
uv run python -m tools.purchase_search.benchmark guides \
  --partition test \
  --methods greedy:1 beam:4 beam:8 beam:16 beam:32 \
            diverse:16 eclat:8 eclat:16 leiden:16 \
  --depth 6 --prior 1000 --joint-support 200 \
  --structures generated/purchase-guide-search/structures-corrected.json \
  --frozen generated/purchase-guide-search/reproduction-freeze.json \
  --output generated/purchase-guide-search/reproduction-test-guides.json

uv run python -m tools.purchase_search.benchmark decisions \
  --partition test \
  --methods greedy:1 beam:4 beam:8 beam:16 beam:32 \
            diverse:16 eclat:8 eclat:16 leiden:16 \
  --depth 6 --prior 1000 --joint-support 200 \
  --structures generated/purchase-guide-search/structures-corrected.json \
  --frozen generated/purchase-guide-search/reproduction-freeze.json \
  --output generated/purchase-guide-search/reproduction-test-decisions.json
```

The remaining frozen defaults are cost exponent 0.5, diversity strength 0.02, three alternatives, and 96 sampled decisions per hero.
The scorer also uses discount 0.97, uncertainty multiplier 0.5, and minimum item-cell support 30.
A beam width is an internal search limit, not a number of displayed builds.

## Analysis

```bash
uv run python -m tools.purchase_search.comparison \
  generated/purchase-guide-search/reproduction-test-guides.json \
  generated/purchase-guide-search/reproduction-guide-analysis.json

uv run python -m tools.purchase_search.comparison \
  generated/purchase-guide-search/reproduction-test-decisions.json \
  generated/purchase-guide-search/reproduction-decision-analysis.json
```

The analysis uses 2,000 cluster resamples with seed 23.
Run timing comparisons sequentially on an otherwise idle machine.
Keep data preparation, search, evidence checking, and structure preparation times separate.

## Saved artifacts

| Artifact | Local generated path |
| --- | --- |
| Final validation guides | `validation-guides-optimized.json` |
| Final validation decisions | `validation-decisions-optimized.json` |
| Final corrected test guides | `test-guides-corrected.json` |
| Final corrected test decisions | `test-decisions-corrected.json` |
| Initial parameter study | `sensitivity-validation/` |
| Combined parameter study | `combined-validation/` |
| Structure study | `structure-sensitivity/` |
| Final structure proposals | `structures-corrected.json` |
| Optimization equality check | `optimization-verification.json` |
| Cohort correction equality check | `cohort-correction-verification.json` |
| Final gate logs | `quality-corrected/` |

All paths in this table are relative to `generated/purchase-guide-search/`.
The smaller [results artifacts](results/) retain aggregate measurements for review without the large cache.
The [checksum record](results/artifact-sha256.json) identifies the original generated result files.
Its freeze entry refers to the corrected freeze in this research directory.
The source query count, method settings, machine details, fingerprints, and calibration results remain in the benchmark documents.
