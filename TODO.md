# TODO / Roadmap (Hypothetical)

This is a forward-looking task list based on the current code layout and the direction implied by `app/casino/`, `app/web_requests/warcraft_logs/`, and the existing SQLAlchemy betting models.

## 0) Project hygiene (reduce friction)

- [x] Manage dependencies via `uv` (no Poetry); use `uv sync --dev` and `uv run`.
- [x] Pick one Discord library (`py-cord` vs `disco-rd.py`) and remove the other to avoid import/runtime conflicts.
- [x] Add a minimal “dev sanity” script/command (e.g., `python -m compileall`, smoke import of `app.discord_bot.bot`).
- [x] Add formatting/linting (Ruff + Black) and a short `CONTRIBUTING.md` with the standard commands.

## 1) Database bootstrap + migrations (make it repeatable)

- [ ] Create a real “initial schema” Alembic revision that creates all tables in `app/db/models/`.
- [ ] Add non-null/defaults for key economy fields (`players.piter_death_tokens`, `tokens_spent`, `tokens_received`).
- [ ] Add indexes that match query patterns (`players.discord_id`, `usage.timestamp`, etc.).
- [ ] Add a `scripts/` entrypoint to:
  - create tables (dev-only) and/or run migrations
  - seed players (name + discord_id) and initial PDT balances
- [ ] Add a bot command for onboarding, e.g. `!register` (admin-only) to map Discord IDs to `players`.

## 2) Casino: “tables”, “books”, and bet lifecycle (core direction)

### 2.1 Table orchestration

- [ ] Fix/verify polling + cleanup logic:
  - `app/casino/casino.py` table expiry removal
  - `app/casino/table.py` “valid fight” detection and edge cases
- [ ] Add robust error handling around WCL calls (rate limits, auth refresh, transient failures).
- [ ] Add observability:
  - structured logs (report id, fight id, book id)
  - optionally a `!casino status` command

### 2.2 Bet placement + persistence

- [ ] Define a single “bet API” on `Table`:
  - `place_bet(book_type, player_discord_id, selection, amount)`
  - validate funds, lock funds (escrow), store in DB
- [ ] Connect Discord views/modals to the bet API:
  - `app/discord_bot/views/wipe_prediction.py`
  - `app/discord_bot/views/deadpool.py`
- [ ] Implement “cancel bet” behavior (deadline-based, partial refunds, etc.).

### 2.3 Book implementations

- [ ] Implement `WipePrediction` book (`app/casino/books/wipe_prediction.py`)
  - outcome definition (kill vs wipe)
  - payout rules (e.g., pari-mutuel pool, house edge)
  - resolve on each valid fight
- [ ] Implement `Deadpool` book (`app/casino/books/deadpool.py`)
  - map WCL actor deaths to “who died”
  - resolve on each valid fight based on the first death event
- [ ] Wire outcomes to existing models:
  - `bet_events`, `bet_outcomes`, `bet`

### 2.4 Economy integration

- [ ] Decide how PDT interacts with bets:
  - hard lock funds at bet time
  - payout on resolve; refund on table expiry
- [ ] Add admin controls: `!casino pause`, `!casino close`, `!casino refund`.

## 3) Raid tooling + data ingestion (clean up the “That’s My BIS” path)

- [ ] Move “That’s My BIS export → loot-data” logic into a supported flow:
  - update scripts in `data/` to not depend on Flask-era `app` imports
  - optionally store imported data in Postgres instead of JSON
- [ ] Add a bot command to refresh loot/prio data (admin-only) and cache it.
- [ ] Add input validation + clearer UX for `!raid addAlt`, `!raid shards`, `!raid noNext`.

## 4) Testing (protect the casino + economy)

- [ ] Add unit tests for:
  - “valid fight” detection logic
  - schedule bitfield encode/decode (`Schedule.days2bin` / `bin2days`)
  - payout math for each book (deterministic fixtures)
- [ ] Add a small integration test harness that fakes WCL responses and simulates a table resolving a fight.

## 5) Deployment (make it easy to run)

- [ ] Add `docker-compose.yml` for Postgres + bot.
- [ ] Add a `systemd` unit example (or a one-command runner) for long-lived hosting.
- [ ] Document required environment variables + secrets handling.
