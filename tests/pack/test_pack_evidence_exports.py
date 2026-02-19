from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping

import pytest

from praeparo.models import PackConfig, PackEvidenceConfig, PackEvidenceBindingsConfig, PackSlide, PackVisualRef
from praeparo.pack import create_pack_jinja_env, run_pack
from praeparo.pack.evidence import select_evidence_bindings, should_skip_existing
from praeparo.pipeline import OutputKind, PipelineDataOptions, PipelineOptions
from praeparo.visuals.bindings import VisualMetricBinding, register_visual_bindings_adapter


def test_pack_evidence_schema_rejects_empty_select_keys() -> None:
    with pytest.raises(ValueError, match="cannot be empty"):
        PackConfig.model_validate(
            {
                "schema": "test-pack",
                "evidence": {"enabled": True, "bindings": {"select": [""]}},
                "slides": [],
            }
        )


def test_select_evidence_bindings_respects_select_mode_and_overrides() -> None:
    bindings = [
        VisualMetricBinding(
            binding_id="a",
            selector_segments=("a",),
            metric_key="m",
            metadata={"sla": {}},
        ),
        VisualMetricBinding(
            binding_id="b",
            selector_segments=("b",),
            metric_key="m",
            metadata={"ratio_to": True},
        ),
        VisualMetricBinding(
            binding_id="c",
            selector_segments=("c",),
            metric_key="m",
            metadata={"sla": {}, "ratio_to": True},
        ),
    ]

    config = PackEvidenceConfig(
        enabled=True,
        bindings=PackEvidenceBindingsConfig(select=["sla", "ratio_to"], select_mode="all"),
    )
    assert [binding.binding_id for binding in select_evidence_bindings(bindings, selector=config)] == ["c"]

    include_config = PackEvidenceConfig(
        enabled=True,
        bindings=PackEvidenceBindingsConfig(select=["sla", "ratio_to"], select_mode="all", include=["b"]),
    )
    assert [binding.binding_id for binding in select_evidence_bindings(bindings, selector=include_config)] == ["b", "c"]

    exclude_config = PackEvidenceConfig(
        enabled=True,
        bindings=PackEvidenceBindingsConfig(select=["sla"], select_mode="any", exclude=["c"]),
    )
    assert [binding.binding_id for binding in select_evidence_bindings(bindings, selector=exclude_config)] == ["a"]


def test_should_skip_existing_requires_fingerprint_and_files(tmp_path: Path) -> None:
    evidence_path = tmp_path / "evidence.csv"
    dax_path = tmp_path / "_artifacts" / "explain.dax"
    summary_path = tmp_path / "_artifacts" / "summary.json"
    dax_path.parent.mkdir(parents=True, exist_ok=True)

    evidence_path.write_text("x", encoding="utf-8")
    dax_path.write_text("y", encoding="utf-8")
    summary_path.write_text("z", encoding="utf-8")

    from praeparo.metrics.explain_runner import MetricExplainOutputs

    outputs = MetricExplainOutputs(
        artefact_dir=dax_path.parent,
        evidence_path=evidence_path,
        dax_path=dax_path,
        summary_path=summary_path,
    )

    assert (
        should_skip_existing(
            target_key="k",
            fingerprint="abc",
            prior_fingerprints={"k": "abc"},
            outputs=outputs,
        )
        is True
    )
    assert (
        should_skip_existing(
            target_key="k",
            fingerprint="def",
            prior_fingerprints={"k": "abc"},
            outputs=outputs,
        )
        is False
    )


class _StubPipeline:
    def execute(self, visual, context):  # noqa: ANN001
        for target in context.options.outputs:
            if target.kind is OutputKind.PNG:
                target.path.parent.mkdir(parents=True, exist_ok=True)
                target.path.write_text("png", encoding="utf-8")
        return type("Result", (), {"config": visual, "outputs": []})()


