from __future__ import annotations

from pathlib import Path
from typing import Sequence

import pytest

from praeparo.datasets import MetricDatasetBuilder, MetricDatasetBuilderContext


def _write_metric(path: Path, variants: Sequence[str] = ()) -> None:
    lines: list[str] = [
        "schema: draft-1",
        "key: documents_sent",
        "display_name: Documents sent",
        "section: Document Preparation",
        'define: "COUNTROWS ( \'fact_documents\' )"',
    ]

    if variants:
        lines.append("variants:")
        for variant in variants:
            lines.extend(
                [
                    f"  {variant}:",
                    f"    display_name: {variant}",
                    "    calculate:",
                    '      - "TRUE()"',
                ]
            )

    path.write_text("\n".join(lines), encoding="utf-8")


def _builder(tmp_path: Path, variants: Sequence[str] = ()) -> MetricDatasetBuilder:
    metrics_root = tmp_path / "metrics"
    metrics_root.mkdir()
    _write_metric(metrics_root / "documents_sent.yaml", variants)
    context = MetricDatasetBuilderContext.discover(project_root=tmp_path, metrics_root=metrics_root)
    return MetricDatasetBuilder(context)


def test_ratio_to_infers_base_and_sets_percent(tmp_path: Path) -> None:
    builder = _builder(tmp_path, variants=["variant"])
    builder.metric("documents_sent", alias="base")
    builder.metric("documents_sent.variant", alias="ratio_series", ratio_to=True)

    plan = builder.plan()

    raw = [
        {
            plan.measure_map["base"]: 200,
            plan.measure_map["ratio_series"]: 50,
            "'dim_calendar'[Month]": "Jan-25",
        }
    ]

    rows = builder._normalise_rows(raw, plan)

    assert rows[0]["ratio_series"] == pytest.approx(0.25)
    ratio_series = next(series for series in builder._series if series.series_id == "ratio_series")
    assert ratio_series.value_type == "percent"


def test_ratio_to_explicit_denominator(tmp_path: Path) -> None:
    builder = _builder(tmp_path, variants=["within_1d"])
    builder.metric("documents_sent", alias="docs")
    builder.metric("documents_sent.within_1d", alias="in_1d_raw")
    builder.metric("documents_sent.within_1d", alias="pct_in_1d", ratio_to="documents_sent")

    plan = builder.plan()

    raw = [
        {
            plan.measure_map["docs"]: 200,
            plan.measure_map["in_1d_raw"]: 100,
            plan.measure_map["pct_in_1d"]: 100,
        }
    ]

    rows = builder._normalise_rows(raw, plan)

    assert rows[0]["pct_in_1d"] == pytest.approx(0.5)


def test_ratio_to_preserves_explicit_value_type_override(tmp_path: Path) -> None:
    builder = _builder(tmp_path, variants=["variant"])
    builder.metric("documents_sent", alias="base")
    builder.metric("documents_sent.variant", alias="ratio_series", ratio_to=True, value_type="number")

    plan = builder.plan()

    raw = [
        {
            plan.measure_map["base"]: 50,
            plan.measure_map["ratio_series"]: 25,
        }
    ]

    rows = builder._normalise_rows(raw, plan)

    ratio_series = next(series for series in builder._series if series.series_id == "ratio_series")
    assert ratio_series.value_type == "number"
    assert rows[0]["ratio_series"] == pytest.approx(0.5)


def test_ratio_to_requires_denominator_present(tmp_path: Path) -> None:
    builder = _builder(tmp_path, variants=["variant"])
    builder.metric("documents_sent.variant", alias="ratio_series", ratio_to="documents_sent")

    with pytest.raises(ValueError):
        builder.plan()


def test_ratio_to_true_requires_dotted_metric(tmp_path: Path) -> None:
    builder = _builder(tmp_path)

    with pytest.raises(ValueError):
        builder.metric("documents_sent", ratio_to=True)
