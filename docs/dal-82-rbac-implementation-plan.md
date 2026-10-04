# DAL-82: Discord guild roles to application capabilities

## Outcome

Authorize web requests using a user's current Discord guild membership and role IDs, resolved against reusable application capabilities. Discord identity, guild membership, authorization roles, and legacy `Player` linkage remain independent concepts. Application code and UI consume stable capability strings; neither depends on guild rank labels.

## Current implementation

- Discord OAuth and opaque server-side sessions are implemented in `apps/backend/app/api/auth.py`.
- Login requests `identify guilds.members.read`; the OAuth callback resolves initial guild membership and role IDs.
- `GET /api/auth/session` returns persisted session and authorization state without contacting Discord. `POST /api/auth/session/refresh` is the explicit membership/token refresh boundary.
- The existing `WebIdentity`, `WebSession`, and `OAuthState` models are registered through `app.db.models`; Alembic owns durable schema changes.
- The web client restores that session in `apps/web/src/app/page.tsx`; generated API declarations come from backend OpenAPI.

## Proposed design

### Durable guild and mapping configuration

Add shared SQLAlchemy models, registered with `Base`, for configured Discord communities and role-to-capability grants. A community stores its Discord guild ID and a stable internal key/display-neutral identifier; each mapping is keyed by `(community_id, discord_role_id, capability)`. Store role IDs as strings to preserve Discord snowflakes exactly. Permit multiple communities in schema and resolver, while configuration selects the active installation community (initially `DISCORD_GUILD_ID`, preserving current deployment configuration).

Use an Alembic migration to add the tables and constraints/indexes. Do not seed guild IDs, role IDs, or rank names in source. Bootstrap mappings through documented deployment-managed configuration/import/administrative seed mechanism, with mapping writes restricted to `admin.manage_rbac`; deployment supplies the first mapping out-of-band so there is no privilege-escalation bootstrap trap. A missing/unconfigured mapping set grants no privileged capabilities.

Capabilities are stable strings (`app.view`, `players.manage`, `coaching.configure`, `usage.view`, `admin.manage_rbac`). Keep the initial supported capability registry centralized in backend domain/authz code and return capability strings over the API. Mappings are many-to-many: every mapping for every current member role contributes capabilities, and the final set is deduplicated and deterministic.

### Membership refresh and resolver behavior

The Discord membership provider calls the guild-member endpoint with the access token obtained server-side during OAuth and during explicit refresh. Validate response shape and extract only guild membership and role IDs. Keep raw provider response types inside the provider boundary. Add a deterministic policy resolver accepting normalized `(guild_id, is_member, role_ids)` plus stored mapping records and returning a typed authorization context.

OAuth access and refresh tokens are encrypted in the server-side session and never returned to the browser or logged. Explicit refresh uses these credentials; it does not rely on browser-cached roles. On successful membership lookup, re-resolve current roles and capabilities. A successful non-member response clears membership/capabilities immediately. A Discord/API failure fails closed for privileged capabilities and clears cached roles; explicit refresh returns unavailable rather than retaining old grants. Do not interpret transport failure as “not a member.”

Behavior matrix:

| State | Authorization result |
| --- | --- |
| Anonymous / invalid session | Existing unauthenticated session contract; protected endpoint returns 401 |
| Authenticated, not a member | `is_member=false`, empty role/capability sets |
| Member, no mapped role | `is_member=true`, empty capability set |
| Member with mapped role(s) | Union of mapped capabilities |
| Multiple mapped roles | Deterministic set union; no ordering semantics |
| Role removed on successful refresh | Removed capabilities absent immediately |
| Unmapped role | Ignored; grants nothing |
| Discord unavailable/malformed response | No privileged grants; report refresh unavailable distinctly; never preserve old privileges as current |

Resolve membership during OAuth callback and at the explicit authenticated refresh endpoint. `GET /api/auth/session` is read-only and must not fetch Discord. Capability dependencies use currently persisted membership/role state and must not fetch Discord. If initial resolution is unavailable, establish the authenticated session with no privileged capabilities, enabling retry. An explicit refresh returns a clear 503 on provider failure and must not retain previously cached privileges as current.

### API authorization and contracts

Extend typed `AuthSessionResponse` with a stable authorization object containing active community ID/key, membership status, application role/capability list, and refresh status/time as appropriate. Keep identity fields separate and do not add Player IDs. Provide the explicit `POST /api/auth/session/refresh` endpoint behind authentication; document method and response in OpenAPI.

