# Pull Coach mechanic discovery trust boundary

Automatic encounter discovery records observations, not mechanic meaning. A versioned
`EncounterDiscovery` artifact contains encounter and ability identifiers/names,
observed event types, aggregate actor-type counts, occurrence counts by fight,
damage totals when present, timestamp bounds, death-window associations as counts,
and a SHA-256 source fingerprint plus fight identifiers. Raw report references belong
only in private runtime/snapshot metadata, never in the persisted artifact. Actor counts
use the constrained `player`, `npc`, `pet`, `object`, and `unknown` vocabulary, and
event types use the normalized Pull Coach event enum. It excludes player names and raw event
payloads. Keep the normalized source snapshot/report available for reproducing those
aggregates; the artifact itself is a compact reviewable result, not a replacement for
the source evidence.

The lifecycle is `UNKNOWN -> DISCOVERED -> DRAFTED -> VERIFIED -> SUPPORTED`.
Discovery and draft generation may be automatic. Only verification/promotion into
the production mechanic registry requires explicit human approval. Only separately verified
`MechanicDefinition` values in the existing registry may supply failure category,
avoidability, severity, role responsibility, target-priority meaning, or exposure
and opportunity semantics to production analysis. Candidate artifacts cannot be
loaded as mechanic definitions, and automatic verification is not permitted.
