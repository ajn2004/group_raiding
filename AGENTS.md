# AGENTS.md

This repository contains tooling for the Presynaptic World of Warcraft guild.

The long-term direction is a guild operating system centered on Discord, Warcraft Logs, deterministic raid analysis, historical raid-night replay, and eventually web and in-game clients.

Agents working in this repository should optimize for:

1. correctness;
2. reproducibility;
3. deterministic analysis;
4. test-driven development;
5. backwards compatibility;
6. narrow, reviewable changes;
7. preserving existing working behavior.

Do not optimize for maximum code generation or broad refactoring.

---

# Source of truth

For ticketed work, use this priority order:

1. the assigned Linear ticket and its acceptance criteria;
2. this `AGENTS.md`;
3. existing tests;
4. documented architecture;
5. existing implementation behavior.

If these disagree materially, do not silently choose one interpretation.

Prefer the smallest implementation that satisfies the ticket while preserving established behavior.

---

# Repository architecture

Current major areas include:

```text
app/
  db/                  Existing guild/player persistence
  discord_bot/         Discord bot and commands
  web_requests/        External service integrations
    warcraft_logs/
  pull_coach/          Pull Coach domain and analysis system
```

The Pull Coach architecture should maintain clear boundaries:

```text
external data
    ↓
provider ingestion
    ↓
normalized domain models
    ↓
deterministic analysis
    ↓
evidence-backed findings
    ↓
progression comparison
    ↓
coaching synthesis
    ↓
Discord / web / addon presentation
```

Keep those boundaries intact.

In particular:

- Discord objects should not leak into analysis code.
- Warcraft Logs HTTP/GraphQL response shapes should not leak into analyzer-facing code.
- SQLAlchemy persistence models should not become the domain contract.
- LLM output must never become the source of truth for game events.
- Presentation code must consume structured results rather than recompute raid analysis.

---

# Deterministic facts before generated interpretation

Pull Coach uses a strict separation between measurement and interpretation.

Code determines facts such as:

- who was hit;
- by which ability;
- when;
- how much damage occurred;
- whether a mechanic matched a known mechanic definition;
- deaths;
- interrupts;
- dispels;
- role assignments;
- pull progression;
- known causal relationships supported by the event timeline.

An LLM may later summarize or contextualize these facts.

An LLM must not invent them.

Every meaningful coaching finding should remain traceable to deterministic evidence.

When implementing analysis features, prefer structured outputs such as:

```text
Finding
  id
  category
  severity
  mechanic
  actors
  roles
  evidence[]
  related_findings[]
```

over unstructured prose.

---

# Test-driven development

Feature work in this repository should follow test-driven development wherever practical.

The expected development loop is:

```text
1. Understand existing behavior.
2. Add or identify a failing test representing the desired change.
3. Confirm the test fails for the expected reason.
4. Implement the smallest change that makes it pass.
5. Run the focused tests.
6. Run the broader relevant suite.
7. Refactor only while tests remain green.
```

Do not write the full implementation and then add tests afterward merely to confirm it.

For bug fixes:

> Reproduce the bug with a failing regression test before fixing it whenever feasible.

For new functionality:

> Establish executable acceptance behavior before or alongside implementation.

---

# The test suite is a ratchet

Tests are intended to ratchet functionality forward.

Once valid behavior is covered by a test, later work should preserve it unless the product requirement explicitly changes.

Do not:

- delete tests because a new implementation breaks them;
- weaken assertions simply to make a test pass;
- replace meaningful behavioral tests with mocks that no longer exercise the behavior;
- update snapshots blindly;
- silently re-baseline historical raid results.

If behavior intentionally changes:

1. identify the product/technical reason;
2. update the relevant test deliberately;
3. document the changed expectation;
4. ensure unrelated historical behavior remains stable.

---

# Historical raid-night regression testing

Existing Warcraft Logs are a first-class test corpus.

The system is expected to support replaying historical progression nights as though they were happening live.

A historical raid should conceptually execute:

```text
pull 1
  → analyze
  → coach

pull 2
  → analyze using knowledge from pulls 1..2
  → coach

pull 3
  → analyze using knowledge from pulls 1..3
  → coach
```

Future information must never leak backward.

This invariant is important:

> Results through pull N must be identical whether the replay stops at pull N or continues through later pulls.

When modifying:

- event normalization;
- mechanic classification;
- analysis;
- progression logic;
- coaching inputs;
- persistence;

run the relevant historical regression fixtures when they exist.

Treat changed historical results as something to investigate, not automatically update.

---

# Fixtures

Tests should prefer deterministic fixtures over live services.

