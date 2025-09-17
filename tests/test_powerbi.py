import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from praeparo.powerbi import (
    PowerBIAuthenticationError,
    PowerBIClient,
    PowerBIConfigurationError,
    PowerBIQueryError,
    PowerBISettings,
)


def test_settings_from_env_missing(monkeypatch):
    monkeypatch.delenv("PRAEPARO_PBI_CLIENT_ID", raising=False)
    monkeypatch.delenv("PRAEPARO_PBI_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("PRAEPARO_PBI_TENANT_ID", raising=False)
    monkeypatch.delenv("PRAEPARO_PBI_REFRESH_TOKEN", raising=False)

    with pytest.raises(PowerBIConfigurationError):
        PowerBISettings.from_env({})


@pytest.mark.asyncio
async def test_acquire_token_and_execute(monkeypatch):
    settings = PowerBISettings(
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
    )

    token_response: dict[str, Any] = {"access_token": "abc123", "expires_in": 3600}
    query_payload: dict[str, Any] = {
        "results": [
            {
                "tables": [
                    {
                        "rows": [
                            {
                                "dim.City": "Seattle",
                                "Sales": 100,
                            }
                        ]
                    }
                ]
            }
        ]
    }

    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            calls.append("token")
            return httpx.Response(200, json=token_response)
        if request.url.host == "api.powerbi.com":
            calls.append("query")
            if request.headers.get("Authorization") != "Bearer abc123":
                return httpx.Response(401)
            return httpx.Response(200, json=query_payload)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    async with PowerBIClient(settings) as client:
        client._client = httpx.AsyncClient(transport=transport, timeout=client._timeout)
        rows = await client.execute_dax(dataset_id="dataset", query="EVALUATE")

    assert rows == query_payload["results"][0]["tables"][0]["rows"]
    assert calls == ["token", "query"]
