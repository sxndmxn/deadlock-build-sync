---
name: deadlock-build-preview
description: Generate and display complete Deadlock hero builds from production artifacts. Use when the user requests builds or exact Steam output.
---

# Deadlock Build Preview

Show the complete production build for each requested hero in Markdown.
A request to see builds does not authorize Steam installation.

## Generation

Use the repository's `build` command for generation without Steam access.
Confirm that the executable matches the checkout before calling its output the current implementation.
Specify `--hero` for each requested hero; omission generates every eligible hero.
Use a separate artifact directory to preserve the existing installation bundle.

```bash
cargo run --locked -- build --hero viscous --build-evidence /absolute/path/build-evidence.json --artifacts /absolute/path/preview-artifacts --format markdown
```

Replace the example paths with the selected evidence file and preview directory.
Keep the generator compatible with the evidence and the user's request.
Confirm current options in `crates/deadlock-build-sync/src/cli_arguments.rs` when selecting a different generation mode.
Use saved output when requested; otherwise generate the requested build.
Distinguish a new generation from fresh analytics collection.
Report stale or incompatible evidence instead of weakening validation or silently substituting another snapshot.

## Output Authority

Read the generated `builds.json` index to locate each build's Markdown and `steam_json` artifact.
Use the serialized `steam_build` or corresponding `.steam.json` as the authority for Steam content.
The `build_output.rs` file writes Markdown and Steam JSON from the same presentation.
Read `crates/deadlock-build-sync/src/build_output.rs` when checking that relationship.

Preserve every serialized panel, item order, purchase instruction, and build note in the displayed output.
Show all builds for the requested hero unless the user selects a specific build.
Do not replace a complete build with its core items or an intermediate item pool.
Do not add absent tier panels, variants, or tactical advice to make the preview appear complete.
Report missing expected content as a discrepancy.
Keep internal route details separate from the Steam presentation when the user requests those details.

## Delivery

Print the build Markdown in the response; file links alone do not complete a request to see builds.
Keep surrounding explanation brief without removing build content.
Identify the generation method, snapshot or evidence timestamp, and artifact directory once.
State whether the output came from this execution or existing artifacts.
Report generation failures and skipped heroes explicitly.
Do not describe generated artifacts as installed builds without installation evidence.
