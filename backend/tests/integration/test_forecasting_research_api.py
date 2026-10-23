import math


def _observations(n: int = 120) -> list[dict]:
    obs = []
    for i in range(n):
        close = 1.0 + 0.001 * i + math.sin(i / 5) * 0.01
        obs.append(
            {
                "timestamp": f"2024-01-{1 + (i % 28):02d}T00:00:00+00:00"
                if False
                else __import__("datetime").datetime(
                    2024, 1, 1, tzinfo=__import__("datetime").timezone.utc
                )
                + __import__("datetime").timedelta(days=i),
                "open": close,
                "high": close + 0.005,
                "low": close - 0.005,
                "close": close,
                "volume": 1000,
            }
        )
    # normalize timestamp to isoformat
    out = []
    for o in obs:
        o["timestamp"] = o["timestamp"].isoformat()
        out.append(o)
    return out


def _problem(target_type: str = "future_return") -> dict:
    return {
        "problem_id": "demo",
        "version": "1.0.0",
        "instrument_scope": ["EURUSD"],
        "input_timeframe": "D1",
        "price_basis": "close",
        "feature_availability_policy": "point_in_time",
        "prediction_reference": "observation_close",
        "prediction_horizon": 1,
        "target_type": target_type,
        "target_units": "fraction",
        "eligibility_rules": [],
        "label_generation_method": "exact_future_observation",
        "missing_observation_policy": "drop_row",
        "required_historical_coverage": 20,
        "evaluation_protocol": "chronological_holdout",
        "known_limitations": [],
        "neutral_threshold": 0.001 if target_type == "direction" else None,
        "volatility_window": 5 if target_type == "realized_volatility" else None,
        "max_features": 64,
    }


def test_list_model_families(client):
    r = client.get("/api/v1/forecasting/models")
    assert r.status_code == 200
    data = r.json()["data"]
    assert len(data["families"]) >= 4


def test_experiment_validation(client):
    body = {
        "observations": _observations(50),
        "problem": _problem(),
        "lookback": 20,
        "n_folds": 3,
        "min_train_samples": 30,
        "model_families": ["ridge_regression"],
        "random_seed": 1,
    }
    r = client.post("/api/v1/forecasting/experiment/validate", json=body)
    assert r.status_code == 200
    assert r.json()["data"]["valid"] is True


def test_experiment_run_and_retrieval(client):
    body = {
        "observations": _observations(120),
        "problem": _problem(),
        "lookback": 20,
        "n_folds": 3,
        "min_train_samples": 30,
        "purge": True,
        "embargo_periods": 1,
        "model_families": ["ridge_regression"],
        "random_seed": 1,
    }
    r = client.post("/api/v1/forecasting/experiment/run", json=body)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["status"] in {"completed", "completed_with_warnings"}
    eid = data["experiment_id"]
    r2 = client.get(f"/api/v1/forecasting/experiment/{eid}")
    assert r2.status_code == 200
    r3 = client.get(f"/api/v1/forecasting/experiment/{eid}/comparison")
    assert r3.status_code == 200
    r4 = client.get(f"/api/v1/forecasting/experiment/{eid}/limitations")
    assert r4.status_code == 200
    r5 = client.get(f"/api/v1/forecasting/experiment/{eid}/folds")
    assert r5.status_code == 200


def test_invalid_experiment_rejected(client):
    body = {
        "observations": _observations(30),
        "problem": _problem(),
        "lookback": 20,
        "n_folds": 3,
        "min_train_samples": 30,
        "model_families": ["not_a_model"],
        "random_seed": 1,
    }
    r = client.post("/api/v1/forecasting/experiment/run", json=body)
    assert r.status_code in {400, 422, 500}
