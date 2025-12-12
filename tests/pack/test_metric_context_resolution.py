from __future__ import annotations

from pathlib import Path
import asyncio
import json

import pytest

from praeparo.datasets import MetricDatasetBuilderContext
from praeparo.metrics import load_metric_catalog
from praeparo.models import PackMetricBinding
from praeparo.pack.metric_context import ResolvedMetricContext, resolve_metric_context
from praeparo.pack.templating import create_pack_jinja_env


def _empty_context(tmp_path: Path):
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True, exist_ok=True)
    builder_context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        use_mock=True,
    )
    catalog = load_metric_catalog([metrics_root])
    env = create_pack_jinja_env()
    return builder_context, catalog, env


def test_resolve_metric_context_runs_inside_active_event_loop(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_sent.yaml").write_text(
        """
key: documents_sent
display_name: Documents Sent
section: documents
define: "COUNTROWS('fact_documents')"
""",
        encoding="utf-8",
    )

    builder_context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        use_mock=True,
    )
    catalog = load_metric_catalog([metrics_root])
    env = create_pack_jinja_env()

    bindings = [PackMetricBinding(key="documents_sent", alias="total_documents")]

    async def _runner() -> None:
        resolved = resolve_metric_context(
            bindings=bindings,
            inherited=None,
            builder_context=builder_context,
            catalog=catalog,
            env=env,
            base_payload={},
            scope="root",
        )
        assert "total_documents" in resolved.aliases

    asyncio.run(_runner())


def test_expression_evaluated_in_dependency_order(tmp_path: Path) -> None:
    builder_context, catalog, env = _empty_context(tmp_path)
    inherited = ResolvedMetricContext(aliases={"a": 2.0}, by_key={}, signatures_by_key={}, formats_by_alias={})

    bindings = [
        PackMetricBinding(alias="b", expression="a * 3"),
        PackMetricBinding(alias="c", expression="b + 1"),
    ]

    resolved = resolve_metric_context(
        bindings=bindings,
        inherited=inherited,
        builder_context=builder_context,
        catalog=catalog,
        env=env,
        base_payload={},
        scope="root",
    )

    assert resolved.aliases["b"] == 6.0
    assert resolved.aliases["c"] == 7.0


def test_expression_cycle_raises(tmp_path: Path) -> None:
    builder_context, catalog, env = _empty_context(tmp_path)

    bindings = [
        PackMetricBinding(alias="a", expression="b + 1"),
        PackMetricBinding(alias="b", expression="a + 1"),
    ]

    with pytest.raises(ValueError, match="cyclic"):
        resolve_metric_context(
            bindings=bindings,
            inherited=None,
            builder_context=builder_context,
            catalog=catalog,
            env=env,
            base_payload={},
            scope="root",
        )


def test_expression_missing_identifier_raises(tmp_path: Path) -> None:
    builder_context, catalog, env = _empty_context(tmp_path)
    bindings = [PackMetricBinding(alias="a", expression="missing + 1")]

    with pytest.raises(ValueError, match="unknown identifier"):
        resolve_metric_context(
            bindings=bindings,
            inherited=None,
            builder_context=builder_context,
            catalog=catalog,
            env=env,
            base_payload={},
            scope="root",
        )


def test_unknown_metric_key_raises_before_query(tmp_path: Path) -> None:
    builder_context, catalog, env = _empty_context(tmp_path)
    bindings = [PackMetricBinding(key="unknown_metric", alias="unknown_metric")]

    with pytest.raises(ValueError, match="unknown metric key"):
        resolve_metric_context(
            bindings=bindings,
            inherited=None,
            builder_context=builder_context,
            catalog=catalog,
            env=env,
            base_payload={},
            scope="root",
        )


