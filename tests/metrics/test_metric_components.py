from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.metrics import MetricDaxBuilder, load_metric_catalog
from praeparo.metrics.components import MetricComponentError, resolve_component_path
from praeparo.metrics.explain import build_metric_explain_plan, resolve_metric_explain_spec


def test_resolve_component_path_anchors_registry_metrics(tmp_path: Path) -> None:
    declaring = tmp_path / "registry" / "metrics" / "domain" / "metric.yaml"
    declaring.parent.mkdir(parents=True)
    declaring.write_text("schema: draft-1\nkey: metric\nsection: Test\ndisplay_name: Metric\ndefine: 1\n", encoding="utf-8")

    component = tmp_path / "registry" / "components" / "explain" / "default_event.yaml"
    component.parent.mkdir(parents=True)
    component.write_text("schema: component-draft-1\nexplain: {select: {matter_id: fact_events[MatterId]}}\n", encoding="utf-8")

    resolved = resolve_component_path("@/registry/components/explain/default_event.yaml", declaring_file=declaring)
    assert resolved == component.resolve()


def test_resolve_component_path_anchors_metrics_root(tmp_path: Path) -> None:
    declaring = tmp_path / "metrics" / "metric.yaml"
    declaring.parent.mkdir(parents=True)
    declaring.write_text("schema: draft-1\nkey: metric\nsection: Test\ndisplay_name: Metric\ndefine: 1\n", encoding="utf-8")

    component = tmp_path / "registry" / "components" / "explain" / "default_event.yaml"
    component.parent.mkdir(parents=True)
    component.write_text("schema: component-draft-1\nexplain: {select: {matter_id: fact_events[MatterId]}}\n", encoding="utf-8")

    resolved = resolve_component_path("@/registry/components/explain/default_event.yaml", declaring_file=declaring)
    assert resolved == component.resolve()


def test_resolve_component_path_supports_relative_refs(tmp_path: Path) -> None:
    declaring = tmp_path / "registry" / "metrics" / "domain" / "metric.yaml"
    declaring.parent.mkdir(parents=True)
    declaring.write_text("schema: draft-1\nkey: metric\nsection: Test\ndisplay_name: Metric\ndefine: 1\n", encoding="utf-8")

    component = tmp_path / "registry" / "components" / "explain" / "default_event.yaml"
    component.parent.mkdir(parents=True)
    component.write_text("schema: component-draft-1\nexplain: {select: {matter_id: fact_events[MatterId]}}\n", encoding="utf-8")

    resolved = resolve_component_path("../../components/explain/default_event.yaml", declaring_file=declaring)
    assert resolved == component.resolve()


def test_explain_plan_merges_component_select_and_define(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    components_root = tmp_path / "registry" / "components" / "explain"
    metrics_root.mkdir(parents=True)
    components_root.mkdir(parents=True)

    (components_root / "default_event.yaml").write_text(
        "\n".join(
            [
                "schema: component-draft-1",
                "explain:",
                "  define:",
                "    __latest_event_key: |",
                "      MEASURE 'adhoc'[__latest_event_key] = 1",
                "  select:",
                "    matter_id: fact_events[MatterId]",
            ]
        ),
        encoding="utf-8",
    )

    (metrics_root / "documents_verified.yaml").write_text(
        "\n".join(
            [
                "schema: draft-1",
                "key: documents_verified",
                "display_name: Documents verified",
                "section: Document Verification",
                "define: \"1\"",
                "compose:",
                "  - \"@/registry/components/explain/default_event.yaml\"",
                "explain:",
                "  select:",
                "    event_timestamp_utc: fact_events[EventTimestampUTC]",
            ]
        ),
        encoding="utf-8",
    )

    catalog = load_metric_catalog([metrics_root])

    plan = build_metric_explain_plan(catalog, metric_identifier="documents_verified", limit=10)
    assert "__latest_event_key" in plan.statement
    assert "\"matter_id\"" in plan.statement
    assert "\"event_timestamp_utc\"" in plan.statement

    compiled = MetricDaxBuilder(catalog).compile_metric("documents_verified")
    assert "__latest_event_key" not in compiled.base.expression


def test_missing_component_reference_includes_declaring_file(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    metric_path = metrics_root / "documents_verified.yaml"
    metric_path.write_text(
        "\n".join(
            [
                "schema: draft-1",
                "key: documents_verified",
                "display_name: Documents verified",
                "section: Document Verification",
                "define: \"1\"",
                "compose:",
                "  - \"@/registry/components/explain/missing.yaml\"",
            ]
        ),
        encoding="utf-8",
    )

    catalog = load_metric_catalog([metrics_root])

    with pytest.raises(MetricComponentError) as excinfo:
        resolve_metric_explain_spec(catalog, metric_key="documents_verified", variant_path=None)

    message = str(excinfo.value)
    assert str(metric_path) in message
    assert "missing.yaml" in message
