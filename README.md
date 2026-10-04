# Synapticity Discord Bot

Guild tooling for Presynaptic, including the deterministic Pull Coach V0.

This repository is a polyglot monorepo. `apps/backend` is the Python
server-side application and `apps/web` is the React/TypeScript presentation
application. They will meet at the future HTTP/OpenAPI boundary.

```text
apps/backend/ Python bot, persistence, integrations, Pull Coach, migrations, tests
apps/web/     TypeScript web workspace
docs/         Architecture and project documentation
```

Python domain and business logic remain authoritative. Browser/UI code must not
import Python persistence models or duplicate domain rules. Web/backend
contracts cross the HTTP API/OpenAPI boundary.

## Install and run

Install Python, [uv](https://docs.astral.sh/uv/), Node.js, and pnpm. Run Python
commands from `apps/backend` (or use the root `pnpm backend:*` convenience
scripts):

```bash
cd apps/backend
uv sync
cp .env.example .env   # fill in only credentials needed for your workflow
uv run python main.py
```

Run tests with `uv run pytest` in `apps/backend`. Python imports retain the
package name `app`; Alembic and backend-relative data/mechanics paths are rooted
there as well.

### Create and migrate a new PostgreSQL database

Create an empty PostgreSQL database, configure its connection in
`apps/backend/.env` (`SQLALCHEMY_DATABASE_USER`, `SQLALCHEMY_DATABASE_PASSWORD`,
`SQLALCHEMY_DATABASE_HOST`, `SQLALCHEMY_DATABASE_PORT`, and
`SQLALCHEMY_DATABASE_DB`), then run:

```bash
cd apps/backend
uv run alembic upgrade head
```

The Alembic history bootstraps the legacy application schema and all current
feature tables; no schema pre-seeding or `create_all()` step is needed.

The fresh-PostgreSQL migration acceptance test is opt-in. Set
`TEST_POSTGRES_ADMIN_URL` to a PostgreSQL URL for a user permitted to create and
drop databases, then run `uv run pytest tests/test_fresh_postgres_bootstrap.py`.

### PostgreSQL integration tests (DAL-91)

The regular backend suite remains fast and isolated on SQLite where appropriate;
it runs without PostgreSQL configuration. The opt-in PostgreSQL lane validates
the real Alembic chain, PostgreSQL constraints/upserts/timestamps and shared
caller-owned repository sessions. It uses a unique schema per run in an
explicitly configured **test-only** PostgreSQL database. The fixture removes
only that schema after disposing test connections. Never point it at a
production database; use the dedicated disposable service below.

Start a dedicated local service with dummy test credentials (Docker required):

```bash
docker run -d --name group-raiding-dal91-postgres \
  -e POSTGRES_USER=dal91_test -e POSTGRES_PASSWORD=dal91_test_only \
  -e POSTGRES_DB=dal91_test -p 55432:5432 postgres:16
until docker exec group-raiding-dal91-postgres pg_isready -U dal91_test -d dal91_test; do sleep 1; done
```

From the repository root, configure the test infrastructure URL and run the
explicit lane. This setting is read by pytest only; application configuration
does not use it or fall back to `SQLALCHEMY_DATABASE_*`:

```bash
TEST_DATABASE_URL='postgresql+psycopg2://dal91_test:dal91_test_only@127.0.0.1:55432/dal91_test' pnpm backend:test-postgres
docker rm -f group-raiding-dal91-postgres
```

Equivalent direct command from `apps/backend`:

```bash
TEST_DATABASE_URL='postgresql+psycopg2://dal91_test:dal91_test_only@127.0.0.1:55432/dal91_test' uv run pytest --postgres -m postgres -q
```

The explicit lane fails with an actionable error if `TEST_DATABASE_URL` is
missing, the URL is not PostgreSQL, or the service cannot be reached. It never
falls back to SQLite. Ordinary `pnpm backend:test` / `uv run pytest -q` clearly
deselects the PostgreSQL-marked tests and does not connect to a database.
CI can run the same explicit command with an ephemeral PostgreSQL service and
the same test-only environment variable; no CI workflow is currently present.
Install JavaScript workspace dependencies from the repository root with:

```bash
pnpm install
```

Start the web client with `pnpm web:dev` (or `pnpm --filter @group-raiding/web dev`).
The root `pnpm lint`, `pnpm typecheck`, `pnpm test`, and `pnpm build` commands
(also available as `pnpm web:lint`, `pnpm web:typecheck`, `pnpm web:test`, and
`pnpm web:build`) run the web quality checks. Web and backend API are independent services;
starting the browser app does not implicitly start the bot or API.

### HTTP API development

The FastAPI service runs independently of the Discord bot. Start it from the
repository root; once the Next.js app is available, start the web app in another
terminal:

```bash
pnpm backend:api
pnpm web:dev
```

The Next.js `/api/*` rewrite defaults to `http://127.0.0.1:8000`. Set
`API_PROXY_TARGET` when the Python API listens elsewhere; this is a server-side
Next.js environment variable and the browser always calls its same-origin `/api`
path. The checked-in schema and generated TypeScript definitions are refreshed
with `pnpm backend:openapi` followed by `pnpm web:generate-api`.

The health endpoint is `GET /api/healthz`; interactive docs are at
`/api/docs`. Export the reproducible OpenAPI contract from the repository root with:

```bash
pnpm backend:openapi
```

The generated document belongs in
`apps/web/src/lib/api/generated/openapi.json`. Derived TypeScript API types
should live alongside it in `apps/web/src/lib/api/generated/` and be generated
from this contract rather than duplicating backend response definitions.

### Discord web sign-in (DAL-81)

The Python API owns Discord OAuth and durable web sessions. The browser only
uses the same-origin Next.js `/api` proxy; do not call the Python port directly
from the browser. Required backend settings are in `apps/backend/.env.example`:

- `DISCORD_OAUTH_CLIENT_ID` and `DISCORD_OAUTH_CLIENT_SECRET`: OAuth application
  credentials from Discord Developer Portal → OAuth2 → General.
- `PUBLIC_APP_URL`: the browser-visible application origin.
- `DISCORD_OAUTH_CALLBACK_URL`: exactly
  `${PUBLIC_APP_URL}/api/auth/discord/callback`.
- `DISCORD_GUILD_ID`: community whose current-user membership may be read. It
  does not grant application permissions.
- `DISCORD_TOKEN_ENCRYPTION_KEY`: stable Fernet key used to encrypt Discord OAuth
  credentials at rest for membership refresh. Generate with
  `uv run python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`.
  Keep it secret and stable; rotating it requires users to sign in again.
- `SQLALCHEMY_DATABASE_USER`, `SQLALCHEMY_DATABASE_PASSWORD`,
  `SQLALCHEMY_DATABASE_HOST`, `SQLALCHEMY_DATABASE_PORT`, and
  `SQLALCHEMY_DATABASE_DB`: PostgreSQL connection settings shared with the
  primary backend PostgreSQL database. Auth identities, sessions, and one-use
  OAuth state are stored there; the old development SQLite sessions are
  disposable and users must sign in again after upgrading.

Runtime durable relational state belongs in the primary PostgreSQL database and
is schema-managed through Alembic. SQLite is permitted only for isolated tests
unless an explicit architecture ticket says otherwise. New persistent features
must use the shared database boundary and caller-owned sessions, register models
with the shared `Base`, add migrations to the single Alembic chain, never create
private durable tables at service startup, and avoid feature-specific database
configuration. Apply `uv run alembic upgrade head` before using database-backed
authentication or other persistent features. `/api/healthz`, API imports, and
OpenAPI generation do not require PostgreSQL.

Register `http://localhost:3000/api/auth/discord/callback` as the redirect URI
in the Discord Developer Portal for local use. For production, register the
exact HTTPS callback, for example
`https://group.example/api/auth/discord/callback`, and set `PUBLIC_APP_URL` and
`DISCORD_OAUTH_CALLBACK_URL` to that matching origin. Keep the Next.js proxy in
front of the API so the session cookie is first-party. Local HTTP cookies omit
`Secure`; HTTPS deployments set it. Cookies are HTTP-only and SameSite=Lax.

No session signing/encryption secret is required: the API issues cryptographically
random opaque cookies, stores only a SHA-256 token hash, and invalidates sessions
server-side on logout. Discord OAuth tokens are encrypted server-side and never
returned to clients or logged. This web OAuth client is independent of
`DISCORD_BOT_TOKEN`.

### Discord RBAC mappings (DAL-82)

Discord role snowflakes map to reusable capabilities, never rank names. The
supported capability keys are `app.view`, `players.manage`,
`coaching.configure`, `usage.view`, and `admin.manage_rbac`. Membership and role
IDs are initially resolved during the OAuth callback.
`GET /api/auth/session` is read-only and does not contact Discord;
`POST /api/auth/session/refresh` is the explicit membership/token refresh
boundary (send the session CSRF token in `X-CSRF-Token`). Capability dependencies
authorize from the currently persisted membership and role state. Discord
failures deny privileged capabilities; refresh returns 503 and clears cached
roles. An unmapped role grants nothing.

After applying migrations, configure mappings from a deployment-managed JSON
file (role IDs are strings):

```json
{
  "community": "primary",
  "guild_id": "YOUR_DISCORD_COMMUNITY_ID",
  "mappings": [
    {"role_id": "YOUR_DISCORD_ROLE_ID", "capabilities": ["app.view", "usage.view"]}
  ]
}
```

Run `uv run python scripts/configure_rbac.py /path/to/rbac-mappings.json` from
`apps/backend`. The command replaces all mappings for that guild atomically;
store the file outside source control if it contains production IDs. Changing
this configuration takes effect on the next API authorization check without a
frontend change. `GET /api/rbac/mappings` requires `admin.manage_rbac`.

There is no checked-in PostgreSQL compose/service configuration. For a local
development-only server, start a disposable PostgreSQL container (or connect to
your existing development PostgreSQL instance):

```bash
docker run -d --name group-raiding-postgres \
  -e POSTGRES_USER=group_raiding -e POSTGRES_PASSWORD=local-dev-only \
  -e POSTGRES_DB=group_raiding -p 5432:5432 postgres:16
until docker exec group-raiding-postgres pg_isready -U group_raiding -d group_raiding; do sleep 1; done
```

Set these **PostgreSQL** values (not Discord OAuth credentials) in
`apps/backend/.env`:

```dotenv
SQLALCHEMY_DATABASE_USER=group_raiding
SQLALCHEMY_DATABASE_PASSWORD=local-dev-only
SQLALCHEMY_DATABASE_HOST=127.0.0.1
SQLALCHEMY_DATABASE_PORT=5432
SQLALCHEMY_DATABASE_DB=group_raiding
```

Keep the database container running across API restarts. Apply migrations:

```bash
cd apps/backend
uv run alembic upgrade head
```

Configure `DISCORD_OAUTH_CLIENT_ID`, `DISCORD_OAUTH_CLIENT_SECRET`, and
`DISCORD_GUILD_ID` separately as Discord OAuth credentials. Register the
localhost callback URI, then start API and frontend in separate repository-root
terminals:

```bash
pnpm backend:api
```

```bash
pnpm web:dev
```

Open `http://localhost:3000`, select **Sign in with Discord**, authorize, and
verify the return to the app. Reload to verify read-only session restoration,
use `POST /api/auth/session/refresh` to verify membership refresh, restart the
backend and reload again to verify PostgreSQL durability, then sign out and
verify the signed-out view (the previous session cookie must remain invalid).
Automated auth tests use a fake Discord transport
and need no credentials. API contracts are `GET /api/auth/session`,
`GET /api/auth/discord/login?return_to=/safe/path`,
`GET /api/auth/discord/callback`, and `POST /api/auth/logout` with the session
response's `csrf_token` in `X-CSRF-Token`. Callback redirects only to a same-site
absolute path; external return destinations are rejected.

The Playwright smoke test starts the local FastAPI app and Next.js app, then
checks the real browser-to-Python `/api/healthz` request through the same-origin
rewrite. It needs no external services. Install its browser once with
`pnpm --filter @group-raiding/web exec playwright install chromium`.

The bot uses `DISCORD_BOT_TOKEN`; all database-backed features use the same
`SQLALCHEMY_DATABASE_*` primary PostgreSQL settings. Pull Coach's offline demo does not need Discord,
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