def test_metric_context_emits_data_artifact(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_sent.yaml").write_text(
        """
key: documents_sent
display_name: Documents Sent
section: documents
define: "COUNTROWS('fact_documents')"
""",
        encoding="utf-8",
    )

    builder_context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        use_mock=True,
    )
    catalog = load_metric_catalog([metrics_root])
    env = create_pack_jinja_env()

    bindings = [PackMetricBinding(key="documents_sent", alias="total_documents")]
    artefact_dir = tmp_path / "artefacts"

    resolve_metric_context(
        bindings=bindings,
        inherited=None,
        builder_context=builder_context,
        catalog=catalog,
        env=env,
        base_payload={},
        scope="root",
        artefact_dir=artefact_dir,
    )

    data_path = artefact_dir / "metric_context.root.data.json"
    assert data_path.exists()
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    assert isinstance(payload, list)
    assert len(payload) == 1
    assert "total_documents" in payload[0]


def test_metrics_calculate_included_in_dax_artifact(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_sent.yaml").write_text(
        """
key: documents_sent
display_name: Documents Sent
section: documents
define: "COUNTROWS('fact_documents')"
""",
        encoding="utf-8",
    )

    builder_context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        use_mock=True,
    )
    catalog = load_metric_catalog([metrics_root])
    env = create_pack_jinja_env()

    bindings = [PackMetricBinding(key="documents_sent", alias="total_documents")]
    artefact_dir = tmp_path / "artefacts"
    month_filter = "'dim_calendar'[month] = DATEVALUE(\"2025-11-01\")"

    resolve_metric_context(
        bindings=bindings,
        inherited=None,
        builder_context=builder_context,
        catalog=catalog,
        env=env,
        base_payload={},
        scope="root",
        metrics_calculate={"month": month_filter},
        artefact_dir=artefact_dir,
    )

    dax_path = artefact_dir / "metric_context.root.dax"
    assert dax_path.exists()
    assert month_filter in dax_path.read_text(encoding="utf-8")


def test_metrics_calculate_mismatch_disables_reuse(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_sent.yaml").write_text(
        """
key: documents_sent
display_name: Documents Sent
section: documents
define: "COUNTROWS('fact_documents')"
""",
        encoding="utf-8",
    )

    builder_context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        use_mock=True,
    )
    catalog = load_metric_catalog([metrics_root])
    env = create_pack_jinja_env()

    binding = PackMetricBinding(key="documents_sent", alias="total_documents")
    inherited = ResolvedMetricContext(
        aliases={"total_documents": 7.0},
        by_key={"documents_sent": 7.0},
        signatures_by_key={"documents_sent": binding.signature() + (tuple(),)},
        formats_by_alias={},
    )

    artefact_dir = tmp_path / "artefacts"
    resolve_metric_context(
        bindings=[binding],
        inherited=inherited,
        builder_context=builder_context,
        catalog=catalog,
        env=env,
        base_payload={},
        scope="slide_1",
        metrics_calculate=["'dim_calendar'[month] = DATEVALUE(\"2025-11-01\")"],
        artefact_dir=artefact_dir,
    )

    dax_path = artefact_dir / "metric_context.slide_1.dax"
    assert dax_path.exists()


def test_binding_evaluate_filters_emit_in_evaluate_section(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_sent.yaml").write_text(
        """
key: documents_sent
display_name: Documents Sent
section: documents
define: "COUNTROWS('fact_documents')"
""",
        encoding="utf-8",
    )

    builder_context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        use_mock=True,
    )
    catalog = load_metric_catalog([metrics_root])
    env = create_pack_jinja_env()

    binding = PackMetricBinding.model_validate(
        {
            "key": "documents_sent",
            "alias": "total_documents",
            "calculate": {
                "period": {
                    "evaluate": "'Time Intelligence'[Period] = \"Current Month\"",
                }
            },
        }
    )
    artefact_dir = tmp_path / "artefacts"

    resolve_metric_context(
        bindings=[binding],
        inherited=None,
        builder_context=builder_context,
        catalog=catalog,
        env=env,
        base_payload={},
        scope="root",
        artefact_dir=artefact_dir,
    )

    dax_text = (artefact_dir / "metric_context.root.dax").read_text(encoding="utf-8")
    before_eval, after_eval = dax_text.split("EVALUATE", 1)
    assert "Time Intelligence" not in before_eval
    assert "Time Intelligence" in after_eval


