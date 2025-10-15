"""Tests for Praeparo metric catalog discovery."""

from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.metrics import (
    MetricDiscoveryError,
    discover_metric_files,
    load_metric_catalog,
)


def _write_metric(path: Path, key: str, display_name: str = "Metric", section: str = "Section", variants: str = "") -> None:
    payload = f"""schema: draft-1
key: {key}
display_name: {display_name}
section: {section}
"""
    if variants:
        payload += variants
    path.write_text(payload, encoding="utf-8")


def test_load_metric_catalog_parses_metrics_and_variants(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()

    _write_metric(
        metrics_dir / "documents_sent.yaml",
        key="documents_sent",
        variants="""variants:
  automated:
    display_name: Automated
    calculate:
      - fact_events.IsAutomated = TRUE()
""",
    )

    _write_metric(metrics_dir / "lodgement.yaml", key="lodgement_complete")

    catalog = load_metric_catalog([metrics_dir])

    assert catalog.metric_keys() == {"documents_sent", "lodgement_complete"}
    assert catalog.contains("documents_sent")
    assert catalog.contains("documents_sent.automated")
    assert not catalog.contains("documents_sent.missing_variant")
    assert catalog.get_variant("documents_sent.automated") is not None
    assert catalog.has_variant("documents_sent", "automated")
    assert catalog.has_variant("documents_sent", "documents_sent.automated")


def test_load_metric_catalog_detects_duplicate_keys(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()

    _write_metric(metrics_dir / "documents.yaml", key="documents_sent")
    _write_metric(metrics_dir / "documents_copy.yaml", key="documents_sent")

    with pytest.raises(MetricDiscoveryError) as excinfo:
        load_metric_catalog([metrics_dir])

    err = excinfo.value
    assert any("duplicate metric key" in message for message in err.errors)
    assert err.catalog is not None
    assert err.catalog.contains("documents_sent")


def test_load_metric_catalog_reports_missing_extends(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()

    _write_metric(metrics_dir / "base.yaml", key="documents_sent")
    _write_metric(
        metrics_dir / "child.yaml",
        key="documents_sent_child",
        variants="extends: documents_sent_missing\n",
    )

    with pytest.raises(MetricDiscoveryError) as excinfo:
        load_metric_catalog([metrics_dir])

    err = excinfo.value
    assert any("extends 'documents_sent_missing' not found" in message for message in err.errors)


def test_discover_metric_files_rejects_non_yaml_file(tmp_path: Path) -> None:
    metrics_dir = tmp_path / "metrics"
    metrics_dir.mkdir()
    bad_file = metrics_dir / "notes.txt"
    bad_file.write_text("not yaml", encoding="utf-8")

    with pytest.raises(ValueError):
        discover_metric_files([bad_file])

