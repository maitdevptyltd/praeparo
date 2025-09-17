"""Power BI connectivity helpers."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from typing import Any, Mapping

import httpx


class PowerBIConfigurationError(RuntimeError):
    """Raised when required Power BI configuration is missing."""


class PowerBIAuthenticationError(RuntimeError):
    """Raised when acquiring an access token fails."""


class PowerBIQueryError(RuntimeError):
    """Raised when a DAX query execution fails."""


@dataclass
class PowerBISettings:
    """Configuration required to authenticate with Power BI."""

    tenant_id: str
    client_id: str
    client_secret: str
    refresh_token: str
    scope: str = "https://analysis.windows.net/powerbi/api/.default"

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "PowerBISettings":
        env = env or os.environ
        try:
            tenant_id = env["PRAEPARO_PBI_TENANT_ID"]
            client_id = env["PRAEPARO_PBI_CLIENT_ID"]
            client_secret = env["PRAEPARO_PBI_CLIENT_SECRET"]
            refresh_token = env["PRAEPARO_PBI_REFRESH_TOKEN"]
        except KeyError as exc:
            raise PowerBIConfigurationError(
                "Missing Power BI configuration environment variables."
            ) from exc

        scope = env.get("PRAEPARO_PBI_SCOPE", "https://analysis.windows.net/powerbi/api/.default")
        return cls(
            tenant_id=tenant_id,
            client_id=client_id,
            client_secret=client_secret,
            refresh_token=refresh_token,
            scope=scope,
        )


class PowerBIClient:
    """Client for executing DAX queries against Power BI datasets."""

    def __init__(self, settings: PowerBISettings, *, timeout: float = 30.0) -> None:
        self._settings = settings
        self._timeout = timeout
        self._client = httpx.AsyncClient(timeout=timeout)
        self._access_token: str | None = None
        self._expires_at: float | None = None
        self._lock = asyncio.Lock()

    async def __aenter__(self) -> "PowerBIClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_access_token(self) -> str:
        async with self._lock:
            if self._access_token and self._expires_at and self._expires_at - 60 > time.time():
                return self._access_token

            token_url = (
                f"https://login.microsoftonline.com/{self._settings.tenant_id}/oauth2/v2.0/token"
            )
            data = {
                "client_id": self._settings.client_id,
                "client_secret": self._settings.client_secret,
                "grant_type": "refresh_token",
                "refresh_token": self._settings.refresh_token,
                "scope": self._settings.scope,
            }

            response = await self._client.post(token_url, data=data)
            if response.status_code != 200:
                raise PowerBIAuthenticationError(
                    f"Failed to acquire Power BI access token: {response.status_code} {response.text}"
                )

            payload = response.json()
            access_token = payload.get("access_token")
            if not access_token:
                raise PowerBIAuthenticationError("Access token missing in authentication response.")

            expires_in = payload.get("expires_in")
            self._access_token = access_token
            if isinstance(expires_in, (int, float)):
                self._expires_at = time.time() + float(expires_in)
            else:
                self._expires_at = None
            return access_token

    async def execute_dax(
        self,
        dataset_id: str,
        query: str,
        *,
        group_id: str | None = None,
    ) -> list[dict[str, Any]]:
        token = await self.get_access_token()

        base_url = "https://api.powerbi.com/v1.0/myorg"
        if group_id:
            url = f"{base_url}/groups/{group_id}/datasets/{dataset_id}/executeQueries"
        else:
            url = f"{base_url}/datasets/{dataset_id}/executeQueries"

        response = await self._client.post(
            url,
            headers={"Authorization": f"Bearer {token}"},
            json={"queries": [{"query": query}]},
        )

        if response.status_code != 200:
            raise PowerBIQueryError(
                f"Power BI query execution failed: {response.status_code} {response.text}"
            )

        payload = response.json()
        try:
            tables = payload["results"][0]["tables"]
            rows = tables[0]["rows"]
        except (KeyError, IndexError, TypeError) as exc:
            raise PowerBIQueryError("Unexpected response shape from Power BI executeQueries.") from exc

        return rows


__all__ = [
    "PowerBIClient",
    "PowerBISettings",
    "PowerBIAuthenticationError",
    "PowerBIConfigurationError",
    "PowerBIQueryError",
]
