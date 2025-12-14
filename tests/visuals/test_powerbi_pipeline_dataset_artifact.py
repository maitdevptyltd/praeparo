from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

from praeparo.models import PowerBISource, PowerBIVisualConfig
from praeparo.pipeline import ExecutionContext, PipelineOptions, VisualPipeline

# Import the visual module so its pipeline definition is registered.
import praeparo.visuals.powerbi as powerbi_visuals
from praeparo.powerbi import PowerBISettings


def test_powerbi_pipeline_emits_stable_dataset_manifest(tmp_path: Path, monkeypatch) -> None:
    artefact_dir = tmp_path / "artefacts"
    exports_dir = tmp_path / "exports"

    class FakePowerBIClient:
        def __init__(self, settings: PowerBISettings, *, timeout: float = 30.0) -> None:
            self._settings = settings
            self._timeout = timeout

        async def __aenter__(self) -> "FakePowerBIClient":
            return self

        async def __aexit__(self, exc_type, exc, tb) -> None:
            return None

        async def export_to_file(
            self,
            *,
            group_id: str,
            report_id: str,
            payload: Mapping[str, object],
            dest_path: str | Path,
            mode: str = "report",
            poll_interval: float = 2.0,
            timeout: float = 300.0,
        ) -> str:
            path = Path(dest_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"stub")
            return str(path)

    monkeypatch.setattr(powerbi_visuals, "PowerBIClient", FakePowerBIClient)
    monkeypatch.setattr(
        powerbi_visuals.PowerBISettings,
        "from_env",
        classmethod(lambda cls, env=None: PowerBISettings(tenant_id="t", client_id="c", client_secret="s", refresh_token="r")),
    )

    config = PowerBIVisualConfig(
        title="Matters On Hold",
        mode="report",
        source=PowerBISource(group_id="group", report_id="report", page="Page 1"),
        filters=["MatterType eq 'Residential'"],
    )
    pipeline = VisualPipeline()
    context = ExecutionContext(
        config_path=tmp_path / "visual.yaml",
        project_root=tmp_path,
        options=PipelineOptions(
            artefact_dir=artefact_dir,
            outputs=[],
            metadata={"build_artifacts_dir": exports_dir},
        ),
    )

    result = pipeline.execute(config, context)

    assert result.dataset_path is not None
    assert result.dataset_path.name == "data.json"
    assert result.dataset_path.exists()

    payload = json.loads(result.dataset_path.read_text(encoding="utf-8"))
    assert isinstance(payload, dict)

    assert payload.get("format") == "png"
    export_payload = payload.get("export_payload")
    assert isinstance(export_payload, dict)
    assert export_payload.get("format") == "PNG"

    report_configuration = export_payload.get("powerBIReportConfiguration")
    assert isinstance(report_configuration, dict)
    assert report_configuration.get("pages") == [{"pageName": "Page 1"}]
    assert report_configuration.get("reportLevelFilters") == [{"filter": "MatterType eq 'Residential'"}]

    # Ensure we never persist Power BI credentials in dataset manifests.
    dataset_text = result.dataset_path.read_text(encoding="utf-8")
    assert "client_secret" not in dataset_text
    assert "refresh_token" not in dataset_text
