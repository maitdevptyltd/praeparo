from __future__ import annotations

from pathlib import Path

from praeparo.models import BaseVisualConfig, PackConfig
from praeparo.pack.metric_context import ResolvedMetricContext
from praeparo.pack.runner import run_pack
from praeparo.pipeline import PipelineOptions, VisualExecutionResult
from praeparo.pipeline.outputs import PipelineOutputArtifact


class _StubPipeline:
    def __init__(self) -> None:
        self.contexts: list = []

    def execute(self, visual: BaseVisualConfig, context) -> VisualExecutionResult:
        self.contexts.append(context)
        outputs: list[PipelineOutputArtifact] = []
        for target in context.options.outputs:
            target.path.parent.mkdir(parents=True, exist_ok=True)
            target.path.write_text("dummy", encoding="utf-8")
            outputs.append(PipelineOutputArtifact(kind=target.kind, path=target.path))
        return VisualExecutionResult(config=visual, outputs=outputs)


def test_root_and_slide_metrics_injected_into_visual_context(monkeypatch, tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {
                "customer": "Example Bank",
                "metrics": {"instructions_received": "total_instructions"},
            },
            "slides": [
                {
                    "title": "Highlights {{ total_instructions }}",
                    "context": {"metrics": {"documents_sent": "count_docs_sent"}},
                    "visual": {"ref": "dummy.yaml"},
                }
            ],
        }
    )

    def fake_resolve_metric_context(
        *,
        bindings,
        inherited,
        builder_context,
        catalog,
        env,
        base_payload,
        scope: str,
        metrics_calculate=None,
        artefact_dir=None,
    ) -> ResolvedMetricContext:
        if scope == "root":
            return ResolvedMetricContext(
                aliases={"total_instructions": 7.0},
                by_key={"instructions_received": 7.0},
                signatures_by_key={"instructions_received": ("instructions_received", tuple(), None, None)},
            )
        return ResolvedMetricContext(
            aliases={"count_docs_sent": 3.0},
            by_key={},
            signatures_by_key={},
        )

    monkeypatch.setattr(
        "praeparo.pack.runner.resolve_metric_context",
        fake_resolve_metric_context,
    )

    pipeline = _StubPipeline()

    def dummy_loader(_: Path) -> BaseVisualConfig:
        return BaseVisualConfig(type="dummy_metric_ctx")

    results = run_pack(
        tmp_path / "pack.yaml",
        pack,
        project_root=tmp_path,
        output_root=tmp_path / "artefacts",
        base_options=PipelineOptions(metadata={"metrics_root": metrics_root, "data_mode": "mock"}),
        visual_loader=dummy_loader,
        pipeline=pipeline,
    )

    assert results
    assert pack.slides[0].title == "Highlights 7.0"
    assert pipeline.contexts
    context_payload = pipeline.contexts[0].options.metadata.get("context") or {}
    assert context_payload["total_instructions"] == 7.0
    assert context_payload["count_docs_sent"] == 3.0
