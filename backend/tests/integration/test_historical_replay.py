from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient


def _observations(n: int = 130) -> list[dict[str, object]]:
    start = datetime(2023, 1, 1, tzinfo=UTC)
    rows: list[dict[str, object]] = []
    for index in range(n):
        close = 1.08 + index * 0.0001 + math.sin(index / 4) * 0.002
        timestamp = start + timedelta(days=index)
        rows.append(
            {
                "timestamp": timestamp.isoformat(),
                "available_at": (timestamp + timedelta(minutes=2)).isoformat(),
                "open": close,
                "high": close + 0.001,
                "low": close - 0.001,
                "close": close,
                "volume": 1000.0,
                "source_record_id": f"test-record-{index}",
            }
        )
    return rows


def _body(target_type: str = "future_return") -> dict[str, object]:
    return {
        "instrument": "EURUSD",
        "timeframe": "D1",
        "price_basis": "close",
        "source_dataset_id": "test-fixture-v1",
        "synthetic": True,
        "observations": _observations(),
        "problem": {
            "problem_id": "historical-replay-test",
            "version": "1.0.0",
            "instrument_scope": ["EURUSD"],
            "input_timeframe": "D1",
            "price_basis": "close",
            "feature_availability_policy": "point_in_time",
            "prediction_reference": "observation_close",
            "prediction_horizon": 1,
            "target_type": target_type,
            "target_units": "fraction" if target_type != "direction" else "class",
            "eligibility_rules": [],
            "label_generation_method": "exact_future_observation",
            "missing_observation_policy": "drop_row",
            "required_historical_coverage": 20,
            "evaluation_protocol": "chronological_holdout",
            "known_limitations": [],
            "neutral_threshold": 0.0005 if target_type == "direction" else None,
            "volatility_window": None,
            "max_features": 64,
        },
        "lookback": 10,
        "min_train_samples": 20,
        "validation_mode": "expanding",
        "embargo_periods": 0,
        "model_families": (
            ["ridge_logistic"] if target_type == "direction" else ["ridge_regression"]
        ),
        "random_seed": 17,
    }


def test_historical_replay_respects_event_availability_and_is_reproducible(
    client: TestClient,
) -> None:
    body = _body()
    response = client.post("/api/v1/historical-replay/run", json=body)
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["status"] in {"completed", "completed_with_warnings"}
    assert result["synthetic"] is True
    assert result["provenance_status"] == "synthetic_fixture"
    assert result["dataset_fingerprint"] == result["reproducibility"]["dataset_fingerprint"]
    assert result["n_predictions"] > 20
    assert result["robustness"]["primary_protocol"] == "chronological_rolling_origin_replay"
    assert result["robustness"]["future_evaluation"]["status"] == "not_established"
    assert result["robustness"]["service_ablation"]["status"] == "not_available"
    assert all(
        row["information_cutoff"] < row["target_available_at"]
        and row["training_outcomes_available_by_cutoff"]
        for row in result["predictions"]
    )
    model = next(item for item in result["models"] if item["model_family"] == "ridge_regression")
    assert model["vs_baseline"]["status"] == "computed"


def test_provider_sourced_replay_fails_closed_when_upstream_is_unconfigured(
    client: TestClient,
) -> None:
    body = _body()
    body.pop("synthetic")
    body.pop("observations")
    body["price_basis"] = "midpoint"
    body["provider_id"] = "real-provider"
    body["start"] = "2023-01-01T00:00:00Z"
    body["end"] = "2023-05-01T00:00:00Z"
    body["limit"] = 1000

    response = client.post(
        "/api/v1/historical-replay/run-from-market-data",
        json=body,
    )

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "DEP_UNAVAILABLE"
    assert response.json()["error"]["details"]["dependency"] == "fx-market-data-service"


