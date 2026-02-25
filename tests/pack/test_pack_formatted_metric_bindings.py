from __future__ import annotations

from pathlib import Path
from typing import Mapping

import pytest

from praeparo.models import BaseVisualConfig, PackConfig
from praeparo.pack.metric_context import ResolvedMetricContext
from praeparo.pack.runner import run_pack
from praeparo.pack.templating import create_pack_jinja_env
from praeparo.pipeline import ExecutionContext, PipelineOptions, VisualExecutionResult, VisualPipeline
from praeparo.pipeline.outputs import PipelineOutputArtifact
from praeparo.visuals.context_models import VisualContextModel


class _CapturingPipeline(VisualPipeline[VisualContextModel]):
    def __init__(self) -> None:
        super().__init__()
        self.contexts: list[ExecutionContext[VisualContextModel]] = []

    def execute(
        self,
        visual: BaseVisualConfig,
        context: ExecutionContext[VisualContextModel],
    ) -> VisualExecutionResult:
        self.contexts.append(context)
        outputs: list[PipelineOutputArtifact] = []
        for target in context.options.outputs:
            target.path.parent.mkdir(parents=True, exist_ok=True)
            target.path.write_text("dummy", encoding="utf-8")
            outputs.append(PipelineOutputArtifact(kind=target.kind, path=target.path))
        return VisualExecutionResult(config=visual, outputs=outputs)


def test_governance_highlights_formats_bindings_but_preserves_raw_context(monkeypatch, tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {
                "customer": "Example Bank",
                "metrics": {
                    "bindings": [
                        {
                            "key": "instructions_received",
                            "alias": "total_instructions",
                            "format": "number:0",
                        }
                    ]
                },
            },
            "slides": [
                {
                    "title": "Highlights",
                    "context": {
                        "governance_highlights": "Volume {{ total_instructions }}; raw {{ total_instructions.value }}.",
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
        allow_empty=True,
        artefact_dir=None,
    ) -> ResolvedMetricContext:
        if scope == "root":
            return ResolvedMetricContext(
                aliases={"total_instructions": 7.0},
                by_key={"instructions_received": 7.0},
                signatures_by_key={"instructions_received": ("instructions_received", tuple(), "number:0", None)},
                formats_by_alias={"total_instructions": "number:0"},
            )
        assert inherited is not None
        return inherited

    monkeypatch.setattr(
        "praeparo.pack.runner.resolve_metric_context",
        fake_resolve_metric_context,
    )

    pipeline = _CapturingPipeline()

    def dummy_loader(_: Path) -> BaseVisualConfig:
        return BaseVisualConfig(type="dummy_formatted_bindings")

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
    assert pipeline.contexts

    context_payload = pipeline.contexts[0].options.metadata.get("context") or {}
    assert isinstance(context_payload, Mapping)
    assert context_payload["total_instructions"] == 7.0
    assert isinstance(context_payload["total_instructions"], float)
    assert context_payload["governance_highlights"] == "Volume 7; raw 7.0."


def test_key_insights_formats_bindings_but_preserves_raw_context(monkeypatch, tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {
                "customer": "Example Bank",
                "metrics": {
                    "bindings": [
                        {
                            "key": "instructions_received",
                            "alias": "total_instructions",
                            "format": "number:1",
                        }
                    ]
                },
            },
            "slides": [
                {
                    "title": "Highlights",
                    "context": {
                        "key_insights": "Volume {{ total_instructions }}; raw {{ total_instructions.value }}.",
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
        allow_empty=True,
        artefact_dir=None,
    ) -> ResolvedMetricContext:
        if scope == "root":
            return ResolvedMetricContext(
                aliases={"total_instructions": 7.26},
                by_key={"instructions_received": 7.26},
                signatures_by_key={"instructions_received": ("instructions_received", tuple(), "number:1", None)},
                formats_by_alias={"total_instructions": "number:1"},
            )
        assert inherited is not None
        return inherited

    monkeypatch.setattr(
        "praeparo.pack.runner.resolve_metric_context",
        fake_resolve_metric_context,
    )

    pipeline = _CapturingPipeline()

    def dummy_loader(_: Path) -> BaseVisualConfig:
        return BaseVisualConfig(type="dummy_formatted_bindings")

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
    assert pipeline.contexts

    context_payload = pipeline.contexts[0].options.metadata.get("context") or {}
    assert isinstance(context_payload, Mapping)
    assert context_payload["total_instructions"] == 7.26
    assert isinstance(context_payload["total_instructions"], float)
    assert context_payload["key_insights"] == "Volume 7.3; raw 7.26."


def test_display_render_skips_execution_keys(monkeypatch, tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {
                "metrics": {
                    "bindings": [
                        {
                            "key": "instructions_received",
                            "alias": "total_instructions",
                            "format": "number:1",
                        }
                    ]
                },
            },
            "slides": [
                {
                    "title": "Highlights",
                    "context": {
                        "define": "Value {{ total_instructions }} (should stay raw)",
                        "note": "Value {{ total_instructions }} (should format)",
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
        allow_empty=True,
        artefact_dir=None,
    ) -> ResolvedMetricContext:
        if scope == "root":
            return ResolvedMetricContext(
                aliases={"total_instructions": 7.26},
                by_key={"instructions_received": 7.26},
                signatures_by_key={"instructions_received": ("instructions_received", tuple(), "number:1", None)},
                formats_by_alias={"total_instructions": "number:1"},
            )
        assert inherited is not None
        return inherited

    monkeypatch.setattr(
        "praeparo.pack.runner.resolve_metric_context",
        fake_resolve_metric_context,
    )

    pipeline = _CapturingPipeline()

    def dummy_loader(_: Path) -> BaseVisualConfig:
        return BaseVisualConfig(type="dummy_formatted_bindings")

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
    assert pipeline.contexts

    context_payload = pipeline.contexts[0].options.metadata.get("context") or {}
    assert isinstance(context_payload, Mapping)
    assert context_payload["define"] == "Value 7.26 (should stay raw)"
    assert context_payload["note"] == "Value 7.3 (should format)"


def test_invalid_metric_binding_format_fails_validation() -> None:
    with pytest.raises(ValueError, match=r"Invalid format token 'nonsense:3'.*count_instructions"):
        PackConfig.model_validate(
            {
                "schema": "test-pack",
                "context": {
                    "metrics": {
                        "bindings": [
                            {
                                "key": "instructions_received",
                                "alias": "count_instructions",
                                "format": "nonsense:3",
                            }
                        ]
                    }
                },
                "slides": [{"title": "Slide", "visual": {"ref": "dummy.yaml"}}],
            }
        )


def test_ratio_to_defaults_to_percent_format_for_display() -> None:
    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {
                "metrics": {
                    "bindings": [
                        {
                            "key": "documents_verified.within_1_day",
                            "alias": "pct_verified_1d",
                            "ratio_to": True,
                        }
                    ]
                }
            },
            "slides": [{"title": "Slide", "visual": {"ref": "dummy.yaml"}}],
        }
    )

    bindings = pack.context.metrics.bindings if pack.context.metrics else None
    assert bindings is not None and len(bindings) == 1
    binding = bindings[0]
    assert binding.format == "percent:0"

    env = create_pack_jinja_env()
    from praeparo.pack.formatted_values import FormattedMetricValue

    context: dict[str, object] = {
        "pct_verified_1d": FormattedMetricValue(value=0.54, format=binding.format),
    }
    rendered = env.from_string("Rate {{ pct_verified_1d }} (raw {{ pct_verified_1d.value }}).").render(**context)
    assert rendered == "Rate 54% (raw 0.54)."
