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

- Follow the dependency layers and public interfaces in `tach.toml` and [docs/architecture.md](docs/architecture.md).
  Do not add a dependency only to remove a Tach error.
  Review the module owner and dependency direction first.
- `api.py`, `purchase_guide.py`, `ability_order.py`, and `power_curve.py` contain deterministic analytics.
- `strategy_context.py` exports evidence and calculates fingerprints.
- `scripts/generate_narratives.py` generates descriptions deterministically and validates artifacts.
- `narratives.py` accepts reviewed artifacts for use in guides.
- `protobuf.py`, `kv3_binary.py`, and `cache.py` form the Steam write boundary.
  Errors in these modules can damage user data.
- `cli.py` controls user workflows. Keep the `sync` command simple to use without arguments.
  Retain the commands for review and debugging.

## Verification and release requirements

- Use the documented Python and uv workflow.
  This repository has no Node package workflow.
  Do not use npm or pnpm as a replacement for its quality gates.
- Identify the checks you ran in pull request verification notes.
  State which checks passed, failed, or did not run.
  Fixture validation does not certify live builds.
- Add a regression test for every correctness or safety fix.
- Run the complete fast local gate in [docs/quality-gates.md](docs/quality-gates.md) before you deliver changes.
- For packaging changes, inspect the built wheel outside the source checkout.
  Run a smoke test on that wheel outside the source checkout.
- Do not run a live Steam sync without explicit user authorization.
  After a live run, report the artifact directory, cache path, backup path, created and updated counts, and skipped heroes.