Normal tests must not require:

- Warcraft Logs credentials;
- Discord credentials;
- a network connection;
- an LLM provider;
- a running production database;
- external services.

Live integration tests may exist separately, but they should be explicit and opt-in.

Historical fixtures should be versioned.

Unsupported fixture versions should fail clearly rather than being silently reinterpreted.

---

# Test layering

Prefer tests at the lowest useful level.

## Unit tests

Use for:

- domain contracts;
- event normalization;
- mechanic matching;
- failure classification;
- progression calculations;
- evidence construction.

These should be fast and deterministic.

## Integration tests

Use for boundaries between components, such as:

```text
WCL fixture
  → normalized events
  → analyzer
  → findings
```

or:

```text
pull findings
  → progression comparison
  → coaching input
```

## End-to-end tests

Reserve for important user-visible flows such as:

```text
historical raid-night fixture
  → Pull Coach pipeline
  → Discord payload
```

Do not rely primarily on E2E tests when a unit or integration test can establish the behavior more precisely.

---

# Testing commands

Use the repository's documented dependency manager and test runner.

Use uv + pytest as the canonical project environment:

```bash
uv sync
uv run pytest
```

For focused development:

```bash
uv run pytest tests/path/to/test_file.py
```

or:

```bash
uv run pytest tests/path/to/test_file.py::test_name
```

Before completing a change, run:

1. the focused tests for the changed behavior;
2. the relevant subsystem tests;
3. the full available test suite when practical.

Report the exact commands and results.

If the repository's tooling changes, follow the checked-in configuration rather than this example.

---

# Do not hide broken pre-existing behavior

If unrelated tests are already failing:

1. verify the failure exists independently of your change;
2. document it;
3. do not silently alter unrelated code to make the suite green unless the ticket covers it.

If your change introduces a new failure, fix it before completion.

---

# Scope discipline

Stay inside the ticket.

Avoid opportunistic refactors unless they are necessary for the requested work.

Examples of work that should usually be separate tickets:

- replacing the Discord framework;
- rewriting the database layer;
- broad dependency upgrades;
- changing Python versions;
- reorganizing the entire application package;
- rewriting old casino/guild features;
- adding a web UI while working on Pull Coach internals.

Small local refactors that make the requested implementation clearer are fine when fully covered by tests.

---

# Compatibility

This repository contains older working guild functionality.

Preserve it.

Before modifying shared code, inspect its consumers.

Avoid breaking:

- existing Discord commands;
- player/character data handling;
- raid scheduling;
- Warcraft Logs functionality;
- existing database schemas;

unless the assigned ticket explicitly requires the change.

When replacing an old interface, prefer an incremental migration path rather than a flag-day rewrite.

---

# Error handling

Fail clearly at boundaries.

Prefer explicit domain errors for conditions such as:

- invalid fixture schema;
- unsupported fixture version;
- inaccessible Warcraft Logs report;
- invalid report code;
- missing encounter metadata;
- unrecognized mechanic definitions;
- malformed normalized events.

Do not swallow exceptions broadly.

Avoid:

```python
try:
    ...
except:
    ...
```

unless there is an exceptional, documented reason.

---

# Observability

Important pipeline operations should eventually make it possible to identify:

- report;
- fight/pull;
- analyzer version;
- fixture/replay run;
- failure stage.

Logs should help debug failures without dumping credentials or sensitive configuration.

Never log:

- Discord tokens;
- OAuth secrets;
- API credentials;
- database passwords.

---

# Dependency policy

Do not add dependencies casually.

Before adding one, determine whether the Python standard library or an existing dependency can solve the problem cleanly.

If adding a dependency:

1. add it through the repository's package manager;
2. explain why it is necessary;
3. pin/version it according to project conventions;
4. update the lockfile;
5. verify clean installation.

Avoid introducing a large framework to solve a small problem.

---

# Jujutsu workflow

This repository uses **Jujutsu (`jj`) as the primary version-control interface**.

Prefer `jj` commands over direct Git mutation commands.

Git may be used for inspection or interoperability when necessary, but development history should be managed through JJ.

---

# Beginning work

Inspect the workspace first:

```bash
jj status
jj log -r '@ | @- | master@origin'
```

If the task should begin from current upstream `master`, ensure the working commit is based on the correct revision before editing.

Do not destroy or overwrite unrelated working-copy changes.

If unexpected local modifications exist, understand them before proceeding.

---

# Working commits

Keep the working commit focused on one Linear ticket.

Set a useful description early rather than leaving an anonymous commit throughout development:

