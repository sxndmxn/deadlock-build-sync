---
name: library-documentation
description: Fetch upstream documentation when a task depends on this repository's library APIs, configuration, or version compatibility.
---

# Library Documentation

Use the package's own documentation to verify API choices for the requested task.
Open the relevant entry in [the library index](references/libraries.md).
Fetch only documentation needed for the current package or question.

## Versions and Features

Check the package version in `Cargo.lock` and its enabled features in the root and consuming crate manifests.
Resolve dependency aliases and multiple locked versions through the consuming crate's dependency entry.
Use `cargo metadata --locked --format-version 1` when the dependency relationship is unclear.

Fetch the relevant latest API page directly from the index.
Check its displayed version against the resolved package version before using its API.
When versions differ, fetch the corresponding locked-version API page for implementation decisions.
Use the latest documentation for current capabilities and requested upgrade comparisons.
Identify APIs that require a package upgrade, additional features, or a newer Rust toolchain.
Change dependencies only when the requested work includes that change.

## Source Selection

Follow documentation links to the relevant function, type, module, or configuration reference.
Use upstream source and release notes when the API documentation does not answer the question.
Prefer the source tag or revision that matches the selected package version.
If hosted version documentation is unavailable, inspect the matching package source in the local Cargo registry.
State any unresolved behavior instead of inventing an API or using documentation from an incompatible version.
Use search only when direct upstream documentation does not resolve the question.
Cite the specific documentation page when explaining an API choice.

For DuckDB SQL, use the engine documentation linked in the index.
Check the actual engine version; the Rust wrapper version is a separate identifier.
Check extension versions when extension behavior affects the answer.

## Index Maintenance

The index covers direct external dependencies, including build and development dependencies when present.
Look up transitive dependencies from `Cargo.lock` only when the task involves them.
Use workspace source for local crates.
Update affected index entries when adding, removing, or upgrading a direct dependency.
Keep documentation as links; do not copy package manuals into this repository.
