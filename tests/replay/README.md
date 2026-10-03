# Replay corpus and importing a historical report

`example-night.json` uses `tests/fixtures/warcraft_logs/replay_snapshot.json`, a
three-fight synthetic/reference WCL-shaped fixture. It is not captured from a
live Warcraft Logs report and does not establish real historical-corpus
acceptance.

Replay `sequence_number` is global to the manifest; DAL-44's `pull_number`
remains local to its encounter. Stages run causally in manifest order: each stage
sees completed outputs from earlier stages for the current pull and completed
results from prior pulls only. Original-speed replay uses the gap from the
previous pull's end to the current pull's start (falling back to its start when
an end timestamp is unavailable). Prefix replay avoids ingesting or analyzing
future fights, while DAL-44 may still validate the containing snapshot file's
schema when it is loaded.

The authorized historical multi-pull report acceptance item remains outstanding;
the checked-in corpus is intentionally synthetic/reference data.

To import a report you are authorized to use, configure `WCL_CLIENT_ID` and
`WCL_CLIENT_SECRET` in the normal local environment, then use DAL-44's snapshot
API for each selected fight and merge the event pages (the report metadata is
shared):

```python
from app.web_requests.warcraft_logs import WCLClient, WCLSnapshot

client = WCLClient()
report_code = "AUTHORIZED_REPORT_CODE"
fight_ids = [12, 13, 14]
parts = [client.snapshot(report_code, fight_id) for fight_id in fight_ids]
snapshot = WCLSnapshot(parts[0].report, {
    fight_id: pages
    for part in parts
    for fight_id, pages in part.event_pages.items()
})
snapshot.save("tests/fixtures/warcraft_logs/imported-night.json")
```

Inspect and sanitize player identities and report provenance before checking in
an imported snapshot. Create a replay manifest pointing to that snapshot with
the report code and chronologically ordered fight IDs. Never commit credentials
or private report data without approval.