class _DummyEvidenceBindingsAdapter:
    def list_bindings(self, visual, *, source_path=None):  # noqa: ANN001
        return (
            VisualMetricBinding(
                binding_id="row_0",
                selector_segments=("row_0",),
                label="Row 0",
                metric_key="documents_sent",
                metadata={"sla": {"target_percent": 95}},
                source_path=source_path,
            ),
            VisualMetricBinding(
                binding_id="row_1",
                selector_segments=("row_1",),
                label="Row 1",
                metric_key="documents_sent.manual",
                metadata={"sla": {"target_percent": 90}},
                source_path=source_path,
            ),
        )

    def resolve_binding(self, visual, selector_segments, *, source_path=None):  # noqa: ANN001
        bindings = self.list_bindings(visual, source_path=source_path)
        for binding in bindings:
            if binding.selector_segments == tuple(selector_segments):
                return binding
        raise ValueError("Unknown binding selector.")


def _write_test_metric(metrics_root: Path) -> None:
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_sent.yaml").write_text(
        "\n".join(
            [
                "schema: draft-1",
                "key: documents_sent",
                "display_name: Documents sent",
                "section: Document Preparation",
                "description: Synthetic metric used for evidence export tests.",
                "define: |",
                "  COUNTROWS ( 'fact_documents' )",
                "variants:",
                "  manual:",
                "    display_name: Documents sent (manual)",
                "    calculate:",
                "      - \"'fact_documents'[IsManual] = TRUE()\"",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_run_pack_exports_evidence_for_selected_bindings(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    _write_test_metric(metrics_root)

    pack_path = tmp_path / "registry" / "customers" / "foo" / "pack.yaml"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text("{}", encoding="utf-8")

    visual_path = pack_path.parent / "visual.yaml"
    visual_path.write_text("type: dummy_evidence\n", encoding="utf-8")

    register_visual_bindings_adapter("dummy_evidence", _DummyEvidenceBindingsAdapter(), overwrite=True)

    def stub_visual_loader(path: Path):
        assert path == visual_path.resolve()
        from praeparo.models import BaseVisualConfig

        return BaseVisualConfig(type="dummy_evidence")

    pack = PackConfig(
        schema="test-pack",
        evidence=PackEvidenceConfig(enabled=True, bindings=PackEvidenceBindingsConfig(select=["sla"])),
        slides=[PackSlide(id="performance_dashboard", title="Performance", visual=PackVisualRef(ref="visual.yaml"))],
    )

    options = PipelineOptions(data=PipelineDataOptions(provider_key="mock"))

    output_root = tmp_path / "artefacts"
    env = create_pack_jinja_env()

    run_pack(
        pack_path,
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=options,
        pipeline=_StubPipeline(),  # type: ignore[arg-type]
        visual_loader=stub_visual_loader,
        env=env,
    )

    manifest_path = output_root / "_evidence" / "manifest.json"
    assert manifest_path.exists()

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(manifest, Mapping)
    bindings = manifest.get("bindings")
    assert isinstance(bindings, list)
    assert len(bindings) == 2
    for entry in bindings:
        paths = entry.get("paths")
        assert isinstance(paths, Mapping)

        evidence_path = Path(str(paths["evidence"]))
        evidence_flat_path = Path(str(paths["evidence_flat"]))

        assert evidence_path.name == "evidence.csv"
        assert evidence_path.exists()
        assert evidence_flat_path.exists()
        assert evidence_flat_path.name == f"{evidence_path.parent.name}.csv"
        assert evidence_flat_path.read_text(encoding="utf-8") == evidence_path.read_text(encoding="utf-8")

    # Re-run against the same artefact directory to confirm fingerprint-based skipping.
    run_pack(
        pack_path,
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=options,
        pipeline=_StubPipeline(),  # type: ignore[arg-type]
        visual_loader=stub_visual_loader,
        env=env,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bindings = manifest.get("bindings")
    assert isinstance(bindings, list)
    assert {entry.get("status") for entry in bindings} == {"skipped"}


def test_run_pack_evidence_reruns_when_metric_definition_changes(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    _write_test_metric(metrics_root)

    pack_path = tmp_path / "registry" / "customers" / "foo" / "pack.yaml"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text("{}", encoding="utf-8")

    visual_path = pack_path.parent / "visual.yaml"
    visual_path.write_text("type: dummy_evidence\n", encoding="utf-8")

    register_visual_bindings_adapter("dummy_evidence", _DummyEvidenceBindingsAdapter(), overwrite=True)

    def stub_visual_loader(path: Path):
        assert path == visual_path.resolve()
        from praeparo.models import BaseVisualConfig

        return BaseVisualConfig(type="dummy_evidence")

    pack = PackConfig(
        schema="test-pack",
        evidence=PackEvidenceConfig(enabled=True, bindings=PackEvidenceBindingsConfig(select=["sla"])),
        slides=[PackSlide(id="performance_dashboard", title="Performance", visual=PackVisualRef(ref="visual.yaml"))],
    )

    options = PipelineOptions(data=PipelineDataOptions(provider_key="mock"))
    output_root = tmp_path / "artefacts"
    env = create_pack_jinja_env()

    run_pack(
        pack_path,
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=options,
        pipeline=_StubPipeline(),  # type: ignore[arg-type]
        visual_loader=stub_visual_loader,
        env=env,
    )

    manifest_path = output_root / "_evidence" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bindings = manifest.get("bindings")
    assert isinstance(bindings, list)
    assert {entry.get("status") for entry in bindings} == {"success"}

    # Mutate the metric definition (simulates a downstream repo updating metric.calculate).
    metric_path = metrics_root / "documents_sent.yaml"
    metric_path.write_text(
        metric_path.read_text(encoding="utf-8")
        + "\n".join(
            [
                "calculate:",
                "  event_intelligence:",
                "    evaluate: |",
                "      'Event Intelligence'[Instance] = \"Latest\"",
                "",
            ]
        ),
        encoding="utf-8",
    )

    run_pack(
        pack_path,
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=options,
        pipeline=_StubPipeline(),  # type: ignore[arg-type]
        visual_loader=stub_visual_loader,
        env=env,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bindings = manifest.get("bindings")
    assert isinstance(bindings, list)
    assert {entry.get("status") for entry in bindings} == {"success"}


def test_run_pack_evidence_migrates_legacy_filename_and_rehydrates_flat_copy(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    _write_test_metric(metrics_root)

    pack_path = tmp_path / "registry" / "customers" / "foo" / "pack.yaml"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text("{}", encoding="utf-8")

    visual_path = pack_path.parent / "visual.yaml"
    visual_path.write_text("type: dummy_evidence\n", encoding="utf-8")

    register_visual_bindings_adapter("dummy_evidence", _DummyEvidenceBindingsAdapter(), overwrite=True)

    def stub_visual_loader(path: Path):
        assert path == visual_path.resolve()
        from praeparo.models import BaseVisualConfig

        return BaseVisualConfig(type="dummy_evidence")

    pack = PackConfig(
        schema="test-pack",
        evidence=PackEvidenceConfig(enabled=True, bindings=PackEvidenceBindingsConfig(select=["sla"])),
        slides=[PackSlide(id="performance_dashboard", title="Performance", visual=PackVisualRef(ref="visual.yaml"))],
    )

    options = PipelineOptions(data=PipelineDataOptions(provider_key="mock"))
    output_root = tmp_path / "artefacts"
    env = create_pack_jinja_env()

    run_pack(
        pack_path,
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=options,
        pipeline=_StubPipeline(),  # type: ignore[arg-type]
        visual_loader=stub_visual_loader,
        env=env,
    )

    manifest_path = output_root / "_evidence" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bindings = manifest.get("bindings")
    assert isinstance(bindings, list)
    assert bindings

    for entry in bindings:
        paths = entry.get("paths")
        assert isinstance(paths, Mapping)
        metric_slug = entry.get("metric_slug")
        assert isinstance(metric_slug, str)

        evidence_path = Path(str(paths["evidence"]))
        evidence_flat_path = Path(str(paths["evidence_flat"]))
        legacy_path = evidence_path.parent / f"evidence_{metric_slug}.csv"

        evidence_path.replace(legacy_path)
        if evidence_flat_path.exists():
            evidence_flat_path.unlink()

        assert legacy_path.exists()
        assert not evidence_path.exists()
        assert not evidence_flat_path.exists()

    run_pack(
        pack_path,
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=options,
        pipeline=_StubPipeline(),  # type: ignore[arg-type]
        visual_loader=stub_visual_loader,
        env=env,
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bindings = manifest.get("bindings")
    assert isinstance(bindings, list)
    assert {entry.get("status") for entry in bindings} == {"skipped"}

    for entry in bindings:
        paths = entry.get("paths")
        assert isinstance(paths, Mapping)
        metric_slug = entry.get("metric_slug")
        assert isinstance(metric_slug, str)

        evidence_path = Path(str(paths["evidence"]))
        evidence_flat_path = Path(str(paths["evidence_flat"]))
        legacy_path = evidence_path.parent / f"evidence_{metric_slug}.csv"

        assert evidence_path.exists()
        assert not legacy_path.exists()
        assert evidence_flat_path.exists()


def test_pack_evidence_exports_include_registry_month_scoping(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    _write_test_metric(metrics_root)

    context_root = tmp_path / "registry" / "context"
    context_root.mkdir(parents=True, exist_ok=True)
    (context_root / "month.yaml").write_text(
        "\n".join(
            [
                "context:",
                "  month: \"2025-12-01\"",
                "",
            ]
        ),
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
                "",
            ]
        ),
        encoding="utf-8",
    )

    pack_path = tmp_path / "registry" / "customers" / "foo" / "pack.yaml"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text("{}", encoding="utf-8")

    visual_path = pack_path.parent / "visual.yaml"
    visual_path.write_text("type: dummy_evidence\n", encoding="utf-8")

    register_visual_bindings_adapter("dummy_evidence", _DummyEvidenceBindingsAdapter(), overwrite=True)

    def stub_visual_loader(path: Path):
        assert path == visual_path.resolve()
        from praeparo.models import BaseVisualConfig

        return BaseVisualConfig(type="dummy_evidence")

    pack = PackConfig(
        schema="test-pack",
        evidence=PackEvidenceConfig(enabled=True, bindings=PackEvidenceBindingsConfig(select=["sla"])),
        slides=[PackSlide(id="performance_dashboard", title="Performance", visual=PackVisualRef(ref="visual.yaml"))],
    )

    options = PipelineOptions(data=PipelineDataOptions(provider_key="mock"))
    output_root = tmp_path / "artefacts"
    env = create_pack_jinja_env()

    run_pack(
        pack_path,
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=options,
        pipeline=_StubPipeline(),  # type: ignore[arg-type]
        visual_loader=stub_visual_loader,
        env=env,
        evidence_only=True,
    )

    manifest_path = output_root / "_evidence" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    bindings = manifest.get("bindings")
    assert isinstance(bindings, list)
    assert bindings

    dax_path = Path(bindings[0]["paths"]["dax"])
    dax_text = dax_path.read_text(encoding="utf-8")
    assert "2025-12-01" in dax_text
    assert "dim_calendar" in dax_text


class _FailingPipeline:
    def execute(self, visual, context):  # noqa: ANN001
        raise AssertionError("Pipeline.execute should not run during --evidence-only pack runs.")


def test_run_pack_evidence_only_skips_visual_execution(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    _write_test_metric(metrics_root)

    pack_path = tmp_path / "registry" / "customers" / "foo" / "pack.yaml"
    pack_path.parent.mkdir(parents=True, exist_ok=True)
    pack_path.write_text("{}", encoding="utf-8")

    visual_path = pack_path.parent / "visual.yaml"
    visual_path.write_text("type: dummy_evidence\n", encoding="utf-8")

    register_visual_bindings_adapter("dummy_evidence", _DummyEvidenceBindingsAdapter(), overwrite=True)

    def stub_visual_loader(path: Path):
        assert path == visual_path.resolve()
        from praeparo.models import BaseVisualConfig

        return BaseVisualConfig(type="dummy_evidence")

    pack = PackConfig(
        schema="test-pack",
        evidence=PackEvidenceConfig(enabled=True, bindings=PackEvidenceBindingsConfig(select=["sla"])),
        slides=[PackSlide(id="performance_dashboard", title="Performance", visual=PackVisualRef(ref="visual.yaml"))],
    )

    options = PipelineOptions(data=PipelineDataOptions(provider_key="mock"))
    output_root = tmp_path / "artefacts"
    env = create_pack_jinja_env()

    results = run_pack(
        pack_path,
        pack,
        project_root=tmp_path,
        output_root=output_root,
        base_options=options,
        pipeline=_FailingPipeline(),  # type: ignore[arg-type]
        visual_loader=stub_visual_loader,
        env=env,
        evidence_only=True,
    )

    assert results == []
    assert (output_root / "_evidence" / "manifest.json").exists()
