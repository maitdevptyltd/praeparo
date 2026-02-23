from __future__ import annotations

from pathlib import Path
from typing import cast

from praeparo.models import BaseVisualConfig, PackConfig
from praeparo.pack.metric_context import ResolvedMetricContext
from praeparo.pack.runner import run_pack
from praeparo.pipeline import PipelineOptions, VisualExecutionResult, VisualPipeline
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
                formats_by_alias={},
            )
        return ResolvedMetricContext(
            aliases={"count_docs_sent": 3.0},
            by_key={},
            signatures_by_key={},
            formats_by_alias={},
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
        pipeline=cast(VisualPipeline, pipeline),
    )

    assert results
    assert pack.slides[0].title == "Highlights 7.0"
    assert pipeline.contexts
    context_payload = pipeline.contexts[0].options.metadata.get("context") or {}
    assert context_payload["total_instructions"] == 7.0
    assert context_payload["count_docs_sent"] == 3.0


def test_governance_highlights_renders_after_metric_injection(monkeypatch, tmp_path: Path) -> None:
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
                    "context": {
                        "metrics": {"documents_sent": "count_docs_sent"},
                        "governance_highlights": "Instruction volume is {{ total_instructions }} and docs {{ count_docs_sent }}.",
                    },
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
                formats_by_alias={},
            )
        return ResolvedMetricContext(
            aliases={"count_docs_sent": 3.0},
            by_key={},
            signatures_by_key={},
            formats_by_alias={},
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
        pipeline=cast(VisualPipeline, pipeline),
    )

    assert results
    assert pipeline.contexts
    context_payload = pipeline.contexts[0].options.metadata.get("context") or {}
    assert (
        context_payload["governance_highlights"]
        == "Instruction volume is 7.0 and docs 3.0."
    )


