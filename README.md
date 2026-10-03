# Synapticity Discord Bot

A bot to assist with discord actions in Presynaptic's discord

# Quickstart Installation
To get started with this codebase you need to have [python](https://www.python.org/downloads/) installed. If you're using WSL2 you can do this easily
```bash
sudo apt-get install python3
```
Download the codebase and install dependencies
```bash
git clone https://github.com/ajn2004/group_raiding
cd group_raiding
poetry install
```
This will download the project to your machine and install the necessary libraries to run the code.

# Discord Bot
The [main.py](main.py) file is entry point for the discord bot. It can be run with a simple command
```bash
python3 main.py
```
This will launch the bot to connect to the discord server and start hosting commands


# Postgres Server
The postgres server can best be understood by studying the [models](app/db/models). This is a basic relational database intended to model the guild environment. Accessing the server can be done through the [.env file](.env.example).
```
SQLALCHEMY_DATABASE_USER='YOUR_USER_NAME'
SQLALCHEMY_DATABASE_PASSWORD='YOUR_PASSWORD'
SQLALCHEMY_DATABASE_HOST='YOUR_DATABASE_ADDR'
SQLALCHEMY_DATABASE_PORT='YOUR_DATABASE_PORT'
SQLALCHEMY_DATABASE_DB='YOUR_DATABASE_NAME'
DISCORD_BOT_TOKEN='YOUR_DISCORD_BOT_API_TOKEN'
```
Update these values with your access information and the app should connect automatically.

Of course this requires you to be running a postgres server, or know how to access a running one.

# Pull Coach foundation

`app/pull_coach` contains provider-independent dataclass contracts for reports,
pulls, actors, normalized events, mechanic observations, evidence-backed
findings, analysis results, and progression deltas. Domain models do not depend
on Discord, SQLAlchemy, HTTP clients, or Warcraft Logs response types.

The intended V0 boundary is:

```text
provider ingestion (future) → normalized events → deterministic analysis
→ evidence-backed findings → progression comparison → coaching/presentation
```

Warcraft Logs ingestion will adapt external data into these contracts;
deterministic analyzers consume the normalized contracts. Persistence,
coaching, and Discord/web/addon clients will be downstream adapters. This
foundation defines no provider integration or analysis behavior.

Versioned JSON examples in `app/pull_coach/fixtures` exercise individual pulls
and ordered raid-night manifests. `load_raid_night_prefix(..., through_pull=N)`
opens only payloads through N, so replaying a historical prefix cannot read
later-pull data. Fixture schema version mismatches fail explicitly. Real
captured historical raid nights and replay tooling are intended for later work.

Run the deterministic, service-free tests with:

```bash
poetry install
poetry run pytest
```
