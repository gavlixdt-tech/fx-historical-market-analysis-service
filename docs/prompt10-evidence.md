# Prompt 10 Evidence Report — Reproducible Research, Robustness Validation & Predictive-Value Readiness Gate

## 1. Initial Git state
- Branch: `master`
- HEAD: `3165912 feat(prompt9): verified data integration audit, QA fixes, evidence report`
- Working tree: clean at start.

## 2. Files changed
- `backend/app/services/analysis_service.py` — upstream candle ingestion now skips incomplete/invalid OHLC rows instead of coercing missing prices to `0.0`.
- `backend/app/services/forecasting_service.py` — content-based deterministic dataset fingerprints; reproducibility metadata; research-readiness classification; assess_research_readiness returns readiness status.
- `backend/app/schemas/forecasting.py` — optional reproducibility/readiness fields.
- `backend/app/api/v1/routes/forecasting.py` — passes readiness status through.
- `frontend/src/schemas/api.ts` — frontend types aligned with new fields.
- `frontend/src/features/ForecastingReadiness.tsx` — surfaces evidence, readiness, fingerprint, reproducibility metadata.
- `backend/tests/integration/test_prompt10_reproducibility.py` — reproducibility/fingerprint/readiness tests.
- `docs/prompt10-evidence.md` — this report.

## 3. Reproducibility design
- Dataset fingerprints are SHA-256 over canonical JSON (`sort_keys=True`) of instrument, timeframe, price basis, problem, lookback, observation OHLCV values, timestamps, and outcome ends.
- Experiment records include UTC start/completion times, random seed, validation scheme, purge/embargo, folds, per-fold metrics, warnings, limitations, artifact metadata, reproducibility block, and research-readiness decision.
- Randomized models use controlled seeds (`random_seed + fold`).
- Results are stored in-memory only; they do not survive application restarts.

## 4. Data integrity and leakage findings
- Fixed upstream coercion defect in `analysis_service._resolve_observations`.
- Existing point-in-time feature construction and chronological walk-forward folds preserved.
- Synthetic vs real classification remains unverified for user-supplied data and is labelled `user_supplied_unverified`.

## 5. Validation protocol and metrics
- Regression: MAE, RMSE, R², mean error; classification: accuracy, balanced accuracy, confusion matrix, calibration where applicable; volatility: sample std.
- Baseline comparisons retained (zero return, historical mean, majority class, volatility mean).

## 6. Test results
- Backend: 90 passed (pytest), ruff clean, mypy clean.
- Frontend: vitest 20 passed, build successful.

## 7. Real-market-data status
- BLOCKED: upstream `UPSTREAM_MARKET_DATA_BASE_URL` unset; no credentials/container runtime. Synthetic data not treated as real-market evidence.

## 8. Research-readiness gate
- Statuses: BLOCKED, INSUFFICIENT EVIDENCE, NOT DEMONSTRATED, PROMISING, NOT ESTABLISHED, RESEARCH VALIDATION PASSED.
- Conservative criteria: improvement over baseline, finite metrics, >=3 folds, sample size threshold.

## 9. Known limitations
- In-memory experiment storage.
- No independent real-market validation.
- Statistical significance not claimed.

## 10. Unverified assumptions
- Git commit not captured at runtime (reported as unknown).
- Readiness thresholds are heuristic and dataset-specific.