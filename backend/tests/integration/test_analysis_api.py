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


def test_capabilities_endpoint(client) -> None:
    response = client.get("/api/v1/analysis/capabilities")
    assert response.status_code == 200
