The corrections reject incomplete SQL evidence and preserve concurrent cache changes when installation stops before replacement.
The review used base commit `d19558f`.

| Correction | Regression coverage |
| --- | --- |
| Require explicit reward eligibility for every player. | Null, false, and true flags |
| Check complete source matches after candidate selection. | Extra players with missing, excluded, and eligible ranks |
| Preserve unknown team wealth for incomplete observations. | Null wealth, unequal arrays, and duplicate timestamps |
| Exclude purchases after match completion. | Extraction, production beam counts, and research observations |
| Load research statistics from SQL files. | Result counts, AST checks, and data fingerprint changes |
| Restrict split-table detection to the current database and schema. | Unrelated schemas and attached catalogs |
| Restore backups only after an actual replacement failure. | Concurrent favorites, validation failures, and synchronization failures |
| Refuse restoration while Deadlock is running. | Game start after replacement and exact refusal diagnostics |

The evidence methods are now `eclat-leiden-pairwise-v4` and `eclat-leiden-beam16-v2`.
Older evidence requires regeneration.
Resume requests must use a source manifest with the current extraction method.
Regression tests reject previous method versions and manifests without that field.

The version change altered two reference hashes.
The bundle comparison changed only snapshot, policy, and evidence identity fields.
The export comparison changed only its method version and derived artifact identity.
The tests retain their exact reference hashes and content assertions.

Verification used Python 3.13.15, DuckDB 1.5.5, and SQLFluff 4.3.0.

| Check | Result |
| --- | --- |
| `uv lock --check` | Passed |
| `uv sync --frozen` | Passed |
| `uv run ruff format --check .` | Passed |
| `uv run ruff check .` | Passed |
| `uv run sqlfluff lint .` | Passed; 142 SQL files |
| `uv run ty check` | Passed |
| `uv run deptry .` | Passed |
| `uv run tach check` | Passed |
| `uv run complexipy` | Passed |
| `uv run coverage erase` | Passed |
| `uv run coverage run -m pytest -W error` | Passed; 1,597 tests |
| `uv run coverage json` | Passed; 97.13% statement coverage and 92.04% branch coverage |
| `uv run tools/quality_gate.py` | Passed |
| `uv run vulture` | Passed |
| `uv run pylint --disable=all --enable=duplicate-code src scripts` | Passed |
| `uv pip check` | Passed |
| `uv build` | Passed |
| Wheel installation and CLI smoke tests outside the checkout | Passed |
| Wheel SQL inventory and installed file comparison | Passed; 53 SQL files |
| `uv run mutmut run --max-children 4 '*'` | Completed for the complete Steam data boundary |
| `uv run mutmut export-cicd-stats` | Passed |
| `uv run tools/mutation_gate.py` | Passed; 1,973 mutants detected |
| Live Steam sync and live evidence generation | Did not run |
| Live extraction performance measurement | Did not run |

The mutation run detected 1,966 mutants through test failures and seven through timeouts.
No mutants survived, lacked tests, or remained unclassified.

Match admission now checks all player rows for each candidate match.
This requires an additional source read.
The fixture tests verify correctness but do not measure its live extraction cost.
Fixture validation does not certify live builds.
