"""Tests covering metric inheritance validation."""

from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.inheritance import validate_extends_graph
from praeparo.metrics import MetricDefinition


def _metric_payload(key: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "key": key,
        "display_name": key.replace("_", " ").title(),
        "section": "Test",
        "calculate": [],
    }
    payload.update(overrides)
    return payload


def _make_metric(key: str, **overrides: object) -> MetricDefinition:
    return MetricDefinition.model_validate(_metric_payload(key, **overrides))


def test_validate_extends_graph_success() -> None:
    parent = _make_metric("parent")
    child = _make_metric("child", extends="parent")

    registry = {"parent": parent, "child": child}
    sources = {key: Path(f"{key}.yaml") for key in registry}

    errors = validate_extends_graph(registry, sources, get_parent=lambda m: m.extends)

    assert errors == []


def test_validate_extends_graph_missing_parent() -> None:
    child = _make_metric("child", extends="missing")
    registry = {"child": child}
    sources = {"child": Path("child.yaml")}

    errors = validate_extends_graph(registry, sources, get_parent=lambda m: m.extends)

    assert len(errors) == 1
    assert "extends 'missing' not found" in errors[0]


def test_validate_extends_graph_cycle() -> None:
    parent = _make_metric("parent", extends="child")
    child = _make_metric("child", extends="parent")
    registry = {"parent": parent, "child": child}
    sources = {key: Path(f"{key}.yaml") for key in registry}

    errors = validate_extends_graph(registry, sources, get_parent=lambda m: m.extends)

    assert len(errors) == 1
    assert "inheritance cycle" in errors[0]
