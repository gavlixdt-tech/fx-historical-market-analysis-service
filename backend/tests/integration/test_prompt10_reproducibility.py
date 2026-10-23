import math


def _observations(n: int = 120) -> list[dict]:
    obs = []
    dt_start = __import__("datetime").datetime(
        2024, 1, 1, tzinfo=__import__("datetime").timezone.utc
    )
    for i in range(n):
        close = 1.0 + 0.001 * i + math.sin(i / 5) * 0.01
        obs.append(
            {
                "timestamp": (dt_start + __import__("datetime").timedelta(days=i)).isoformat(),
                "open": close,
                "high": close + 0.005,
                "low": close - 0.005,
                "close": close,
                "volume": 1000,
            }
        )
    return obs


def _problem() -> dict:
    return {
        "problem_id": "demo",
        "version": "1.0.0",
        "instrument_scope": ["EURUSD"],
        "input_timeframe": "D1",
        "price_basis": "close",
        "feature_availability_policy": "point_in_time",
        "prediction_reference": "observation_close",
        "prediction_horizon": 1,
        "target_type": "future_return",
        "target_units": "fraction",
        "eligibility_rules": [],
        "label_generation_method": "exact_future_observation",
        "missing_observation_policy": "drop_row",
        "required_historical_coverage": 20,
        "evaluation_protocol": "chronological_holdout",
        "known_limitations": [],
        "max_features": 64,
    }


def test_experiment_reproducible_fingerprint(client):
    body = {
        "observations": _observations(120),
        "problem": _problem(),
        "lookback": 20,
        "n_folds": 3,
        "min_train_samples": 30,
        "purge": True,
        "embargo_periods": 1,
        "model_families": ["ridge_regression"],
        "random_seed": 7,
    }
    r1 = client.post("/api/v1/forecasting/experiment/run", json=body)
    r2 = client.post("/api/v1/forecasting/experiment/run", json=body)
    assert r1.status_code == 200
    assert r2.status_code == 200
    d1 = r1.json()["data"]
    d2 = r2.json()["data"]
    assert d1["dataset_fingerprint"] == d2["dataset_fingerprint"]
    assert d1["research_readiness_status"] == d2["research_readiness_status"]
    # aggregate metric reproducibility within tolerance
    m1 = d1["models"][0]["aggregate_primary_metric"]
    m2 = d2["models"][0]["aggregate_primary_metric"]
    assert abs(m1 - m2) < 1e-9


def test_fingerprint_changes_with_data(client):
    obs = _observations(120)
    body = {
        "observations": obs,
        "problem": _problem(),
        "lookback": 20,
        "n_folds": 3,
        "min_train_samples": 30,
        "model_families": ["ridge_regression"],
        "random_seed": 1,
    }
    r1 = client.post("/api/v1/forecasting/experiment/run", json=body)
    obs2 = [dict(o) for o in obs]
    obs2[10]["close"] = obs2[10]["close"] + 0.5
    obs2[10]["high"] = obs2[10]["close"] + 0.005
    obs2[10]["low"] = obs2[10]["close"] - 0.005
    obs2[10]["open"] = obs2[10]["close"]
    body2 = dict(body, observations=obs2)
    r2 = client.post("/api/v1/forecasting/experiment/run", json=body2)
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["data"]["dataset_fingerprint"] != r2.json()["data"]["dataset_fingerprint"]


def test_research_readiness_blocked_unconfigured(client):
    body = {
        "instrument": "EURUSD",
        "timeframe": "D1",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-02-01T00:00:00Z",
        "problem": _problem(),
    }
    r = client.post("/api/v1/research/readiness", json=body)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["ready"] is False
    assert data["readiness_status"] == "BLOCKED"
