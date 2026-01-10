# Contributing

## Prereqs

- Python 3.10+
- uv
- Postgres (local or remote) if you plan to run the bot end-to-end

## Setup

```bash
uv sync --dev
cp .env.example .env
```

This repo includes `uv.lock`; update it with `uv lock` when changing dependencies.

## Dev sanity checks

- Compile + smoke import (no network calls):

```bash
uv run python -m app.scripts.sanity
```

## Formatting

```bash
uv run black .
```

## Linting

```bash
uv run ruff check .
```

## Running the bot

```bash
uv run python main.py
```
