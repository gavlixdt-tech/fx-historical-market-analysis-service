# Recovery runbook

## Current recovery status

**BLOCKED / NOT ESTABLISHED.** Service 2 has no canonical durable dataset or
research-artifact store and no Service 66 integration. Experiments retained
in process memory are lost at restart. The optional local JSON artifact
directory is not a backup, replication, or tested restore mechanism.
No RPO/RTO, backup frequency, retention, or recovery claim is approved.

## Safe restart

1. Confirm the deployment remains in `research-simulation` mode and that
   trading/execution is not enabled.
2. Restart only the Service 2 process/container using the approved deployment
   controller; do not delete, overwrite, or synthesize artifacts.
3. Check `GET /api/v1/health/live`, `/api/v1/health/ready`, and `/api/v1/status`.
4. Treat an absent in-memory experiment after restart as unavailable, not
   recovered. Re-run only from the same verified immutable dataset if that
   source and lineage are available.
5. Escalate missing durable artifacts to the platform owner. Do not claim a
   restore from a local JSON file without integrity and lineage validation.

## Recovery acceptance prerequisite

Before any recovery-ready claim, approve ownership, encryption, cadence,
retention, RPO/RTO, immutable artifact identity, backup integrity checks,
restore authorization, and a witnessed restore test covering manifests,
fingerprints, source references, results, limitations, and code identity.