def test_ratio_to_adds_denominator_and_resolves_scalar(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_verified.yaml").write_text(
        """
key: documents_verified
display_name: Documents Verified
section: documents
define: "COUNTROWS('fact_documents')"
variants:
  within_1_day:
    display_name: Within 1 day
    calculate:
      - "TRUE()"
""",
        encoding="utf-8",
    )

    builder_context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        use_mock=True,
    )
    catalog = load_metric_catalog([metrics_root])
    env = create_pack_jinja_env()

    binding = PackMetricBinding.model_validate(
        {
            "key": "documents_verified",
            "variant": "within_1_day",
            "alias": "pct_verified_1d",
            "ratio_to": True,
        }
    )

    resolved = resolve_metric_context(
        bindings=[binding],
        inherited=None,
        builder_context=builder_context,
        catalog=catalog,
        env=env,
        base_payload={},
        scope="root",
    )

    assert resolved.aliases["pct_verified_1d"] == pytest.approx(1.0)


def test_ratio_to_evaluate_applies_to_denominator_define_does_not(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_verified.yaml").write_text(
        """
key: documents_verified
display_name: Documents Verified
section: documents
define: "COUNTROWS('fact_documents')"
variants:
  within_1_day:
    display_name: Within 1 day
    calculate:
      - "TRUE()"
""",
        encoding="utf-8",
    )

    builder_context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        use_mock=True,
    )
    catalog = load_metric_catalog([metrics_root])
    env = create_pack_jinja_env()

    define_filter = "fact_documents[DummyDefine] = 1"
    evaluate_filter = "'Time Intelligence'[Period] = \"Current Month\""
    binding = PackMetricBinding.model_validate(
        {
            "key": "documents_verified.within_1_day",
            "alias": "pct_verified_1d",
            "ratio_to": True,
            "calculate": {
                "define_only": define_filter,
                "period": {"evaluate": evaluate_filter},
            },
        }
    )

    artefact_dir = tmp_path / "artefacts"
    resolve_metric_context(
        bindings=[binding],
        inherited=None,
        builder_context=builder_context,
        catalog=catalog,
        env=env,
        base_payload={},
        scope="root",
        artefact_dir=artefact_dir,
    )

    dax_text = (artefact_dir / "metric_context.root.dax").read_text(encoding="utf-8")
    before_eval, after_eval = dax_text.split("EVALUATE", 1)

    assert evaluate_filter not in before_eval
    assert after_eval.count(evaluate_filter) == 2
    assert dax_text.count(define_filter) == 1


def test_ratio_to_unknown_denominator_raises_friendly_error(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_verified.yaml").write_text(
        """
key: documents_verified
display_name: Documents Verified
section: documents
define: "COUNTROWS('fact_documents')"
variants:
  within_1_day:
    display_name: Within 1 day
    calculate:
      - "TRUE()"
""",
        encoding="utf-8",
    )

    builder_context = MetricDatasetBuilderContext.discover(
        project_root=tmp_path,
        metrics_root=metrics_root,
        use_mock=True,
    )
    catalog = load_metric_catalog([metrics_root])
    env = create_pack_jinja_env()

    binding = PackMetricBinding.model_validate(
        {
            "key": "documents_verified.within_1_day",
            "alias": "pct_verified_1d",
            "ratio_to": "missing_metric",
        }
    )

    with pytest.raises(ValueError, match="root context\\.metrics binding 'pct_verified_1d'.*missing_metric"):
        resolve_metric_context(
            bindings=[binding],
            inherited=None,
            builder_context=builder_context,
            catalog=catalog,
            env=env,
            base_payload={},
            scope="root",
        )
