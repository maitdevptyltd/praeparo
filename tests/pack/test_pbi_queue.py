from __future__ import annotations

import threading
import time
from pathlib import Path

from praeparo.models import BaseVisualConfig, PackSlide
from praeparo.pack.pbi_queue import PowerBIExportJob, PowerBIExportQueue
from praeparo.pipeline import ExecutionContext, PipelineOptions, VisualExecutionResult
from praeparo.pipeline.outputs import OutputKind, OutputTarget, PipelineOutputArtifact


class _ConcurrentPipeline:
    def __init__(self, delay: float = 0.05) -> None:
        self.delay = delay
        self.running = 0
        self.max_running = 0
        self._lock = threading.Lock()

    def execute(self, visual: BaseVisualConfig, context: ExecutionContext) -> VisualExecutionResult:
        with self._lock:
            self.running += 1
            self.max_running = max(self.max_running, self.running)

        try:
            if self.delay:
                time.sleep(self.delay)
            path = context.options.outputs[0].path
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("pbi", encoding="utf-8")
            outputs = [PipelineOutputArtifact(kind=OutputKind.PNG, path=path)]
            return VisualExecutionResult(config=visual, outputs=outputs)
        finally:
            with self._lock:
                self.running -= 1


class _FailingPipeline(_ConcurrentPipeline):
    def __init__(self, *, fail_case: str) -> None:
        super().__init__(delay=0.0)
        self.fail_case = fail_case

    def execute(self, visual: BaseVisualConfig, context: ExecutionContext) -> VisualExecutionResult:
        if context.case_key == self.fail_case:
            raise RuntimeError("boom")
        return super().execute(visual, context)


def _build_job(tmp_path: Path, index: int) -> PowerBIExportJob:
    options = PipelineOptions(outputs=[OutputTarget.png(tmp_path / f"slide{index}.png")])
    context = ExecutionContext(
        config_path=tmp_path / f"visual{index}.yaml",
        project_root=tmp_path,
        case_key=f"slide{index}",
        options=options,
    )
    return PowerBIExportJob(
        slide_index=index,
        slide_slug=f"slide_{index}",
        slide_title=f"Slide {index}",
        slide=PackSlide(title=f"Slide {index}", visual=None),
        visual=BaseVisualConfig(type="powerbi"),
        visual_path=tmp_path / f"visual{index}.yaml",
        execution_context=context,
    )


def test_powerbi_queue_respects_max_concurrency(tmp_path: Path) -> None:
    pipeline = _ConcurrentPipeline(delay=0.05)
    queue = PowerBIExportQueue(pipeline, max_concurrent_exports=2)

    for index in range(4):
        queue.enqueue(_build_job(tmp_path, index))

    results = queue.drain()

    assert len(results) == 4
    assert all(item.succeeded for item in results)
    assert pipeline.max_running <= 2
    for item in results:
        assert item.result is not None
        assert item.result.outputs
        assert item.result.outputs[0].path.exists()


def test_powerbi_queue_collects_failures(tmp_path: Path) -> None:
    pipeline = _FailingPipeline(fail_case="slide1")
    queue = PowerBIExportQueue(pipeline, max_concurrent_exports=2)

    queue.enqueue(_build_job(tmp_path, 0))
    queue.enqueue(_build_job(tmp_path, 1))

    results = queue.drain()
    failures = [item for item in results if item.exception]
    successes = [item for item in results if item.succeeded]

    assert len(failures) == 1
    assert str(failures[0].exception) == "boom"
    assert len(successes) == 1
    assert successes[0].result is not None
