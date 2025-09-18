from pathlib import Path

import pytest
import textwrap

from praeparo.datasources import DataSourceConfigError, resolve_datasource


@pytest.fixture()
def project_layout(tmp_path: Path) -> Path:
    root = tmp_path / "example_project"
    visuals = root / "visuals"
    datasources = root / "datasources"
    visuals.mkdir(parents=True)
    datasources.mkdir(parents=True)
    (visuals / "demo.yaml").write_text(
        "type: matrix\nrows: [{template: '{{foo}}'}]\nvalues: [{id: Demo}]\n",
        encoding="utf-8",
    )
    return root


@pytest.fixture()
def powerbi_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PRAEPARO_PBI_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("PRAEPARO_PBI_CLIENT_SECRET", "env-client-secret")
    monkeypatch.setenv("PRAEPARO_PBI_TENANT_ID", "env-tenant")
    monkeypatch.setenv("PRAEPARO_PBI_REFRESH_TOKEN", "env-refresh")
    monkeypatch.setenv("PRAEPARO_PBI_SCOPE", "env-scope")


def test_resolve_mock_fallback(project_layout: Path) -> None:
    visual_path = project_layout / "visuals" / "demo.yaml"

    resolved = resolve_datasource(None, visual_path=visual_path)

    assert resolved.type == "mock"
    assert resolved.dataset_id is None


def test_resolve_mock_keyword(project_layout: Path) -> None:
    visual_path = project_layout / "visuals" / "demo.yaml"

    resolved = resolve_datasource("mock", visual_path=visual_path)

    assert resolved.type == "mock"


def test_resolve_powerbi_defaults_from_env(
    powerbi_env, monkeypatch: pytest.MonkeyPatch, project_layout: Path
) -> None:
    monkeypatch.setenv("PRAEPARO_PBI_DATASET_ID", "env-dataset")
    monkeypatch.setenv("PRAEPARO_PBI_WORKSPACE_ID", "env-workspace")

    datasources = project_layout / "datasources"
    datasources.joinpath("default.yaml").write_text("type: powerbi\n", encoding="utf-8")
    visual_path = project_layout / "visuals" / "demo.yaml"

    resolved = resolve_datasource("default", visual_path=visual_path)

    assert resolved.type == "powerbi"
    assert resolved.dataset_id == "env-dataset"
    assert resolved.workspace_id == "env-workspace"
    assert resolved.settings is not None
    assert resolved.settings.client_id == "env-client-id"
    assert resolved.settings.scope == "env-scope"


def test_resolve_powerbi_with_overrides(
    monkeypatch: pytest.MonkeyPatch, project_layout: Path
) -> None:
    monkeypatch.setenv("CUSTOM_DATASET", "custom-dataset")
    monkeypatch.setenv("CUSTOM_WORKSPACE", "custom-workspace")
    monkeypatch.setenv("CUSTOM_TENANT", "custom-tenant")
    monkeypatch.setenv("CUSTOM_CLIENT", "custom-client")
    monkeypatch.setenv("CUSTOM_SECRET", "custom-secret")
    monkeypatch.setenv("CUSTOM_REFRESH", "custom-refresh")

    datasources = project_layout / "datasources"
    datasources.joinpath("analytics.yaml").write_text(
        textwrap.dedent(
            """
            type: powerbi
            datasetId: "${env:CUSTOM_DATASET}"
            workspaceId: "${env:CUSTOM_WORKSPACE}"
            tenantId: "${env:CUSTOM_TENANT}"
            clientId: "${env:CUSTOM_CLIENT}"
            clientSecret: "${env:CUSTOM_SECRET}"
            refreshToken: "${env:CUSTOM_REFRESH}"
            scope: "custom-scope"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    visual_path = project_layout / "visuals" / "demo.yaml"

    resolved = resolve_datasource("analytics", visual_path=visual_path)

    assert resolved.type == "powerbi"
    assert resolved.dataset_id == "custom-dataset"
    assert resolved.workspace_id == "custom-workspace"
    assert resolved.settings is not None
    assert resolved.settings.tenant_id == "custom-tenant"
    assert resolved.settings.client_id == "custom-client"
    assert resolved.settings.client_secret == "custom-secret"
    assert resolved.settings.refresh_token == "custom-refresh"
    assert resolved.settings.scope == "custom-scope"


def test_missing_dataset_raises(
    powerbi_env, project_layout: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("PRAEPARO_PBI_DATASET_ID", raising=False)

    datasources = project_layout / "datasources"
    datasources.joinpath("default.yaml").write_text("type: powerbi\n", encoding="utf-8")
    visual_path = project_layout / "visuals" / "demo.yaml"

    with pytest.raises(DataSourceConfigError):
        resolve_datasource("default", visual_path=visual_path)


def test_relative_path_lookup(
    powerbi_env, monkeypatch: pytest.MonkeyPatch, project_layout: Path
) -> None:
    monkeypatch.setenv("PRAEPARO_PBI_DATASET_ID", "env-dataset")

    datasources = project_layout / "datasources"
    datasources.joinpath("default.yaml").write_text("type: powerbi\n", encoding="utf-8")
    visual_path = project_layout / "visuals" / "demo.yaml"

    resolved = resolve_datasource(
        "../datasources/default.yaml", visual_path=visual_path
    )

    assert resolved.type == "powerbi"
    assert resolved.dataset_id == "env-dataset"
