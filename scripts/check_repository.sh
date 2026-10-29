#!/usr/bin/env bash
set -euo pipefail

repository_directory=$(git rev-parse --show-toplevel)
pushd "$repository_directory" >/dev/null
trap 'popd >/dev/null' EXIT

check_release=false
case "${1:-}" in
    '') ;;
    --release) check_release=true ;;
    *) printf 'Usage: bash scripts/check_repository.sh [--release]\n' >&2; exit 1 ;;
esac
test "$#" -le 1
export CARGO_BUILD_JOBS=${CARGO_BUILD_JOBS:-2}
export CARGO_INCREMENTAL=0

require_version() {
    local expected=$1
    shift
    local actual
    actual=$("$@" --version)
    if ! rg --quiet --fixed-strings "$expected" <<<"$actual"; then
        printf 'Required tool version: %s. Installed version: %s\n' "$expected" "$actual" >&2
        return 1
    fi
}

require_version 'cargo 1.92.0 ' cargo
require_version 'arch-lint 0.6.0' arch-lint
require_version 'rust-code-analysis-cli 0.0.25' rust-code-analysis-cli
require_version 'cargo-deny 0.20.2' cargo deny
command -v fd jaq rg >/dev/null

python_paths=$(git ls-files --cached --others --exclude-standard -- '*.py' '*.pyi' '*.pyc' '*.pyo' '*.whl' pyproject.toml uv.lock .python-version)
if [ -n "$python_paths" ]; then
    printf 'Python files are prohibited:\n%s\n' "$python_paths" >&2
    exit 1
fi

cargo fmt --all --check
output_directory=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/deadlock-check.XXXXXX")
mkdir "$output_directory/metrics"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
    printf 'metrics_directory=%s\n' "$output_directory" >>"$GITHUB_OUTPUT"
fi
rust-code-analysis-cli -p crates -I '*.rs' -f error -j 2 |
    tee "$output_directory/parser-errors.txt"
test ! -s "$output_directory/parser-errors.txt"
rust-code-analysis-cli -p crates -I '*.rs' -m -O json --pr \
    -o "$output_directory/metrics" -w -j 2
source_count=$(fd --type f --extension rs . crates | wc -l)
report_count=$(fd --type f --extension json . "$output_directory/metrics" | wc -l)
test "$source_count" -gt 0
test "$source_count" -eq "$report_count"
if ! fd --type f --extension json . "$output_directory/metrics" --exec-batch jaq -s -e '
    [.[] | . as $file | .. | objects
      | select(.kind? == "function" and .metrics.cognitive.sum > 21)
      | {file: $file.name, function: .name, line: .start_line,
         cognitive: .metrics.cognitive.sum}]
    | if length == 0 then true else ., false end
' >"$output_directory/complexity-results.json"; then
    printf 'Rust complexity validation failed.\n' >&2
    rg --invert-match '^true$' "$output_directory/complexity-results.json" >&2 || true
    exit 1
fi
printf 'Rust code metrics: %s\n' "$output_directory"

cargo lint
arch-lint --config arch-lint.toml check --engine syn .
uvx --from sqlfluff==4.3.0 sqlfluff lint crates/deadlock-analysis/sql
uvx --from sqlfluff==4.3.0 sqlfluff parse crates/deadlock-analysis/sql --format json --code-only |
    jaq -e 'all(.. | objects; has("wildcard_expression") | not)'
cargo doc --workspace --all-features --no-deps --locked
cargo build --workspace --bins --examples --locked
debug_directory=${CARGO_TARGET_DIR:-target}/debug
"$debug_directory/examples/check_imbues"
"$debug_directory/examples/check_safety"

cli_path="$debug_directory/deadlock-build-sync"
"$cli_path" --help >/dev/null
for command in sync build install status restore; do
    "$cli_path" "$command" --help >/dev/null
done
cargo deny --locked check --deny warnings

if "$check_release"; then
    cargo build --package deadlock-build-sync --release --locked
    release_binary=$(realpath "${CARGO_TARGET_DIR:-target}/release/deadlock-build-sync")
    sh scripts/package_release.sh "$release_binary" x86_64-unknown-linux-gnu
fi
printf 'Repository checks passed.\n'
