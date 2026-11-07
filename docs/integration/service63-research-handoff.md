# Service 63 historical research handoff

## Routes and schema review

Service 2 exposes:

- `POST /api/v1/historical-replay/run`
- `POST /api/v1/historical-replay/run-from-market-data`

The current Service 63 `historical_replay_client.py` targets these same route
paths and validates the response envelope, replay/dataset identity, target
type, synthetic flag, provider provenance status, response size, and
research-only invariants. Its market-data request includes the provider ID,
instrument, timeframe, price basis, interval, dataset ID, problem, and replay
parameters. Service 2 now requires the canonical slash-delimited instrument
identifier for this provider-sourced route, matching Service 1's registry.

The source request/response models were cross-checked for field and
provenance compatibility. This is a source-level contract check only; it is
not an authenticated Service 63 → Service 2 end-to-end run.

## Trust and decision boundary

Provider replay results report `provider_asserted_unverified`; derived
availability is an explicit assumption, and source records are not
independently signed. The Service 63 adapter treats the result as research
only. Retrospective replay does not establish a live forecast, independently
verified evidence, a decision, profitability, or trade readiness.

The existing Service 63 controls must not be weakened. Service 2 contains no
broker or order-execution integration.

## Blockers

- Production Service 64 workload identity/grant is not available. Service 2
  fails closed for real-provider use in production.
- The Service 1 production authentication contract is not verified.
- No shared deployment configuration or real cross-service runtime test was
  available in this verification.
- Provider entitlement, historical first-available timestamps, and source
  signatures remain unverified.

**Classification:** IMPLEMENTED_NOT_VERIFIED. The route and adapter exist;
authenticated runtime integration remains blocked.
