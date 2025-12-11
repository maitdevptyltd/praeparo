from __future__ import annotations

from pathlib import Path

from praeparo.models import BaseVisualConfig, PackSlide
from praeparo.pack.pbi_queue import PowerBIExportJob, PowerBIExportResult
from praeparo.pack.runner import _format_powerbi_failure_summary
from praeparo.pipeline import ExecutionContext, PipelineOptions
from praeparo.pipeline.outputs import OutputTarget


def _build_job(tmp_path: Path) -> PowerBIExportJob:
    options = PipelineOptions(outputs=[OutputTarget.png(tmp_path / "slide.png")])
    context = ExecutionContext(
        config_path=tmp_path / "visual.yaml",
        project_root=tmp_path,
        case_key="discharges_dashboard",
        options=options,
    )
    return PowerBIExportJob(
        slide_index=1,
        slide_slug="discharges_dashboard",
        slide_title="Discharges Dashboard",
        slide=PackSlide(title="Discharges Dashboard", visual=None),
        visual=BaseVisualConfig(type="powerbi"),
        visual_path=tmp_path / "visual.yaml",
        execution_context=context,
    )


def test_failure_summary_includes_slug_title_type_and_message(tmp_path: Path) -> None:
    job = _build_job(tmp_path)
    exc = RuntimeError("DAX error: Token Eof expected near '!='")
    result = PowerBIExportResult(job=job, result=None, exception=exc, duration_seconds=0.1)

    summary = _format_powerbi_failure_summary([result])

    assert "1 Power BI slide(s) failed" in summary
    assert "discharges_dashboard" in summary
    assert "Discharges Dashboard" in summary
    assert "RuntimeError" in summary
    assert "DAX error: Token Eof expected near '!='" in summary
    assert "--max-pbi-concurrency 1" in summary
    assert "Hint:" in summary