```bash
jj describe -m "DAL-43: define Pull Coach domain contracts and fixture harness"
```

Descriptions should follow:

```text
<TICKET>: <imperative summary>
```

Examples:

```text
DAL-43: define Pull Coach domain contracts and fixture harness
DAL-44: add complete Warcraft Logs pull ingestion
DAL-47: implement evidence-backed pull analysis
```

The description should describe the resulting change, not the activity performed.

Prefer:

```text
DAL-47: classify evidence-backed pull failures
```

over:

```text
DAL-47: work on analyzer
```

---

# Inspecting changes

Use JJ throughout implementation:

```bash
jj status
jj diff
jj diff --stat
jj log
```

Before completion, inspect the complete ticket diff rather than relying on memory.

Useful revision inspection may include:

```bash
jj show @
```

and an appropriate comparison against the ticket's base revision.

Check specifically for:

- accidental unrelated files;
- generated artifacts;
- secrets;
- debug code;
- temporary fixtures;
- overly broad refactors.

---

# Evolving commit descriptions

The JJ commit description should evolve with the implementation.

After significant discoveries, update it if the original description is no longer accurate:

```bash
jj describe -m "DAL-43: establish Pull Coach contracts and replay fixtures"
```

Do not leave stale descriptions.

---

# Multiple commits

Default to a single coherent JJ change for a normal Linear ticket unless splitting the work materially improves reviewability.

If multiple commits are appropriate, each should represent a coherent step and have a meaningful description.

Avoid artificial commit fragmentation such as:

```text
add file
fix tests
fix typo
actually fix tests
```

History should explain the implementation, not narrate debugging.

---

# Rebasing

Use JJ-native rebasing when needed:

```bash
jj rebase ...
```

Do not switch to `git rebase` simply out of habit.

After rebasing:

```bash
jj status
jj log
```

and rerun relevant tests.

---

# Bookmarks and pushing

Use JJ bookmarks intentionally.

Before pushing, confirm:

```bash
jj status
jj log
```

Set/update the appropriate bookmark according to the repository's collaboration workflow.

Prefer:

```bash
jj bookmark ...
jj git push ...
```

over mutating branches through Git directly.

Do not force-push or rewrite shared history unless explicitly required and understood.

---

# Ticket completion checklist

Before declaring a ticket complete:

## Correctness

- Acceptance criteria are satisfied.
- New behavior is covered by tests.
- Relevant existing tests still pass.
- Historical replay tests pass when applicable.
- Error paths are tested where useful.

## Scope

- Diff is limited to the ticket.
- No unrelated cleanup slipped in.
- No secrets or local configuration are committed.

## Architecture

- Layer boundaries remain intact.
- Provider-specific data does not leak into domain logic.
- Analysis remains deterministic.
- Generated coaching remains downstream from evidence.

## JJ

Run:

```bash
jj status
jj diff --stat
jj diff
jj log
```

Confirm the JJ description accurately summarizes the final change.

---

# Final agent report

At the end of every ticket, provide a concise implementation report containing:

## What changed

Summarize the implemented behavior.

## Tests

List the exact commands run and results.

Example:

```text
uv run pytest tests/pull_coach -q
42 passed

uv run pytest -q
87 passed
```

If some tests could not be run, say exactly why.

## Files / architecture

Call out important new or changed modules and architectural decisions.

## Compatibility

State whether existing behavior was preserved and identify any deliberate behavior changes.

## Deferred work

Explicitly identify related work intentionally left for later tickets.

Do not hide unfinished work behind vague wording.

---

# Pull request preparation

Before handing work back for review, produce a PR-ready summary based on the **actual final diff and tests**, not the original plan.

Inspect:

```bash
jj diff --stat
jj diff
jj log
```

Then provide:

```text
PR title:
DAL-43: Define Pull Coach domain contracts and fixture harness

Summary:
- ...
- ...
- ...

Testing:
- `...`
- `...`

Notes:
- ...

Deferred:
- ...
```

The summary should answer:

1. What behavior changed?
2. Why was it implemented this way?
3. What protects it from regression?
4. What was intentionally not included?

Do not claim tests passed unless they were actually run.

Do not claim compatibility unless it was checked.

---

# Agent behavior

When encountering ambiguity:

- inspect the repository;
- inspect tests;
- inspect the Linear ticket;
- make the narrowest reasonable implementation consistent with them.

Do not stop for minor implementation choices that can be safely resolved from existing patterns.

Do stop and surface ambiguity when different interpretations would create materially different product behavior, destructive migrations, or compatibility risks.

Prefer working software and executable tests over speculative documentation.

Leave the repository better protected than you found it.
