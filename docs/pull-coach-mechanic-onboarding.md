# Pull Coach mechanic onboarding

Pull Coach can inspect an unsupported encounter from the report browser and save
an observation-only discovery artifact. The operator lifecycle is:

```text
unsupported encounter
  -> automatic discovery of completed pulls
  -> optional deterministic draft/proposal
  -> review
  -> explicit human promote or reject
  -> verified mechanics registry
  -> next browser invocation shows the encounter as supported
```

The transition does not require a bot restart: the encounter catalog factory
loads the directory-backed verified registry on each invocation. The new rule
is available to the normal historical Pull Coach workflow as soon as its
verified file has been promoted.

## Review and promote

The CLI currently accepts `--root` before the subcommand. Review a discovered
candidate using its encounter ID and candidate ID:

```bash
python -m app.pull_coach.mechanics.cli \
  --root /path/to/mechanics \
  review <encounter-id> <candidate-id>
```

Promotion requires a JSON input containing explicit reviewer decisions. For
example:

```bash
python -m app.pull_coach.mechanics.cli \
  --root /path/to/mechanics \
  promote <encounter-id> <candidate-id> \
  --input /path/to/verified-input.json
```

To reject a candidate, providing a reviewer is mandatory; a reason is optional:

```bash
python -m app.pull_coach.mechanics.cli \
  --root /path/to/mechanics \
  reject <encounter-id> <candidate-id> \
  --reviewer <reviewer-name> \
  --reason "Not a mechanic"
```

Promotion will not overwrite an existing encounter file by default. Updating
existing verified mechanics requires the explicit `--replace` option and a new
definition version where the mechanic itself is replaced.

## Trust boundary

- **Discovery is facts:** observed ability identities, event types, aggregate
  counts, timestamps, and report-fight provenance. It does not assign failure
  categories, avoidability, severity, responsibility, or exposure meaning.
- **Draft/proposal is a review aid:** scaffolds are deterministic and semantic
  proposals, when available, remain unverified. A provider outage does not
  prevent factual draft generation.
- **Promotion is an explicit human semantic decision:** the reviewer supplies
  the canonical mechanic identity, selector interpretation, failure category,
  severity, avoidability, and any applicable role or metadata semantics.
- **Only `verified/*.json` is analyzer input.** Discovery and draft artifacts
  remain separate lanes and cannot make an encounter supported or affect
  analysis.

Discovery and draft files contain no player names, actor IDs, raw report code,
or raw event payload. Their source provenance uses a report fingerprint and
fight IDs so the observations can be traced without persisting the report
reference.
