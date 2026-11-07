# Service 61 feature-contract boundary

Service 2 retains its existing point-in-time feature construction and
preprocessing. No Service 61 API is called and no shared feature-version
contract has been approved.

The feature services must agree on feature identifiers, exact formulas,
lookback, price basis, timeframe, missing-value handling, normalization,
feature version, availability cutoff, training-only fit behavior, and
source lineage before sharing an output. In particular, a globally fitted
transform from Service 61 cannot be used in a replay if its fit includes
future observations relative to each prediction origin.

The current audited Service 61 path does not establish those same replay
point-in-time semantics and lineage. Service 2 therefore keeps its own
chronological implementation, which fits replay preprocessing at each
training origin. This is a safe boundary, not a claim that the two feature
sets are equivalent.

**Status:** PARTIALLY_IMPLEMENTED; cross-service integration is blocked pending
an approved, versioned point-in-time feature contract and a contract test.
