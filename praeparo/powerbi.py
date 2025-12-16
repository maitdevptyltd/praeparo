"""Power BI connectivity helpers."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

import httpx

from .env import ensure_env_loaded

class PowerBIConfigurationError(RuntimeError):
    """Raised when required Power BI configuration is missing."""


class PowerBIAuthenticationError(RuntimeError):
    """Raised when acquiring an access token fails."""


class PowerBIQueryError(RuntimeError):
    """Raised when a DAX query execution fails."""


class PowerBIExportError(RuntimeError):
    """Raised when Power BI ExportToFile fails."""


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
        if env is None:
            ensure_env_loaded()
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
            timeout=600
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

        return [_normalise_row_keys(row) for row in rows]

    async def export_to_file(
        self,
        *,
        group_id: str,
        report_id: str,
        payload: Mapping[str, Any],
        dest_path: str | os.PathLike[str],
        mode: str = "report",
        poll_interval: float = 2.0,
        timeout: float = 300.0,
    ) -> str:
        """Call ExportToFile for reports or paginated reports and persist the result.

        The request kicks off an export job, polls until completion (or failure),
        then downloads the file to `dest_path`. Callers choose the export payload
        (format/pages/filters) so this helper stays transport-focused.
        """

        token = await self.get_access_token()
        base_url = _export_base_url(group_id, report_id, mode)
        headers = {"Authorization": f"Bearer {token}"}

        start = await self._client.post(f"{base_url}/ExportTo", headers=headers, json=payload)
        if start.status_code not in (200, 202):
            raise PowerBIExportError(
                f"ExportToFile failed ({start.status_code}): {start.text}"
            )

        try:
            export_id = start.json()["id"]
        except Exception as exc:
            raise PowerBIExportError("ExportToFile response missing export id.") from exc

        deadline = time.time() + timeout
        status = "Running"
        retry_after: float | None = None
        while status not in {"Succeeded", "Failed"}:
            # Pace polling using either Retry-After from the service or the configured interval.
            if time.time() > deadline:
                raise PowerBIExportError("ExportToFile polling timed out.")

            wait_for = retry_after if retry_after and retry_after > 0 else poll_interval
            await asyncio.sleep(wait_for)

            status_resp = await self._client.get(
                f"{base_url}/exports/{export_id}",
                headers=headers,
            )
            if status_resp.status_code not in (200, 202):
                raise PowerBIExportError(
                    f"Failed to poll export status ({status_resp.status_code}): {status_resp.text}"
                )
            payload = status_resp.json()
            status = payload.get("status", "Unknown")
            retry_after = _parse_retry_after(status_resp)

            if status == "Failed":
                message = payload.get("error", {}).get("message") if isinstance(payload, dict) else None
                raise PowerBIExportError(f"Export failed: {message or 'unknown error'}")

        file_resp = await self._client.get(
            f"{base_url}/exports/{export_id}/file",
            headers=headers,
        )
        if file_resp.status_code != 200:
            raise PowerBIExportError(
                f"Failed to download export file ({file_resp.status_code}): {file_resp.text}"
            )

        dest = os.fspath(dest_path)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        Path(dest).write_bytes(file_resp.content)
        return dest


__all__ = [
    "PowerBIClient",
    "PowerBISettings",
    "PowerBIAuthenticationError",
    "PowerBIConfigurationError",
    "PowerBIQueryError",
    "PowerBIExportError",
]


def _normalise_row_keys(row: dict[str, object]) -> dict[str, object]:
    normalised: dict[str, object] = {}
    for key, value in row.items():
        normalised[key] = value
        stripped = _strip_bracket_wrappers(key)
        if stripped and stripped not in normalised:
            normalised[stripped] = value
    return normalised


def _strip_bracket_wrappers(label: str) -> str | None:
    start = label.rfind("[")
    end = label.rfind("]")
    if start == -1 or end == -1 or end <= start + 1:
        return None
    candidate = label[start + 1 : end].strip()
    if not candidate or candidate == label:
        return None
    return candidate


def _export_base_url(group_id: str, report_id: str, mode: str) -> str:
    route = "rdlreports" if mode == "paginated" else "reports"
    return f"https://api.powerbi.com/v1.0/myorg/groups/{group_id}/{route}/{report_id}"


def _parse_retry_after(response) -> float | None:
    try:
        header = response.headers.get("Retry-After")
        if header is None:
            return None
        
        # Retry a bit faster
        return float(header) / 3
    except Exception:
        return None
