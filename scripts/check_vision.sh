#!/usr/bin/env bash
# Fail when VISION.md changes after the commit that added it.
set -euo pipefail

repository_directory=$(git rev-parse --show-toplevel)
cd "$repository_directory"

if [ "$(git rev-parse --is-shallow-repository)" = true ]; then
    printf 'The vision check requires full Git history.\n' >&2
    exit 1
fi

changed_commits=$(git log --full-history --format='%h %s' --diff-filter=MDRTC -- VISION.md)
if [ -n "$changed_commits" ]; then
    printf 'VISION.md is immutable. These commits change it:\n%s\n' "$changed_commits" >&2
    exit 1
fi

added_count=$(git log --full-history --format=%H --diff-filter=A -- VISION.md | wc -l)
if [ "$added_count" -gt 1 ]; then
    printf 'VISION.md is immutable. More than one commit adds it.\n' >&2
    exit 1
fi

if [ "$added_count" -eq 1 ] && ! git diff --quiet HEAD -- VISION.md; then
    printf 'VISION.md is immutable. The working tree changes it.\n' >&2
    exit 1
fi