Add reusable dependencies in `app/api/dependencies.py` or a focused `app/api/authorization.py`: authenticated identity/session dependency, `require_capability(capability)` dependency, and typed request authorization context. Missing/invalid session yields 401; authenticated but insufficient capability yields 403. Apply the dependency to privileged routes centrally and ensure route code does not do ad hoc rank checks. Add an initial protected RBAC mapping administration endpoint only if management is part of this ticket's intended bootstrap mechanism; otherwise the deployment mechanism provisions mappings and the policy dependency is ready for future routes. Never authorize via `WebIdentity.discord_user_id` alone or legacy player linkage.

Regenerate `apps/web/src/lib/api/generated/{openapi.json,api.d.ts}` using the checked-in export workflow after response/route changes.

### Frontend consumption

Extend the client session type to use generated OpenAPI contracts where practical. Add a small capability utility/context exposing `can(capability)` and reusable hide/disable helpers; navigation/actions derive from the same backend capability list. Default to false while session is loading, anonymous, stale, or unavailable. UI visibility is presentation only; API dependencies are authoritative.

## Implementation sequence

1. Add deterministic unit tests for normalized policy resolution and the full role/member matrix before implementing the resolver.
2. Add guild/mapping persistence models, model registration, migration, and repository queries; verify mappings can be changed without code edits and support multiple guild rows.
3. Add Discord member provider and OAuth/session refresh flow with provider failures, non-membership, malformed payload, and removed roles covered by tests.
4. Extend session/me response and explicit refresh endpoint; update auth integration tests and OpenAPI artifacts.
5. Add reusable authenticated/capability dependencies and a representative privileged endpoint; test anonymous 401 and missing-capability 403, including changed mapping and revoked role.
6. Add frontend capability helpers and test visibility behavior against typed session capability sets.
7. Document deployment setup, least-privilege bootstrap, and how to rotate/change mappings; run focused API/web tests, relevant suites, migrations/schema checks, and inspect the complete JJ diff.

## Test plan

- Policy unit tests: anonymous inputs at API boundary, non-member, ordinary mapped member, elevated mapped role, multiple roles, unmapped role, empty mapping set, and deterministic output ordering.
- API tests with synthetic guild/role IDs and stubbed Discord responses: session establishment, refresh, provider unavailable, malformed response, role revocation after prior grant, and mapping changes changing results.
- Authorization integration tests: 401 anonymous; 403 authenticated without capability; success with required capability; revoked/unmapped role returns 403. Ensure no player records are required.
- Persistence/migration tests: multiple community configuration, unique mapping constraints, migration upgrade/downgrade where supported, no source-coded guild/role snowflakes.
- Web tests: `can()` and navigation/action visibility for granted/denied/loading contexts. Backend route tests remain the authorization proof.
- Run `(cd apps/backend && uv run pytest tests/api -q)` and full backend suite; run web unit tests and API type-generation check.

## Deployment and operational notes

1. Apply the Alembic migration against the primary PostgreSQL database.
2. Configure the active Discord guild ID using existing deployment configuration, and grant the OAuth app `guilds.members.read` (already requested by the flow).
3. Provision the initial role-ID-to-capability mappings through the documented deployment bootstrap path using Discord snowflake IDs; do not use human rank labels as policy keys.
4. Verify a regular member receives only intended capabilities, then test a role removal and explicit refresh before enabling privileged routes.

## Implemented decisions

- OAuth access and refresh tokens are Fernet-encrypted in the existing server-side session record using `DISCORD_TOKEN_ENCRYPTION_KEY`; Discord tokens are not returned to clients. Expired access tokens use Discord's refresh-token grant.
- Role mappings are changed via the deployment-managed JSON bootstrap script. `GET /api/rbac/mappings` is protected by `admin.manage_rbac`; an interactive mapping editor is not part of this ticket.
- OAuth callback performs initial membership resolution. Session restoration via `GET /api/auth/session` is read-only and never calls Discord. Explicit refresh uses `POST /api/auth/session/refresh`, requires CSRF validation, clears cached roles on provider failure, and returns 503. Capability dependencies use the persisted membership/role state.
- Community configuration is multi-guild in persistence. The configured `DISCORD_GUILD_ID` selects the active community for OAuth; the community row is created from that setting without source-coded guild identifiers.

## Repository-specific verification note

DAL-82 extends the existing `dal91playerchar` migration head; Alembic revision discovery should report one head. Offline SQL generation remains blocked by an older betting migration that imports `app.db.database` and opens a real PostgreSQL connection; the RBAC migration itself does not use that pattern.
