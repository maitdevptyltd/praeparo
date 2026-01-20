from __future__ import annotations

from pathlib import Path

from praeparo.metrics.cli import run


def _write_metric(metrics_root: Path) -> None:
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_sent.yaml").write_text(
        "\n".join(
            [
                "schema: draft-1",
                "key: documents_sent",
                "display_name: Documents sent",
                "section: Document Preparation",
                "define: \"DISTINCTCOUNT ( 'fact_events'[MatterId] )\"",
                "calculate:",
                "  - dim_event_type.MatterEventTypeName = \"Milestone Complete\"",
            ]
        ),
        encoding="utf-8",
    )


def _write_context(context_root: Path) -> None:
    context_root.mkdir(parents=True, exist_ok=True)
    (context_root / "month.yaml").write_text(
        "\n".join(["context:", '  month: "2025-12-01"']),
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
        ),
        encoding="utf-8",
    )


def test_explain_plan_only_writes_dax_without_evidence(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    context_root = tmp_path / "registry" / "context"
    _write_metric(metrics_root)
    _write_context(context_root)

    dest = tmp_path / "out"
    code = run(
        [
            "explain",
            "documents_sent",
            str(dest),
            "--metrics-root",
            str(metrics_root),
            "--plan-only",
        ]
    )
    assert code == 0

    dax_path = dest / "_artifacts" / "explain.dax"
    summary_path = dest / "_artifacts" / "summary.json"
    evidence_path = dest / "evidence.csv"

    assert dax_path.exists()
    assert summary_path.exists()
    assert not evidence_path.exists()

    dax = dax_path.read_text(encoding="utf-8")
    assert "TOPN(" in dax
    assert "DATEVALUE(\"2025-12-01\")" in dax

