"""Concurrent Power BI export queue used by pack runs."""

from __future__ import annotations

import concurrent.futures
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List

from praeparo.models import BaseVisualConfig, PackSlide
from praeparo.pipeline import ExecutionContext, VisualExecutionResult, VisualPipeline
from praeparo.pipeline.outputs import OutputKind

logger = logging.getLogger(__name__)


@dataclass
class PowerBIExportJob:
    """Work item representing a single Power BI export."""

    slide_index: int
    slide_slug: str
    slide_title: str | None
    slide: PackSlide
    visual: BaseVisualConfig
    visual_path: Path
    execution_context: ExecutionContext


@dataclass
class PowerBIExportResult:
    """Outcome for a Power BI export job."""

    job: PowerBIExportJob
    result: VisualExecutionResult | None
    exception: BaseException | None
    duration_seconds: float

    @property
    def succeeded(self) -> bool:
        return self.exception is None


class PowerBIExportQueue:
    """Bounded thread pool that executes Power BI export jobs concurrently."""

    def __init__(self, pipeline: VisualPipeline, *, max_concurrent_exports: int) -> None:
        if max_concurrent_exports < 1:
            raise ValueError("max_concurrent_exports must be at least 1")
        self._pipeline = pipeline
        self._executor = concurrent.futures.ThreadPoolExecutor(
            max_workers=max_concurrent_exports,
            thread_name_prefix="powerbi-export",
        )
        self._futures: list[concurrent.futures.Future[PowerBIExportResult]] = []
        logger.info(
            "Initialised Power BI export queue (max_concurrent_exports=%s)",
            max_concurrent_exports,
            extra={"max_concurrent_exports": max_concurrent_exports},
        )

    def enqueue(self, job: PowerBIExportJob) -> None:
        logger.info(
            "Queued Power BI export slide=%s title=%r visual=%s",
            job.slide_slug,
            job.slide_title,
            job.visual_path,
            extra={
                "slide": job.slide_slug,
                "title": job.slide_title,
                "visual_path": str(job.visual_path),
            },
        )
        future = self._executor.submit(self._run_job, job)
        self._futures.append(future)

    def drain(self) -> List[PowerBIExportResult]:
        """Wait for all queued jobs to finish and return their results."""

        results: list[PowerBIExportResult] = []
        for future in concurrent.futures.as_completed(self._futures):
            results.append(future.result())

        self._executor.shutdown(wait=True)

        success_count = sum(1 for item in results if item.succeeded)
        failure_count = len(results) - success_count
        logger.info(
            "Power BI export queue drained (success=%s, failed=%s, total=%s)",
            success_count,
            failure_count,
            len(results),
            extra={"success_count": success_count, "failure_count": failure_count},
        )
        # Preserve original slide order for downstream callers.
        return sorted(results, key=lambda item: item.job.slide_index)

    def _run_job(self, job: PowerBIExportJob) -> PowerBIExportResult:
        start = time.perf_counter()
        metadata = job.execution_context.options.metadata or {}
        filters = metadata.get("powerbi_filters")
        png_targets = [
            str(target.path)
            for target in job.execution_context.options.outputs
            if target.kind is OutputKind.PNG
        ]

        logger.info(
            "Starting Power BI export slide=%s title=%r visual=%s target=%s filters=%s",
            job.slide_slug,
            job.slide_title,
            job.visual_path,
            ", ".join(png_targets) if png_targets else "-",
            len(filters) if isinstance(filters, (list, dict)) else 0,
            extra={
                "slide": job.slide_slug,
                "title": job.slide_title,
                "visual_path": str(job.visual_path),
                "png_targets": png_targets,
                "filter_keys": sorted(filters.keys()) if isinstance(filters, dict) else None,
                "filter_count": len(filters) if isinstance(filters, (list, dict)) else None,
            },
        )

        try:
            result = self._pipeline.execute(job.visual, job.execution_context)
            duration = time.perf_counter() - start
            logger.info(
                "Power BI export completed slide=%s duration_ms=%s target=%s",
                job.slide_slug,
                int(duration * 1000),
                ", ".join(png_targets) if png_targets else "-",
                extra={
                    "slide": job.slide_slug,
                    "duration_seconds": round(duration, 3),
                    "png_targets": png_targets,
                },
            )
            return PowerBIExportResult(job=job, result=result, exception=None, duration_seconds=duration)
        except Exception as exc:  # pragma: no cover - exercised via tests
            duration = time.perf_counter() - start
            logger.exception(
                "Power BI export failed slide=%s title=%r duration_ms=%s visual=%s",
                job.slide_slug,
                job.slide_title,
                int(duration * 1000),
                job.visual_path,
                extra={
                    "slide": job.slide_slug,
                    "title": job.slide_title,
                    "visual_path": str(job.visual_path),
                },
            )
            return PowerBIExportResult(job=job, result=None, exception=exc, duration_seconds=duration)


__all__ = ["PowerBIExportJob", "PowerBIExportQueue", "PowerBIExportResult"]
