import asyncio
from pathlib import Path
from typing import Any

import httpx
import pytest

from praeparo.powerbi import (
    PowerBIClient,
    PowerBIExportError,
    PowerBISettings,
)


def _token_response() -> httpx.Response:
    return httpx.Response(200, json={"access_token": "abc123", "expires_in": 3600})


@pytest.mark.asyncio
async def test_export_to_file_report(tmp_path: Path):
    # Arrange a happy-path report export with two status polls.
    settings = PowerBISettings(
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
    )

    calls: list[str] = []
    export_status: list[str] = ["Running", "Succeeded"]

    def handler(request: httpx.Request) -> httpx.Response:
        url = request.url
        if "login.microsoftonline.com" in url.host:
            calls.append("token")
            return _token_response()
        if url.path.endswith("/ExportTo"):
            calls.append("export_start")
            return httpx.Response(202, json={"id": "export-1"})
        if url.path.endswith("/exports/export-1"):
            calls.append("export_status")
            status = export_status.pop(0)
            return httpx.Response(200, json={"status": status})
        if url.path.endswith("/exports/export-1/file"):
            calls.append("export_file")
            return httpx.Response(200, content=b"PNGDATA")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    # Act: run the export and capture the saved file path.
    async with PowerBIClient(settings) as client:
        client._client = httpx.AsyncClient(transport=transport, timeout=client._timeout)
        dest = tmp_path / "out.png"
        path = await client.export_to_file(
            group_id="group",
            report_id="report",
            payload={"format": "PNG"},
            dest_path=dest,
            mode="report",
            poll_interval=0.01,
            timeout=1.0,
        )

    # Assert: file written and call sequence matches expectations.
    assert Path(path).read_bytes() == b"PNGDATA"
    assert calls == ["token", "export_start", "export_status", "export_status", "export_file"]


@pytest.mark.asyncio
async def test_export_to_file_paginated_route(tmp_path: Path):
    # Arrange a paginated export to confirm the rdlreports route is used.
    settings = PowerBISettings(
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
    )

    seen_paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_paths.append(request.url.path)
        if "login.microsoftonline.com" in request.url.host:
            return _token_response()
        if request.url.path.endswith("/ExportTo"):
            return httpx.Response(202, json={"id": "export-2"})
        if request.url.path.endswith("/exports/export-2"):
            return httpx.Response(200, json={"status": "Succeeded"})
        if request.url.path.endswith("/exports/export-2/file"):
            return httpx.Response(200, content=b"PDFDATA")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    # Act: trigger the export and ignore the return value.
    async with PowerBIClient(settings) as client:
        client._client = httpx.AsyncClient(transport=transport, timeout=client._timeout)
        dest = tmp_path / "out.pdf"
        await client.export_to_file(
            group_id="group",
            report_id="report",
            payload={"format": "PDF"},
            dest_path=dest,
            mode="paginated",
            poll_interval=0.01,
            timeout=1.0,
        )

    # Assert: the paginated endpoint was hit during the flow.
    assert any("rdlreports" in path for path in seen_paths)


@pytest.mark.asyncio
async def test_export_to_file_failure(tmp_path: Path):
    # Arrange a failing export start to surface PowerBIExportError.
    settings = PowerBISettings(
        tenant_id="tenant",
        client_id="client",
        client_secret="secret",
        refresh_token="refresh",
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if "login.microsoftonline.com" in request.url.host:
            return _token_response()
        if request.url.path.endswith("/ExportTo"):
            return httpx.Response(400, text="bad request")
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)

    # Act & assert: error raised when the start request fails.
    async with PowerBIClient(settings) as client:
        client._client = httpx.AsyncClient(transport=transport, timeout=client._timeout)
        with pytest.raises(PowerBIExportError):
            await client.export_to_file(
                group_id="group",
                report_id="report",
                payload={"format": "PNG"},
                dest_path=tmp_path / "out.png",
                mode="report",
                poll_interval=0.01,
                timeout=0.5,
            )
