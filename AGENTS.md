# AGENTS.md

## Language

Use ASD-STE100 Simplified Technical English for all prose you write.
This includes responses, documentation, comments, error messages, commit messages, and pull request descriptions.

- Use words with their approved meanings and parts of speech. Use established technical nouns and verbs where necessary.
- Use active voice. In descriptions, use passive voice only when the person or system that acts is unknown.
- Limit each instruction sentence to 20 words. Limit each descriptive sentence to 25 words.
- Give one instruction per sentence. Keep each paragraph about one subject.
- Use the same term for the same concept throughout the work.
- Keep words that are necessary for correct grammar and meaning.
- Do not use contractions.

## Direct statements

- State the result, action, or requirement first.
- Use literal language. Remove metaphors, idioms, decorative phrases, rhetorical questions, and promotional language.
- Do not use humor, slang, praise, or conversational filler.
- Give facts and concrete details. Identify assumptions and uncertainty when they affect the answer.
- Do not add introductions, repeated summaries, or explanations that the task does not require.
- For code requests, give the solution. Explain it only when requested or necessary to identify a material limitation.

## Names

- Use precise engineering terms for every name you create or change.
- Apply this rule to files, directories, scripts, functions, variables, classes, tests, commits, and branches.
- Name the actual action, purpose, or content. Use the terms an engineer would use in a technical specification.
- Do not use jokes, fashionable terms, casual abbreviations, or clever wordplay.
- Use established project terms, standard abbreviations, and the required identifier format.
- Keep exact commands, API names, and external identifiers. Do not change their technical meaning to simplify the language.
- Apply these rules throughout the work. The examples do not limit their scope.

## Examples

- Name a dashboard deployment script deploy_dashboards.sh.
- Name a record validation function validate_records.
- Write “change the parameter” instead of “turn the dial.”
- Write “this requirement still applies” instead of “this point earns its keep.”

Before you finish, remove unnecessary words and replace unclear names.

Language reference: ASD-STE100.

## Repository purpose

`deadlock-build-sync` is a CLI that primarily supports Linux.
It uses current Deadlock analytics to generate private hero builds with tactical instructions that supplied evidence supports.
It installs the builds under Steam's **My Builds**.
The main command is:

```bash
deadlock-build-sync sync
```

The command must generate, validate, back up, and install every eligible guide.
It must not damage or discard user-owned Steam data.

## Required safety rules

- Treat Steam files as user data. Refuse writes while Deadlock is running.
- Create a backup that supports recovery before each write.
- Validate a temporary replacement before installation. Replace the destination file atomically.
- Preserve favorites, saved builds, selected builds, and unrelated private builds.
  Update only entries with the managed marker.
- Keep description generation separate from Steam data writes.
  Use deterministic code for data collection, fingerprints, validation, serialization, installation, and description generation.
  Do not use models for these operations.
- Support tactical prose with supplied evidence.
  Use hero abilities, ability order, item mechanics, purchase windows, rank cohort, patch, match counts, and match duration.
  Do not invent mechanics. Do not state that analytics prove causation.
- Reject incomplete heroes. Reject stale or malformed artifacts.
  Do not weaken validators to accept a generated response.
- Keep `sync` safe to repeat. Reuse artifacts with compatible fingerprints.
  Make managed build updates idempotent.

## Architecture boundaries

- Follow the crate dependencies and public interfaces in [docs/architecture.md](docs/architecture.md).
  Review ownership and dependency direction before changing a boundary.
- `deadlock-data` owns shared validation, fingerprints, snapshots, and artifact writes.
- `deadlock-input` owns synchronous API access and item mechanics.
- `deadlock-guides` owns deterministic analytics, policies, descriptions, and artifact admission.
- `deadlock-analysis` owns optional DuckDB extraction and numerical production.
  It cannot import Steam storage.
- `deadlock-steam` owns KV3, protobuf, cache installation, and recovery.
  Errors in this crate can damage user data.
- `deadlock-build-sync` controls workflows through the library interfaces.
  Keep `sync` simple to use without arguments.
  Retain the review and debugging commands.
- Reject cyclic crate and module dependencies.
- Enforce the import boundaries in `arch-lint.toml` through the complete local gate.
  Keep Arch-lint warnings at zero.
- Use a dependency only when its scope, maintenance, and implementation benefit justify its cost.
  Do not add a VDF package for the local account-name lookup.

## Verification and release requirements

- Use the documented Cargo workflow and pinned Rust toolchain.
  SQLFluff runs separately through `uvx`.
  This repository has no Node package workflow.
- Use synchronous code. Do not add async functions, async blocks, await expressions, or asynchronous runtimes.
- Forbid unsafe repository code and treat warnings as errors.
  Keep Clippy `all`, `pedantic`, and `nursery` findings at zero.
  Keep cognitive complexity at or below 21.
- Identify the checks you ran in pull request verification notes.
  State which checks passed, failed, or did not run.
  Fixture validation does not certify live builds.
- Do not add unit tests until the user requests them.
  Verify correctness and safety changes with isolated executable checks and existing reference fixtures.
- Run the complete fast local gate in [docs/quality-gates.md](docs/quality-gates.md) before you deliver changes.
- For packaging changes, inspect the release archive outside the source checkout.
  Run a smoke check on its executable outside the source checkout.
- Do not run a live Steam sync without explicit user authorization.
  After a live run, report the artifact directory, cache path, backup path, created and updated counts, and skipped heroes.
