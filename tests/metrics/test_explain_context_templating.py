from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.pack.templating import create_pack_jinja_env, render_value
from praeparo.models.scoped_calculate import ScopedCalculateMap
from praeparo.visuals.context import resolve_dax_context
from praeparo.visuals.context_layers import resolve_layered_context_payload


def test_explain_context_renders_metrics_calculate_templates(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    (tmp_path / "registry" / "context").mkdir(parents=True)
    (tmp_path / "registry" / "context" / "month.yaml").write_text(
        "\n".join(["context:", '  month: "2025-12-01"']),
        encoding="utf-8",
    )
    (tmp_path / "registry" / "context" / "metrics.yaml").write_text(
        "\n".join(
            [
                "context:",
                "  metrics:",
                "    calculate:",
                "      month: |",
                "        'dim_calendar'[month] = DATEVALUE(\"{{ month }}\")",
            ]
        ),
        encoding="utf-8",
    )

    env = create_pack_jinja_env()
    payload = resolve_layered_context_payload(metrics_root=metrics_root, env=env)

    raw_metrics = payload.get("metrics")
    assert isinstance(raw_metrics, dict)
    raw_calculate = raw_metrics.get("calculate")
    rendered = render_value(raw_calculate, env=env, context=payload)

    scoped = ScopedCalculateMap.from_raw(rendered)
    calculate_filters, _ = resolve_dax_context(base=payload, calculate=scoped.flatten_define())
    assert any("DATEVALUE" in entry for entry in calculate_filters)


def test_explain_context_rejects_unrendered_metrics_calculate_templates(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    (tmp_path / "registry" / "context").mkdir(parents=True)
    (tmp_path / "registry" / "context" / "metrics.yaml").write_text(
        "\n".join(
            [
                "context:",
                "  metrics:",
                "    calculate:",
                "      month: |",
                "        'dim_calendar'[month] = DATEVALUE(\"{{ month }}\")",
            ]
        ),
        encoding="utf-8",
    )

    env = create_pack_jinja_env()
    payload = resolve_layered_context_payload(metrics_root=metrics_root, env=env)

    raw_metrics = payload.get("metrics")
    assert isinstance(raw_metrics, dict)
    raw_calculate = raw_metrics.get("calculate")
    rendered = render_value(raw_calculate, env=env, context=payload)

    scoped = ScopedCalculateMap.from_raw(rendered)
    calculate_filters, _ = resolve_dax_context(base=payload, calculate=scoped.flatten_define())
    assert all("{{" not in entry and "}}" not in entry for entry in calculate_filters)
