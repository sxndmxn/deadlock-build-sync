# Test maintenance

Each test file checks a specific product area.
The fixture modules below contain shared test data constructors.
Import shared test data constructors from these modules.
Do not import one test file from another.

| Test inputs | Fixture module |
| --- | --- |
| Evidence documents, item records, fingerprints | `build_evidence_fixtures.py` |
| Core alternatives and situational branches | `build_evidence_policy_fixtures.py` |
| Discovery documents and hero rank history | `discovery_fixtures.py` |
| Discovery graphs, generated match data, frozen outputs | `offline/discovery_fixtures.py` |
| Policies, claims, validation context | `policy_fixtures.py` |
| Recommendation inputs and decision state documents | `recommendation_fixtures.py` |
| Narrative guides and catalogs | `narrative_fixtures.py` |
| Evaluation records | `evaluation_fixtures.py` |
| Decoded build details | `rendering_fixtures.py` |
| JSON conversion for output snapshots | `serialization_fixtures.py` |

Other fixture modules remain beside their tests. Keep a helper in its test file
when no other file needs it. Fixture functions must return fresh mutable data on
each call. Use `dataclasses.replace` to change selected fields in a typed record.

For evidence validation, use `write_fingerprinted_evidence` after an intentional
field change. For fingerprint rejection tests, use `write_evidence_document` to preserve the
invalid fingerprint. Keep both paths distinct so setup cannot repair the error
under test.

Use named parameter cases for independent failures. Each case must start from
fresh data. Keep expected values in the test. Retain complete output snapshots
and separate Steam data preservation checks when setup is simplified.

Run a focused file while editing:

```bash
uv run pytest -W error tests/test_build_evidence_validation.py
```

Run the complete [fast gate](../docs/quality-gates.md#fast-local-gate) before
delivery. When test structure changes, compare covered statements and branches
with the previous run. A lower test count alone does not prove an improvement.
