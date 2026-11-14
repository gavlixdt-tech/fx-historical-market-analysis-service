from datetime import datetime, timedelta


def _obs(n: int = 80) -> list[dict]:
    out = []
    price = 1.0
    dt = datetime(2024, 1, 1)
    for i in range(n):
        price *= 1.001
        out.append(
            {
                "timestamp": (dt + timedelta(days=i)).isoformat() + "Z",
                "open": price,
                "high": price * 1.001,
                "low": price * 0.999,
                "close": price,
                "volume": 100,
            }
        )
    return out


def test_regime_endpoint(client) -> None:
    response = client.post("/api/v1/analysis/regimes", json={"observations": _obs()})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["observation_count"] == 80


def test_pattern_endpoint(client) -> None:
    response = client.post(
        "/api/v1/analysis/patterns",
        json={"observations": _obs(), "config": {"pattern_ids": ["directional_persistence"]}},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["patterns"][0]["pattern_id"] == "directional_persistence"


def test_research_summary_endpoint(client) -> None:
    response = client.post(
        "/api/v1/analysis/research-summary",
        json={
            "observations": _obs(120),
            "config": {"pattern": {"pattern_ids": ["directional_persistence"]}},
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] == "completed"
    assert data["observation_count"] == 120
    assert data["confidence"] is None
    assert data["confidence_status"] == "not_calculated"
    assert data["narrative"]
    assert any("trading instruction" in item.lower() for item in data["recommendations"])
    assert data["regime_summary"]["status"] == "completed"



def test_seasonality_endpoint_returns_descriptive_calendar_buckets(client) -> None:
    response = client.post(
        "/api/v1/analysis/seasonality",
        json={
            "observations": _obs(120),
            "timeframe": "D1",
            "timezone": "Africa/Nairobi",
            "bucket_types": ["weekday", "month_of_year"],
            "minimum_bucket_samples": 5,
            "bootstrap_samples": 100,
            "block_size": 3,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] in {"completed", "completed_with_warnings"}
    assert data["timezone"] == "Africa/Nairobi"
    assert data["timeframe"] == "D1"
    assert data["forecast_eligible"] is False
    assert data["algorithm_id"] == "calendar_seasonality_research"
    assert len(data["buckets"]) == 19
    assert data["analysis_fingerprint"]
    assert data["effective_config"]["maximum_gap_multiple"] == 1.5
    assert data["effective_config"]["price_basis"] is None
    assert data["effective_config"]["provider_id"] is None
    assert data["global_summary"]["return_observation_count"] > 0
    assert all("sample_status" in bucket for bucket in data["buckets"])



def test_seasonality_analysis_fingerprint_is_deterministic(client) -> None:
    payload = {
        "observations": _obs(120),
        "timeframe": "D1",
        "timezone": "UTC",
        "bucket_types": ["weekday"],
        "minimum_bucket_samples": 5,
        "bootstrap_samples": 100,
        "block_size": 3,
        "seed": 42,
    }
    first = client.post("/api/v1/analysis/seasonality", json=payload)
    second = client.post("/api/v1/analysis/seasonality", json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    first_data = first.json()["data"]
    second_data = second.json()["data"]
    assert first_data["analysis_id"] != second_data["analysis_id"]
    assert first_data["analysis_fingerprint"] == second_data["analysis_fingerprint"]

    changed_config = {**payload, "timezone": "Africa/Nairobi"}
    third = client.post("/api/v1/analysis/seasonality", json=changed_config)
    assert third.status_code == 200
    assert third.json()["data"]["analysis_fingerprint"] != first_data["analysis_fingerprint"]

def test_seasonality_endpoint_rejects_invalid_timezone(client) -> None:
    response = client.post(
        "/api/v1/analysis/seasonality",
        json={"observations": _obs(80), "timeframe": "D1", "timezone": "Mars/Olympus"},
    )

    assert response.status_code == 422


def test_pattern_endpoint_rejects_unsupported_pattern_and_overlap_policy(client) -> None:
    unsupported_pattern = client.post(
        "/api/v1/analysis/patterns",
        json={
            "observations": _obs(),
            "config": {"pattern_ids": ["unknown_pattern"]},
        },
    )
    unsupported_overlap = client.post(
        "/api/v1/analysis/patterns",
        json={
            "observations": _obs(),
            "config": {"overlap_policy": "silently_allow"},
        },
    )

    assert unsupported_pattern.status_code == 422
    assert unsupported_overlap.status_code == 422

def test_capabilities_endpoint(client) -> None:
    response = client.get("/api/v1/analysis/capabilities")
    assert response.status_code == 200
