# Quality gates

The repository uses local, repeatable Python tools as the source of truth. CI
runs all fast gates on each pull request and each push to `main`. A separate
scheduled or manual workflow runs the slower mutation gate.

## Enforced limits

| Check | Limit | Tool |
| --- | ---: | --- |
| Cyclomatic complexity per function | less than 22 | Radon through `tools/quality_gate.py` |
| Cognitive complexity per function | less than 22 | Complexipy |
| Halstead difficulty per function | less than 80 | Radon through `tools/quality_gate.py` |
| Physical lines per tracked Python file | less than 500 | `tools/quality_gate.py` |
| Statement coverage | at least 90% | Coverage.py |
| Branch coverage | at least 90% | Coverage.py |
| CRAP score per product function | less than 25 | `tools/quality_gate.py` |
| Surviving mutants in the Steam data boundary | zero | Mutmut |
| Dead code | zero | Vulture |
| Repeated code blocks | zero | Pylint similarities |
| `Any` or `Unknown` annotation names | zero | `tools/quality_gate.py` |

The numeric gate checks all tracked Python files for file size, cyclomatic
complexity, Halstead difficulty, and forbidden type names. Coverage and CRAP
apply to `src/` and `scripts/`. Complexipy checks `evals/`, `scripts/`, `src/`,
`tests/`, and `tools/`.

## Fast local gate

Run these commands from the repository root:

```bash
uv lock --check
uv sync --frozen
uv run ruff format --check .
uv run ruff check .
uv run ty check
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

The coverage command treats warnings as errors. `coverage.json` supplies both
repository coverage and per-function data for the CRAP calculation.

## Mutation gate

Run the complete mutation gate with:

```bash
uv run mutmut run
uv run mutmut export-cicd-stats
uv run tools/mutation_gate.py
```

Mutmut changes the cache, KV3, and protobuf modules that form the Steam data
boundary. This focused scope keeps the scheduled gate useful and gives the
highest-risk code a strict zero-survivor limit. Mutmut itself returns success
after a completed run even if a mutant survives. The final command reads its CI
summary and fails unless each mutant was detected by a test failure or timeout.
It also rejects untested, skipped, suspicious, interrupted, or crashed mutants.
Two profiler-output tests do not run inside Mutmut because Mutmut's function
wrappers change the frame names that those tests must check. The normal coverage
run still runs both tests.

## SonarLint in VS Code

The checked-in `.vscode/settings.json` keeps SonarLint in standalone mode. No
SonarQube server or project file is required. SonarLint findings appear in the
VS Code Problems view and its output channel.

The extension does not provide a stable repository CLI for CI or shell piping.
Use the commands above for pipeable, repeatable output. Treat SonarLint as an
extra editor check, not as the repository quality authority.
