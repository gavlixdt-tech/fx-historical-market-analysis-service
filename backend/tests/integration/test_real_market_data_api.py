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


def test_data_source_unconfigured(client) -> None:
    response = client.get("/api/v1/data-source")
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["configuration"]["base_url_configured"] is False
    assert data["configuration"]["credential_configured"] is False
    assert data["connectivity"]["state"] in {"unconfigured", "unavailable"}


def test_research_readiness_with_observations(client) -> None:
    body = {
        "observations": _observations(120),
        "problem": _problem(),
        "lookback": 20,
        "n_folds": 3,
        "min_train_samples": 30,
        "model_families": ["ridge_regression"],
        "random_seed": 1,
    }
    response = client.post("/api/v1/research/readiness", json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert "ready" in data
    assert isinstance(data["findings"], list)
    assert data["experiment_validation"]["valid"] is True


def test_retrieve_historical_requires_instrument(client) -> None:
    response = client.post("/api/v1/historical-data/retrieve", json={})
    assert response.status_code == 422


def test_retrieve_historical_unconfigured(client) -> None:
    body = {
        "instrument": "EURUSD",
        "timeframe": "D1",
        "start": "2024-01-01T00:00:00Z",
        "end": "2024-02-01T00:00:00Z",
    }
    response = client.post("/api/v1/historical-data/retrieve", json=body)
    assert response.status_code == 400
    assert "not configured" in response.json()["error"]["message"].lower()