def test_future_observation_changes_do_not_change_earlier_replay_forecasts(
    client: TestClient,
) -> None:
    original = _body()
    changed = _body()
    changed_rows = changed["observations"]
    assert isinstance(changed_rows, list)
    altered = changed_rows[100]
    assert isinstance(altered, dict)
    altered["open"] = float(altered["open"]) + 0.15
    altered["high"] = float(altered["high"]) + 0.15
    altered["low"] = float(altered["low"]) + 0.15
    altered["close"] = float(altered["close"]) + 0.15

    original_result = client.post("/api/v1/historical-replay/run", json=original).json()["data"]
    changed_result = client.post("/api/v1/historical-replay/run", json=changed).json()["data"]
    before_altered_observation = [
        row
        for row in original_result["predictions"]
        if row["reference_timestamp"] < original["observations"][100]["timestamp"]
    ]
    changed_predictions = {
        row["reference_timestamp"]: row["forecasts"] for row in changed_result["predictions"]
    }
    assert before_altered_observation
    assert all(
        row["forecasts"] == changed_predictions[row["reference_timestamp"]]
        for row in before_altered_observation
    )


def test_replay_rejects_unavailable_or_out_of_order_records(client: TestClient) -> None:
    body = _body()
    observations = body["observations"]
    assert isinstance(observations, list)
    observations[4]["available_at"] = observations[4]["timestamp"]
    observations[4]["available_at"] = (
        datetime.fromisoformat(str(observations[4]["timestamp"])) - timedelta(minutes=1)
    ).isoformat()
    response = client.post("/api/v1/historical-replay/run", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VAL_INVALID"


def test_classification_replay_reports_out_of_sample_calibration(client: TestClient) -> None:
    response = client.post(
        "/api/v1/historical-replay/run",
        json=_body("direction"),
    )
    assert response.status_code == 200
    result = response.json()["data"]
    model = next(item for item in result["models"] if item["model_family"] == "ridge_logistic")
    calibration = model["out_of_sample_metrics"]["calibration"]
    assert calibration["status"] == "out_of_sample_descriptive_only"
    assert calibration["calibrated_probability_claim"] is False
    baseline = next(item for item in result["models"] if item["model_family"] == "majority_class")
    baseline_calibration = baseline["out_of_sample_metrics"]["calibration"]
    assert baseline_calibration["status"] == "out_of_sample_descriptive_only"
    probabilities = result["predictions"][0]["forecasts"]["majority_class"]["class_probabilities"]
    assert abs(sum(probabilities.values()) - 1.0) < 1e-9


def test_declared_holdout_is_never_used_for_training_or_selection_diagnostics(
    client: TestClient,
) -> None:
    body = _body()
    observations = body["observations"]
    assert isinstance(observations, list)
    holdout_start = observations[85]["timestamp"]
    body["final_holdout_start"] = holdout_start

    response = client.post("/api/v1/historical-replay/run", json=body)
    assert response.status_code == 200
    result = response.json()["data"]
    holdout = [row for row in result["predictions"] if row["reference_timestamp"] >= holdout_start]
    assert len(holdout) > 20
    assert len({row["training_samples"] for row in holdout}) == 1
    assert all(row["training_target_end"] < holdout_start for row in holdout)
    assert all(
        row["training_information_cutoff"] == holdout_start
        and row["training_outcomes_available_by_cutoff"]
        for row in holdout
    )
    assert result["robustness"]["selection_diagnostics_use"] == "pre-holdout predictions only"
    assert all(
        model["declared_holdout"]["n_predictions"] == len(holdout)
        and model["model_selection_metrics"] is not None
        for model in result["models"]
    )


def test_rolling_window_bounds_each_training_set(client: TestClient) -> None:
    body = _body()
    body["validation_mode"] = "rolling"
    body["rolling_window"] = 25

    response = client.post("/api/v1/historical-replay/run", json=body)
    assert response.status_code == 200
    result = response.json()["data"]
    assert result["validation_mode"] == "rolling"
    assert all(row["training_samples"] <= 25 for row in result["predictions"])
