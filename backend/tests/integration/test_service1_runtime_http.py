from __future__ import annotations

import os
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest

from backend.app.clients.base import UpstreamContractStatus, UpstreamState
from backend.app.clients.market_data import MarketDataClient
from backend.app.core.errors import UpstreamError

TEST_API_KEY = "service1-integration-test-key-not-a-secret"


@pytest.fixture(scope="module")
def service1_runtime() -> Iterator[str]:
    service1_root = Path(
        os.environ.get(
            "FX_MARKET_DATA_SERVICE_ROOT",
            str(Path(__file__).resolve().parents[3].parent / "fx-market-data-service"),
        )
    )
    if not (service1_root / "backend" / "app" / "main.py").is_file():
        pytest.skip("Set FX_MARKET_DATA_SERVICE_ROOT to run the real Service 1 HTTP test.")

    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(service1_root),
            "ENVIRONMENT": "testing",
            "REQUIRE_AUTH": "true",
            "API_KEY": TEST_API_KEY,
            "PROVIDER_TEST_ADAPTER_ENABLED": "true",
            "PROVIDER_PEPPERSTONE_ENABLED": "false",
            "PROVIDER_TWELVE_DATA_ENABLED": "false",
            "FEED_ENABLED": "false",
            "FEED_STARTUP_ENABLED": "false",
            "EVENT_BUS_PUBLISH_ENABLED": "false",
            "TRUSTED_HOSTS": "127.0.0.1,localhost",
        }
    )
    command = (
        "import uvicorn; "
        "from backend.app.main import create_app; "
        f"uvicorn.run(create_app(), host='127.0.0.1', port={port}, log_level='critical')"
    )
    with tempfile.TemporaryFile(mode="w+t", encoding="utf-8") as server_log:
        process = subprocess.Popen(  # noqa: S603 - fixed local test-app entry point
            [sys.executable, "-c", command],
            cwd=service1_root,
            env=env,
            stdout=server_log,
            stderr=subprocess.STDOUT,
        )
        base_url = f"http://127.0.0.1:{port}"
        try:
            deadline = time.monotonic() + 60
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    server_log.seek(0)
                    pytest.fail(
                        "Service 1 test application exited before becoming ready:\n"
                        + server_log.read()[-4000:]
                    )
                try:
                    response = httpx.get(
                        f"{base_url}/api/v1/health/live",
                        timeout=0.5,
                        trust_env=False,
                    )
                    if response.status_code == 200:
                        break
                except httpx.HTTPError:
                    time.sleep(0.1)
            else:
                server_log.seek(0)
                pytest.fail(
                    "Service 1 test application did not become ready:\n"
                    + server_log.read()[-4000:]
                )
            yield base_url
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


@pytest.mark.asyncio
async def test_actual_service1_http_contract_and_authentication(
    service1_runtime: str,
) -> None:
    client = MarketDataClient(
        base_url=service1_runtime,
        api_key=TEST_API_KEY,
        timeout_seconds=2,
        max_retries=0,
    )
    try:
        check = await client.check_connectivity(request_id="service2-http-test")
        assert check.state == UpstreamState.UNAVAILABLE
        assert check.authentication_status == "verified"
        assert check.provider_status == "test_adapter_only"
        assert check.contract_status == UpstreamContractStatus.VERIFIED

        providers = await client.list_providers(request_id="service2-http-test")
        assert providers.data is not None
        provider = next(
            item for item in providers.data if item.provider_id == "test-adapter"
        )
        assert provider.provider_type.value == "test"

        dataset = await client.fetch_historical_candles(
            "EUR/USD",
            provider_id="test-adapter",
            start=datetime(2025, 1, 2, tzinfo=UTC),
            end=datetime(2025, 1, 9, tzinfo=UTC),
            timeframe="D1",
            price_basis="bid",
            limit=10,
            request_id="service2-http-test",
        )
        assert dataset.provider_id == "test-adapter"
        assert dataset.canonical_instrument == "EUR/USD"
        assert dataset.coverage.complete is False
        assert dataset.coverage.missing_intervals
        assert all(candle.source == "test-adapter" for candle in dataset.candles)
    finally:
        await client.aclose()

    unauthenticated = MarketDataClient(
        base_url=service1_runtime,
        api_key="incorrect-integration-key",
        timeout_seconds=2,
        max_retries=0,
    )
    try:
        with pytest.raises(UpstreamError):
            await unauthenticated.list_providers(request_id="service2-auth-test")
    finally:
        await unauthenticated.aclose()
