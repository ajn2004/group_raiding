# Synapticity Discord Bot

Guild tooling for Presynaptic, including the deterministic Pull Coach V0.

This repository is a polyglot monorepo. `apps/backend` is the Python
server-side application and `apps/web` is the React/TypeScript presentation
application. They communicate through the HTTP/OpenAPI boundary.

```text
apps/backend/ Python bot, persistence, integrations, Pull Coach, migrations, tests
apps/web/     TypeScript web workspace
docs/         Architecture and project documentation
```

Python domain and business logic remain authoritative. Browser/UI code must not
import Python persistence models or duplicate domain rules. Web/backend
contracts cross the HTTP API/OpenAPI boundary.

## Local frontend development

Run all commands in this section from the repository root. The web app and
Python API are separate processes; keep each running in its own terminal.

### Prerequisites and first-time setup

Install Node.js 22, pnpm 10.12.4 (the version pinned in `package.json`),
Python 3.10 or newer within the backend's supported `>=3.10,<4` range, and
[uv](https://docs.astral.sh/uv/).

Install both workspaces' dependencies:

```bash
pnpm install --frozen-lockfile
pnpm backend:sync
```

The current web shell and API health endpoint do not require a database,
a running Discord bot, or Discord/Warcraft Logs/model-provider credentials.
No `.env` file is needed for this basic startup flow. Discord sign-in is
separate work in DAL-81.

### Start the app

In terminal 1, start the Python API:

```bash
pnpm backend:api
```

In terminal 2, start the Next.js frontend:

```bash
pnpm web:dev
```

Open [http://localhost:3000](http://localhost:3000). The page should show
"The web app is running" and the API health result. Next.js updates the page
as you edit files under `apps/web`; the API also runs with automatic reload.
Use Ctrl+C in each terminal to stop the services.

The browser calls same-origin `/api/*` URLs. Next.js forwards those requests to
`http://127.0.0.1:8000` by default. To check the connection:

```bash
# Python API directly
curl http://127.0.0.1:8000/api/healthz

# Through the frontend's API proxy
curl http://localhost:3000/api/healthz
```

Both should return `{"status":"ok","api_version":"v1"}`. Interactive API docs
are available at [http://127.0.0.1:8000/api/docs](http://127.0.0.1:8000/api/docs).

### Configuration and troubleshooting

- If the page loads but its API check fails, confirm `pnpm backend:api` is
  still running and test the direct health URL above.
- If port 3000 is occupied, use the URL printed by Next.js or start on a chosen
  port with `pnpm web:dev --port 3001`.
- If the API needs a different port, start it with
  `pnpm backend:api --port 8001`, then start the frontend with
  `API_PROXY_TARGET=http://127.0.0.1:8001 pnpm web:dev`.
- `API_PROXY_TARGET` is a server-side Next.js setting. For a persistent local
  override, add it to `apps/web/.env.local` and restart the frontend. Browser
  requests continue to use the same-origin `/api` path.
- Running `pnpm web:dev` starts only the frontend. It does not start the API
  or Discord bot.

### Frontend checks and API types

Run the frontend checks from the repository root:

```bash
pnpm web:lint
pnpm web:typecheck
pnpm web:build
```

Install the Playwright browser once before running the test suite:

```bash
pnpm --filter @group-raiding/web exec playwright install chromium
pnpm web:test
```

The web test command checks generated API types, runs Vitest, and runs the
Playwright smoke test. Playwright starts the local API and frontend itself
(or reuses running servers outside CI) and requires no external services.

When the backend API contract changes, regenerate the checked-in schema and
TypeScript definitions:

```bash
pnpm backend:openapi
pnpm web:generate-api
```

The generated files live in `apps/web/src/lib/api/generated/`. Consume these
types rather than duplicating backend response definitions.

## Discord bot development

The bot is a separate backend entrypoint. From the repository root:

```bash
cd apps/backend
uv sync
cp .env.example .env   # first-time setup; fill in credentials for your workflow
uv run python main.py
```

The legacy bot uses `DISCORD_BOT_TOKEN` and the `SQLALCHEMY_DATABASE_*` values
for database-backed features. Pull Coach's offline demo does not need Discord,
database, Warcraft Logs, or model-provider credentials.

Run backend tests with `uv run pytest` in `apps/backend`. Python imports retain
the package name `app`; Alembic and backend-relative data/mechanics paths are
rooted there as well. Run the Python commands below from `apps/backend`.

## Pull Coach V0

The production pipeline keeps provider data and presentation separate:

```text
Warcraft Logs → normalization → encounter mechanic registry → deterministic
analysis/evidence → progression → coaching → Discord presentation
```

The `/pullcoach` Discord command accepts a Warcraft Logs report URL or code and
an optional fight selector (`latest` by default, or a fight ID), then presents
the resulting raid coaching. Live use requires `DISCORD_BOT_TOKEN`, WCL
credentials, and a configured mechanics registry. The preferred setting is a
writable directory root:

```dotenv
PULL_COACH_MECHANICS_ROOT=/path/to/pull-coach-mechanics
```

Do not switch a live bot to the checked-in `mechanics/pull-coach` root under
`apps/backend` until it contains the intended verified encounter definitions.
A configured directory
root takes precedence over `PULL_COACH_MECHANICS_FILE`, so the currently empty
checked-in registry would otherwise replace the legacy definitions with an
empty registry.

The root has the following layout:

```text
pull-coach-mechanics/
  verified/   # only these JSON files enter PullAnalyzer
  discovered/ # factual discovery artifacts; never production analyzer input
  drafts/     # unverified proposals; never production analyzer input
  reviews/    # review lifecycle records
```

The directory must be writable by the bot when automatic unsupported-encounter
discovery is enabled. `PULL_COACH_MECHANICS_FILE` remains available only as a
backwards-compatible single-file fallback when the root setting is unset or
blank. Do not point the live bot at `app/pull_coach/mechanics/definitions/`;
those files are test/demo references, not a production registry.
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

Backend configuration variables are listed in [`apps/backend/.env.example`](apps/backend/.env.example). Replay
semantics and historical corpus/privacy notes are in
[`apps/backend/tests/replay/README.md`](apps/backend/tests/replay/README.md).
