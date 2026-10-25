import math


def _observations(n: int = 120) -> list[dict]:
    obs = []
    for i in range(n):
        close = 1.0 + 0.001 * i + math.sin(i / 5) * 0.01
        obs.append(
            {
                "timestamp": (
                    __import__("datetime").datetime(
                        2024, 1, 1, tzinfo=__import__("datetime").timezone.utc
                    )
                    + __import__("datetime").timedelta(days=i)
                ).isoformat(),
                "open": close,
                "high": close + 0.005,
                "low": close - 0.005,
                "close": close,
                "volume": 1000,
            }
        )
    return obs


def _problem(target_type: str = "future_return", eligibility_rules=None, max_features=64):
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
        "eligibility_rules": [] if eligibility_rules is None else eligibility_rules,
        "label_generation_method": "exact_future_observation",
        "missing_observation_policy": "drop_row",
        "required_historical_coverage": 20,
        "evaluation_protocol": "chronological_holdout",
        "known_limitations": [],
        "neutral_threshold": 0.001 if target_type == "direction" else None,
        "volatility_window": 5 if target_type == "realized_volatility" else None,
        "max_features": max_features,
    }


def test_eligibility_valid_rule_changes_label_count(client):
    body = {
        "observations": _observations(40),
        "problem": _problem(eligibility_rules=["0", "exclude_index:5"]),
    }
    r = client.post("/api/v1/forecasting/labels", json=body)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["valid_count"] < data["total_count"]
    labels = {lab["reference_index"]: lab["status"] for lab in data["labels"]}
    assert labels[0] == "excluded"
    assert labels[5] == "excluded"


def test_eligibility_invalid_rule_rejected(client):
    r = client.post(
        "/api/v1/forecasting/problem/validate",
        json=_problem(eligibility_rules=["not_a_rule"]),
    )
    assert r.status_code == 200
    assert r.json()["data"]["valid"] is False
    assert any("invalid eligibility rule" in e for e in r.json()["data"]["errors"])


def test_eligibility_out_of_range_rejected_at_label_generation(client):
    body = {
        "observations": _observations(40),
        "problem": _problem(eligibility_rules=["1000"]),
    }
    r = client.post("/api/v1/forecasting/labels", json=body)
    assert r.status_code in {400, 422, 500}


def test_max_features_manifest_effective_count(client):
    for mf in (64, 1, 3, 11):
        body = {
            "observations": _observations(80),
            "problem": _problem(max_features=mf),
            "lookback": 20,
            "split": {"train_ratio": 0.6, "validation_ratio": 0.2, "test_ratio": 0.2},
        }
        r = client.post("/api/v1/forecasting/dataset", json=body)
        assert r.status_code == 200
        tc = r.json()["data"]["manifest"]["transformation_config"]
        expected = min(mf, 11)
        assert tc["max_features"] == mf
        assert tc["effective_feature_count"] == expected
        assert len(tc["effective_feature_names"]) == expected


def test_max_features_invalid_rejected(client):
    r = client.post(
        "/api/v1/forecasting/problem/validate",
        json=_problem(max_features=0),
    )
    assert r.status_code == 422
    r2 = client.post(
        "/api/v1/forecasting/problem/validate",
        json=_problem(max_features=257),
    )
    assert r2.status_code == 422


def test_dataset_manifest_records_effective_features(client):
    body = {
        "observations": _observations(80),
        "problem": _problem(max_features=3),
        "lookback": 20,
        "split": {"train_ratio": 0.6, "validation_ratio": 0.2, "test_ratio": 0.2},
    }
    r = client.post("/api/v1/forecasting/dataset", json=body)
    assert r.status_code == 200
    manifest = r.json()["data"]["manifest"]
    tc = manifest["transformation_config"]
    assert tc["max_features"] == 3
    assert tc["effective_feature_count"] == 3
    assert len(tc["effective_feature_names"]) == 3


def test_experiment_run_with_eligibility_and_max_features(client):
    body = {
        "observations": _observations(120),
        "problem": _problem(eligibility_rules=["0", "exclude_index:5"], max_features=3),
        "lookback": 20,
        "n_folds": 3,
        "min_train_samples": 30,
        "model_families": ["ridge_regression"],
        "random_seed": 1,
        "calibration": False,
    }
    r = client.post("/api/v1/forecasting/experiment/run", json=body)
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["effective_config"]["effective_feature_count"] == 3
    assert data["effective_config"]["max_features_requested"] == 3
    body = {
        "observations": _observations(80),
        "problem": _problem(),
        "lookback": 20,
        "n_folds": 3,
        "min_train_samples": 30,
        "model_families": ["ridge_regression"],
        "random_seed": 1,
        "calibration": True,
    }
    rv = client.post("/api/v1/forecasting/experiment/validate", json=body)
    assert rv.status_code == 200
    assert rv.json()["data"]["valid"] is False
    assert any("calibration is not implemented" in e for e in rv.json()["data"]["errors"])
    rr = client.post("/api/v1/forecasting/experiment/run", json=body)
    assert rr.status_code in {400, 422, 500}


def test_calibration_rejected_deterministically(client):
    body = {
        "observations": _observations(80),
        "problem": _problem(),
        "lookback": 20,
        "n_folds": 3,
        "min_train_samples": 30,
        "model_families": ["ridge_regression"],
        "random_seed": 1,
        "calibration": True,
    }
    rv = client.post("/api/v1/forecasting/experiment/validate", json=body)
    assert rv.status_code == 200
    assert rv.json()["data"]["valid"] is False
    assert any("calibration is not implemented" in e for e in rv.json()["data"]["errors"])
    rr = client.post("/api/v1/forecasting/experiment/run", json=body)
    assert rr.status_code in {400, 422, 500}
