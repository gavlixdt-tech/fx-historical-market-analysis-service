# Integration verification

## Local test boundaries

Tests using `backend/tests/contract/fixtures/` or mocked HTTP transports are
contract/software tests only. Fixtures are synthetic and are not evidence of
provider entitlement, real market history, cross-service authentication, or
production operation.

The backend tests verify provider selection, response identity, coverage and
pagination handling, error sanitization, replay provenance and availability
assumptions, point-in-time request validation, and research-summary
limitations. Frontend tests verify typed backend access and UI states; they
do not call upstream services directly.

## Cross-service evidence

| Path | Local/source verification | Live integration |
|---|---|---|
| Service 1 → Service 2 history | Typed schema and labelled fixture checks | BLOCKED / not run with a verified provider and production identity |
| Service 2 → Service 60 artifact write/read | No Service 2 adapter | BLOCKED |
| Service 2 → Service 61 feature contract | No adapter; point-in-time mismatch documented | BLOCKED |
| Service 63 → Service 2 replay | Route and current source schemas cross-checked | BLOCKED / no authenticated deployed call |
| Service 2 → Service 21/49/50 | No compatible adapter | BLOCKED / NOT_IMPLEMENTED |
| Service 2 → Service 62 | No publisher | BLOCKED |
| Service 64/65/66 | Local controls only; no approved central grants/integration | BLOCKED |

## Commands

Run backend commands from `backend/` so `pyproject.toml` enables pytest's
async auto mode:

```powershell
python -m pytest -q
python -m ruff check .
python -m ruff format --check .
python -m mypy app
```

Run frontend checks from `frontend/`:

```powershell
npm test
npm run build
```

Exact results from the current verification are recorded in
[`../acceptance/service2-integration-acceptance-report.md`](../acceptance/service2-integration-acceptance-report.md).