def test_registry_metrics_calculate_defaults_apply_to_slide_metric_context(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)
    (metrics_root / "documents_sent.yaml").write_text(
        """
key: documents_sent
display_name: Documents Sent
section: documents
define: "COUNTROWS('fact_documents')"
""",
        encoding="utf-8",
    )

    context_root = tmp_path / "registry" / "context"
    context_root.mkdir(parents=True)
    (context_root / "month.yaml").write_text(
        "\n".join(
            [
                "context:",
                "  month: \"2025-11-01\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (context_root / "metrics.yaml").write_text(
        "\n".join(
            [
                "context:",
                "  metrics:",
                "    calculate:",
                "      month: |",
                "        'dim_calendar'[month] = DATEVALUE(\"{{ month }}\")",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {"customer": "Example Bank"},
            "slides": [
                {
                    "title": "Highlights",
                    "context": {"metrics": {"documents_sent": "total_documents"}},
                    "visual": {"ref": "dummy.yaml"},
                }
            ],
        }
    )

    pipeline = _StubPipeline()

    def dummy_loader(_: Path) -> BaseVisualConfig:
        return BaseVisualConfig(type="dummy_metric_ctx")

    output_root = tmp_path / "artefacts"
    run_pack(
        tmp_path / "pack.yaml",
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=PipelineOptions(metadata={"metrics_root": metrics_root, "data_mode": "mock"}),
        visual_loader=dummy_loader,
        pipeline=cast(VisualPipeline, pipeline),
    )

    dax_path = output_root / "metric_context.slide_1.dax"
    assert dax_path.exists()
    dax_text = dax_path.read_text(encoding="utf-8")
    assert 'DATEVALUE("2025-11-01")' in dax_text


def test_pack_metrics_calculate_overrides_registry_default(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)
    (metrics_root / "documents_sent.yaml").write_text(
        """
key: documents_sent
display_name: Documents Sent
section: documents
define: "COUNTROWS('fact_documents')"
""",
        encoding="utf-8",
    )

    context_root = tmp_path / "registry" / "context"
    context_root.mkdir(parents=True)
    (context_root / "month.yaml").write_text(
        "\n".join(
            [
                "context:",
                "  month: \"2025-11-01\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (context_root / "metrics.yaml").write_text(
        "\n".join(
            [
                "context:",
                "  metrics:",
                "    calculate:",
                "      month: |",
                "        'dim_calendar'[month] = DATEVALUE(\"{{ month }}\")",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {
                "customer": "Example Bank",
                "metrics": {"calculate": {"month": "TRUE()"}},
            },
            "slides": [
                {
                    "title": "Highlights",
                    "context": {"metrics": {"documents_sent": "total_documents"}},
                    "visual": {"ref": "dummy.yaml"},
                }
            ],
        }
    )

    pipeline = _StubPipeline()

    def dummy_loader(_: Path) -> BaseVisualConfig:
        return BaseVisualConfig(type="dummy_metric_ctx")

    output_root = tmp_path / "artefacts"
    run_pack(
        tmp_path / "pack.yaml",
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=PipelineOptions(metadata={"metrics_root": metrics_root, "data_mode": "mock"}),
        visual_loader=dummy_loader,
        pipeline=cast(VisualPipeline, pipeline),
    )

    dax_path = output_root / "metric_context.slide_1.dax"
    assert dax_path.exists()
    dax_text = dax_path.read_text(encoding="utf-8")
    assert "TRUE()" in dax_text
    assert "DATEVALUE" not in dax_text


def test_slide_calculate_applies_to_slide_metric_context(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)
    (metrics_root / "documents_sent.yaml").write_text(
        """
key: documents_sent
display_name: Documents Sent
section: documents
define: "COUNTROWS('fact_documents')"
""",
        encoding="utf-8",
    )

    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {"customer": "Example Bank"},
            "slides": [
                {
                    "title": "Highlights",
                    "calculate": {
                        "segment": "'dim_funding_channel_type'[FundingChannelTypeName] = \"First Party\"",
                    },
                    "context": {"metrics": {"documents_sent": "total_documents"}},
                    "visual": {"ref": "dummy.yaml"},
                }
            ],
        }
    )

    pipeline = _StubPipeline()

    def dummy_loader(_: Path) -> BaseVisualConfig:
        return BaseVisualConfig(type="dummy_metric_ctx")

    output_root = tmp_path / "artefacts"
    run_pack(
        tmp_path / "pack.yaml",
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=PipelineOptions(metadata={"metrics_root": metrics_root, "data_mode": "mock"}),
        visual_loader=dummy_loader,
        pipeline=cast(VisualPipeline, pipeline),
    )

    dax_path = output_root / "metric_context.slide_1.dax"
    assert dax_path.exists()
    dax_text = dax_path.read_text(encoding="utf-8")
    assert "'dim_funding_channel_type'[FundingChannelTypeName] = \"First Party\"" in dax_text


def test_slide_metrics_calculate_overrides_slide_calculate_by_name(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)
    (metrics_root / "documents_sent.yaml").write_text(
        """
key: documents_sent
display_name: Documents Sent
section: documents
define: "COUNTROWS('fact_documents')"
""",
        encoding="utf-8",
    )

    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {"customer": "Example Bank"},
            "slides": [
                {
                    "title": "Highlights",
                    "calculate": {
                        "segment": "'dim_funding_channel_type'[FundingChannelTypeName] = \"From Slide\"",
                    },
                    "context": {
                        "metrics": {
                            "calculate": {
                                "segment": "'dim_funding_channel_type'[FundingChannelTypeName] = \"From Metrics\"",
                            },
                            "bindings": {"documents_sent": "total_documents"},
                        }
                    },
                    "visual": {"ref": "dummy.yaml"},
                }
            ],
        }
    )

    pipeline = _StubPipeline()

    def dummy_loader(_: Path) -> BaseVisualConfig:
        return BaseVisualConfig(type="dummy_metric_ctx")

    output_root = tmp_path / "artefacts"
    run_pack(
        tmp_path / "pack.yaml",
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=PipelineOptions(metadata={"metrics_root": metrics_root, "data_mode": "mock"}),
        visual_loader=dummy_loader,
        pipeline=cast(VisualPipeline, pipeline),
    )

    dax_path = output_root / "metric_context.slide_1.dax"
    assert dax_path.exists()
    dax_text = dax_path.read_text(encoding="utf-8")
    assert "'dim_funding_channel_type'[FundingChannelTypeName] = \"From Metrics\"" in dax_text
    assert "'dim_funding_channel_type'[FundingChannelTypeName] = \"From Slide\"" not in dax_text
