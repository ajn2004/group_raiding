# Replay corpus and importing a historical report

`example-night.json` uses `tests/fixtures/warcraft_logs/replay_snapshot.json`, a
three-fight synthetic/reference WCL-shaped fixture. It is not captured from a
live Warcraft Logs report and does not establish real historical-corpus
acceptance.

Replay `sequence_number` is global to the manifest; DAL-44's `pull_number`
remains local to its encounter. Stages run causally in manifest order: each
stage sees completed outputs from earlier stages for the current pull and
completed results from prior pulls only. Prefix replay does not ingest or
analyze future fights. Replay of a saved snapshot is offline and requires no
WCL credentials.

The authorized historical multi-pull report acceptance item remains
outstanding; the checked-in corpus is intentionally synthetic/reference data.

## Capture an authorized report

Configure `WCL_CLIENT_ID` and `WCL_CLIENT_SECRET` locally. This command uses
DAL-44's `WCLClient.snapshot()` for each selected completed fight, combines the
pages, and creates a replay manifest:

```bash
uv run python -m app.pull_coach.demo snapshot \
  'https://classic.warcraftlogs.com/reports/AUTHORIZED_REPORT_CODE' \
  --fight 12 --fight 13 --fight 14 \
  --output /tmp/authorized-night.json \
  --manifest /tmp/authorized-night.manifest.json
```

Replay the snapshot with a verified mechanic file explicitly selected:

```bash
uv run python -m app.pull_coach.demo replay \
  /tmp/authorized-night.manifest.json --mechanics /path/to/verified-mechanics.json
```

Snapshot/manifest data may identify players, reports, and guilds. Prefer `/tmp/`,
`.local/`, or another gitignored location. Review and sanitize identities and
report provenance before any fixture check-in. Never commit actual report data
without explicit approval or include credentials in output. Reference mechanics
are synthetic and must not be used against a real encounter. Do not infer
mechanics from unconfigured event names.
