from __future__ import annotations

from pathlib import Path

from praeparo.models import BaseVisualConfig
from praeparo.pipeline import PipelineDataOptions, PipelineOptions, VisualExecutionResult
from praeparo.pipeline.outputs import OutputKind, OutputTarget, PipelineOutputArtifact
from praeparo.visuals.render_manifest import build_visual_render_manifest


def test_build_visual_render_manifest_collects_outputs_and_sidecars(tmp_path: Path) -> None:
    project_root = tmp_path
    artefact_dir = project_root / "build" / "performance_dashboard" / "_artifacts"
    artefact_dir.mkdir(parents=True, exist_ok=True)

    schema_path = artefact_dir / "schema.json"
    schema_path.write_text("{}", encoding="utf-8")
    dataset_path = artefact_dir / "data.json"
    dataset_path.write_text("{}", encoding="utf-8")
    dax_path = artefact_dir / "governance_matrix.dax"
    dax_path.write_text("EVALUATE {}", encoding="utf-8")
    extra_path = artefact_dir / "matrix.live.payload.json"
    extra_path.write_text("{}", encoding="utf-8")

    html_path = project_root / "build" / "performance_dashboard.html"
    html_path.parent.mkdir(parents=True, exist_ok=True)
    html_path.write_text("<html />", encoding="utf-8")
    png_path = project_root / "build" / "performance_dashboard.png"
    png_path.write_text("png", encoding="utf-8")

    options = PipelineOptions(
        data=PipelineDataOptions(provider_key="mock"),
        outputs=[
            OutputTarget.html(html_path),
            OutputTarget.png(png_path),
        ],
        artefact_dir=artefact_dir,
        metadata={
            "data_mode": "mock",
            "metrics_root": project_root / "registry" / "metrics",
        },
    )

    result = VisualExecutionResult(
        config=BaseVisualConfig(type="governance_matrix"),
        schema_path=schema_path,
        dataset_path=dataset_path,
        outputs=[
            PipelineOutputArtifact(kind=OutputKind.SCHEMA, path=schema_path),
            PipelineOutputArtifact(kind=OutputKind.DATA, path=dataset_path),
            PipelineOutputArtifact(kind=OutputKind.DAX, path=dax_path),
            PipelineOutputArtifact(kind=OutputKind.HTML, path=html_path),
            PipelineOutputArtifact(kind=OutputKind.PNG, path=png_path),
        ],
    )

    manifest = build_visual_render_manifest(
        config_path=project_root / "registry" / "customers" / "foo" / "visuals" / "performance_dashboard.yaml",
        project_root=project_root,
        result=result,
        options=options,
    )

    assert manifest.kind == "visual_inspect"
    assert manifest.baseline_key == "performance_dashboard"
    assert manifest.visual_type == "governance_matrix"
    assert manifest.artefact_root == "build/performance_dashboard/_artifacts"
    assert manifest.html_path == "build/performance_dashboard.html"
    assert manifest.png_path == "build/performance_dashboard.png"
    assert manifest.schema_path == "build/performance_dashboard/_artifacts/schema.json"
    assert manifest.dataset_path == "build/performance_dashboard/_artifacts/data.json"
    assert manifest.metrics_root == "registry/metrics"
    assert [item.model_dump() for item in manifest.requested_outputs] == [
        {"kind": "html", "path": "build/performance_dashboard.html"},
        {"kind": "png", "path": "build/performance_dashboard.png"},
    ]

    output_paths = {item.path for item in manifest.outputs}
    assert "build/performance_dashboard/_artifacts/governance_matrix.dax" in output_paths
    assert "build/performance_dashboard/_artifacts/matrix.live.payload.json" in output_paths
