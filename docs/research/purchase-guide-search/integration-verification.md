# Integration verification

The optional beam integration passed the complete fast local gate.
The branch is `experiment/purchase-guide-search`.
No commit or live Steam sync occurred.
The unrelated `docs/repository-review-prompt.md` file remains unchanged.

## Results

All three methods produced 142 complete guide groups across 38 heroes.
The current baseline and ordering control contain 800 variants each.
Full beam contains 787 variants, including 109 cores absent from the baseline.
Full beam supplies 39 default guides and 184 variants through beam search.
The other 103 defaults retain current-guide fallbacks.
Full beam changes 29 default cores and 36 default component paths.
The ordering control changes 41 component paths and preserves every default core.

Every serialized route passed an independent mechanics replay.
The replay checked 800 current variants, 800 ordering-control variants, and 787 full-beam variants.
No route changed its final core or reported cost during replay.
No variant lacked a supported item action in a price tier.
Every variant has a 16-step ability order.
The production pipeline validates ability timing and imbue targets.

The logical display check found no overflow in either beam output.
The current output exceeds the same 900-by-650 target in 138 groups.
This comparison does not establish a live-client display defect.
The target is a layout model.
Full beam omits 160 optional variant categories and 3,352 default-tier item cards from compact views.
Complete Markdown and JSON retain all variants and pools.

The default core remains unchanged for Infernus, Viscous, Kelvin, and Abrams.
Viscous changes the order of its first core.
The first Lash core changes from Quicksilver Reload, Headhunter, Recharging Rush, and Siphon Bullets.
Its replacement uses Quicksilver Reload, Bullet Resist Shredder, Recharging Rush, and Dispel Magic.
Cost falls from 12,800 to 8,000 souls.
Its even-state observed rate falls from 61.2% to 58.4%.
The confidence intervals overlap.
This result does not establish a better build.

The current method has three defaults with `outcome_supported` status.
The ordering control also has three.
Full beam has one.
These statuses describe separate observational checks, not causal effects.
No untouched later evaluation establishes a win-rate benefit.
The generator therefore remains optional.

## Runtime and recovery

The isolated master evidence export took 829.6 seconds with four workers.
Full beam searched 426 group/state requests in 4.8 seconds of summed search time.
The ordering control searched 2,400 core/state requests in 1.2 seconds of summed search time.
These measurements exclude data loading, model construction, and evidence generation.

Final frozen-candidate validation took 207.8 seconds for full beam and 226.3 seconds for the ordering control.
These recovery runs used one worker.
Complete guide generation took 710.3 seconds for current, 200.4 seconds for full beam, and 57.2 seconds for the ordering control.
API cache state differs between these runs.
Do not interpret these times as a direct speed comparison between generators.

API rate limits interrupted initial guide requests.
The comparison then reused captured responses and limited uncached requests.
Disk limits interrupted repeated evidence exports.
Filesystem compression reduced generated-file sizes without changing their content hashes.
Recovery validated the saved candidate families before writing complete replacement artifacts.
Final output identities match their guide-generation records.

Candidate snapshots record their original implementation hashes.
The result summary also records the final implementation hash.
Later refinements strengthen metadata validation and make ordering-control fallback reasons more precise.
They do not change the frozen candidate family.

## Checks

The final test run passed 1,528 tests.
Statement coverage exceeds 97%.
Branch coverage exceeds 91%.
The numeric gate passed its file-size, complexity, coverage, CRAP, and type-name limits.

All required commands passed:

```text
uv lock --check
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
uv run deptry .
uv run tach check
uv run complexipy
uv run coverage erase
uv run coverage run -m pytest -W error
uv run coverage json
uv run tools/quality_gate.py
uv run vulture
uv run pylint --disable=all --enable=duplicate-code src scripts
uv pip check
uv build
```

The built wheel contains the beam modules and SQL resource.
An isolated environment outside the checkout passed the wheel smoke test.
The slower Steam-boundary mutation gate did not run.
No Steam storage module changed.
Fixture tests and recorded-cohort generation do not certify live builds.

## Artifacts

- [All group comparisons](integration-comparison.md)
- [Machine-readable summary and provenance](results/integration-summary.json)
- [Integration commands and constraints](integration.md)
- [Accepted plan](integration-plan.md)

Complete local guide artifacts are under `generated/beam-integration/current`, `generated/beam-integration/beam-order`, and `generated/beam-integration/beam`.
Each directory contains `builds.json`, policies, narratives, strategy context, and complete build Markdown.
The source directory retains frozen nominations and search diagnostics.
The `api` directory retains shared response bytes and hashes.

Reproduce serialized-route verification with:

```bash
uv run python -m tools.beam_comparison.replay --root generated/beam-integration
```
