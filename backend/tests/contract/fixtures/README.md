# Contract Test Fixtures

**Every JSON file in this directory is a hand-written synthetic fixture.**

They are NOT real market data. They were constructed by hand from the
`fx-market-data-service` source schemas to exercise response validation and
error handling without contacting a live upstream service.

No fixture may be presented as, or derived from, observed market data. All
price-like values are obviously synthetic round numbers and the instrument
identifiers are reserved test symbols.

The `contract_status` recorded in the service status response is `verified`
for the *shape* of these payloads because each one was derived directly from
the upstream source schemas. The upstream **authentication** contract remains
`PROPOSED - NOT YET VERIFIED`; see
`contracts/upstream-market-data-contract.md`.
