# Development Guide

## 1. Prerequisites

| Tool | Version used | Notes |
| --- | --- | --- |
| Python | 3.11+ (3.12 used in CI) | The local venv here is 3.15. |
| Node.js | 20+ (24 LTS also works) | npm 11+ |
| Docker | Optional | For the Compose stack and container checks. |

## 2. Repository layout

See `docs/architecture.md` section 3 for the annotated tree.

## 3. Backend setup

From the repository root:

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
```

### Run the backend

```bash
cd backend
uvicorn backend.app.main:app --reload --port 8000
```

The service is then available at <http://localhost:8000>.

| Path | Purpose |
| --- | --- |
| `/api/v1/health/live` | Liveness |
| `/api/v1/health/ready` | Readiness |
| `/api/v1/status` | Full status |
| `/api/v1/version` | Version |
| `/docs` | Interactive OpenAPI docs |
| `/metrics` | Prometheus metrics |

### Backend checks

```bash
cd backend
ruff check app tests          # lint
ruff format --check app tests # formatting
mypy app                      # strict type check
pytest tests -q               # tests
```

Run them from the **repository root** with `backend/.venv/Scripts/python.exe -m
pytest backend/tests -q` if your working directory is the root.

## 4. Frontend setup

```bash
cd frontend
npm install
npm run dev      # dev server on http://localhost:5173
```

The dev server proxies nothing by default. Point the dashboard at a running
backend with `VITE_API_BASE_URL`, or use the Compose stack (below) where the
frontend proxies `/api/` to the backend.

### Frontend checks

```bash
cd frontend
npx tsc --noEmit  # type check
npm run test      # vitest
npm run build     # production build
```

## 5. Running the full stack with Docker

```bash
cp .env.example .env
docker compose up --build
```

| Service | URL |
| --- | --- |
| Dashboard | <http://localhost:8080> |
| Backend API | <http://localhost:8000/api/v1> |
| Backend docs | <http://localhost:8000/docs> |

To include the upstream market-data service, set
`UPSTREAM_MARKET_DATA_BASE_URL` in `.env` before starting. Leaving it empty
runs the service with no upstream, which is a supported configuration.

## 6. Configuration

All configuration is environment-driven and validated at startup. See
`.env.example` for the full list and `docs/api.md` for the behavioural
meaning of each value.

The settings that matter most in development:

| Variable | Default | Notes |
| --- | --- | --- |
| `ENVIRONMENT` | `development` | `production` tightens the invariants. |
| `LOG_FORMAT` | `json` | Use `console` locally for readable output. |
| `REQUIRE_AUTH` | `false` | Must be `true` in production. |
| `CORS_ALLOW_ORIGINS` | `http://localhost:5173` | Comma-separated allowlist. |
| `TRUSTED_HOSTS` | `localhost,127.0.0.1,testserver` | Comma-separated. |
| `UPSTREAM_MARKET_DATA_BASE_URL` | *(empty)* | Empty means no upstream. |
| `UPSTREAM_API_KEY` | *(empty)* | Server-side only. |

## 7. Adding a backend endpoint

1. Define the request/response schemas in `backend/app/schemas/`.
2. Add the route to a module in `backend/app/api/v1/routes/` and register it
   in `backend/app/api/v1/router.py`.
3. Put the behaviour in `backend/app/services/`; the route layer should only
   translate HTTP to a service call.
4. Add tests under `backend/tests/integration/`.
5. Regenerate the OpenAPI document: `curl http://localhost:8000/api/v1/openapi.json`.

## 8. Adding a dashboard panel

1. Add or extend a Zod schema in `frontend/src/schemas/api.ts`.
2. Add the endpoint to `frontend/src/services/api/client.ts`.
3. Build the panel in `frontend/src/features/` and compose it in
   `frontend/src/app/App.tsx`.
4. Add a test in `frontend/src/tests/`.

The dashboard is read-only. Do not add mutation controls.

## 9. Contract test fixtures

Fixtures in `backend/tests/contract/fixtures/` are **synthetic**. They are
hand-built to mirror the upstream schemas and must never be presented as
market data. Keep the `_fixture_notice` field when adding a new fixture.

## 10. Before opening a pull request

```bash
# Backend
backend/.venv/Scripts/python.exe -m ruff check backend
backend/.venv/Scripts/python.exe -m ruff format --check backend
backend/.venv/Scripts/python.exe -m mypy backend/app
backend/.venv/Scripts/python.exe -m pytest backend/tests -q

# Frontend
cd frontend && npx tsc --noEmit && npm run test && npm run build
```

All of these run in CI on every push and pull request.

## 10. Real market data workflow (Prompt 8)

The dashboard integrates the verified backend workflow:

1. Open the **Real Market Data Research** panel.
2. Refresh **Data source status** (`GET /api/v1/data-source`). Only a backend-reported `connected` state may be treated as verified.
3. Submit a bounded historical-data request (`POST /api/v1/historical-data/retrieve`).
4. Inspect dataset quality, coverage, provenance and fingerprint.
5. Run **Validate research readiness** (`POST /api/v1/research/readiness`).
6. Run the forecasting experiment only when readiness is `true`.
7. Inspect model-vs-baseline metrics, fold results, warnings and limitations.

The dashboard never calls Service 1 directly. All upstream access remains server-side.

Synthetic demo experiments remain available in **AI Forecast Research & Evaluation** and are explicitly labeled as synthetic.
