# Synapticity Discord Bot

Guild tooling for Presynaptic, including the deterministic Pull Coach V0.

## Install and run

Install Python and [uv](https://docs.astral.sh/uv/), then:

```bash
uv sync
cp .env.example .env   # fill in only credentials needed for your workflow
uv run python main.py
```

The legacy bot uses `DISCORD_BOT_TOKEN` and the `SQLALCHEMY_DATABASE_*` values
for database-backed features. Pull Coach's offline demo does not need Discord,
database, Warcraft Logs, or model-provider credentials.

## Pull Coach V0

The production pipeline keeps provider data and presentation separate:

```text
Warcraft Logs → normalization → encounter mechanic registry → deterministic
analysis/evidence → progression → coaching → Discord presentation
```

The `/pullcoach` Discord command accepts a Warcraft Logs report URL or code and
an optional fight selector (`latest` by default, or a fight ID), then presents
the resulting raid coaching. Live use requires `DISCORD_BOT_TOKEN`, WCL
credentials, and `PULL_COACH_MECHANICS_FILE` to
point to a verified DAL-45 mechanic-definition JSON file for that encounter.
The current WCL actor ingestion does not establish authoritative active-pull
roles. Role-specific guidance is emitted only when authoritative `Role` data
reaches analysis; Pull Coach does not infer player role from class/spec or
mechanic expectation.

Coaching uses deterministic fallback when no provider is configured; a provider
is optional and its failure falls back to factual, evidence-grounded coaching.
No model API key is required for V0.

### Offline reference demo

Run the checked-in three-pull synthetic/reference replay end to end:

```bash
uv run python -m app.pull_coach.demo replay \
  tests/replay/pull-coach-demo.json \
  --mechanics app/pull_coach/mechanics/definitions/reference_analysis.json
```

It produces analysis, progression, coaching, and Discord-payload stages without
posting to Discord. Use `--format json` for canonical structured stage results,
`--format human` for raid-lead-oriented presentation, `--through-pull N` for a
causal prefix, and `--speed max|step|original`. `--output PATH` writes output to
a file. Mechanic definitions are always explicit; reference definitions must
not be reused against real encounters. A missing encounter definition fails
clearly instead of guessing from combat events.

### Capture and replay an authorized WCL night

To fetch report metadata/event pages, configure `WCL_CLIENT_ID` and
`WCL_CLIENT_SECRET`, then write snapshots/manifests in a private local location
(for example `/tmp`):

```bash
uv run python -m app.pull_coach.demo snapshot \
  'https://classic.warcraftlogs.com/reports/REPORT_CODE' \
  --fight 12 --fight 13 --fight 14 \
  --output /tmp/presynaptic-night.json \
  --manifest /tmp/presynaptic-night.manifest.json
```

Only explicitly selected completed fights are captured. Snapshot output contains
private report/player data; inspect and sanitize identities and provenance
before any check-in, and do not commit actual guild snapshots without explicit
approval. Credentials are read from environment/config and are never included
in snapshot or manifest output.

For authorized historical fixture preparation, use the offline inspection and
sanitization commands. Inspection reports snapshot facts only; it does not assign
avoidability or failure meaning. A human must verify mechanics before authoring
definitions. Sanitization writes new files and does not modify source artifacts:

```bash
uv run python -m app.pull_coach.demo inspect /tmp/presynaptic-night.manifest.json --format human
uv run python -m app.pull_coach.demo inspect /tmp/presynaptic-night.manifest.json --format json --output /tmp/inspection.json
uv run python -m app.pull_coach.demo sanitize /tmp/presynaptic-night.manifest.json \
  --output-snapshot /tmp/authorized-fixture.json \
  --output-manifest /tmp/authorized-fixture.manifest.json
uv run python -m app.pull_coach.demo inspect /tmp/authorized-fixture.manifest.json
```

Workflow: authorized WCL capture → inspect snapshot → human verifies mechanic
semantics → author mechanic definitions → sanitize historical snapshot → inspect
sanitized artifact → offline regression replay/baseline. Treat raw capture and
sanitized fixture as private until a human has checked every identity-bearing
field; sanitized output is explicitly marked as authorized WCL-derived, not
synthetic. A sanitized fixture still requires explicit approval before check-in.

Replay from the saved snapshot (no WCL credentials, network, or Discord token):

```bash
uv run python -m app.pull_coach.demo replay \
  /tmp/presynaptic-night.manifest.json \
  --mechanics /path/to/verified-encounter-mechanics.json \
  --speed max --format human
```

DAL-52's `ReplayRunner` processes pulls sequentially and each pull sees only its
causal history. Results through pull N must match whether replay ends at N or
continues through later pulls. The generic replay harness remains available as
`uv run python -m app.pull_coach.replay MANIFEST`; the demo command composes the
full production pipeline.

Configuration variables are listed in [`.env.example`](.env.example). Replay
semantics and historical corpus/privacy notes are in
[`tests/replay/README.md`](tests/replay/README.md).
