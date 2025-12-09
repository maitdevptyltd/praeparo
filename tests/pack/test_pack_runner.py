from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from pathlib import Path
from typing import Any, Dict, Mapping, Tuple, cast

import pytest

from praeparo.models import BaseVisualConfig, PackConfig, PackSlide, PackVisualRef
from praeparo.pack.filters import merge_odata_filters
from praeparo.pack.loader import load_pack_config
from praeparo.pack.runner import run_pack
from praeparo.pack.templating import create_pack_jinja_env, render_value
from praeparo.pipeline import PipelineOptions, VisualExecutionResult, VisualPipeline
from praeparo.pipeline.outputs import OutputKind, PipelineOutputArtifact
from praeparo.visuals.dax.planner_core import slugify
from praeparo.visuals import VisualContextModel, register_visual_type


def test_pack_loader_and_templating(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text(
        """
schema: ing-pack-draft-1
context:
  lender_id: 201
  month: "2025-10-01"
filters:
  lender: "dim_lender/LenderId eq {{ lender_id }}"
  dates: "{{ odata_months_back_range('dim_calendar/month', month, 3) }}"
define: "DEFINE VAR Lender = {{ lender_id }}"
slides:
  - title: Example
    visual:
      ref: visuals/example.yaml
""",
        encoding="utf-8",
    )

    pack = load_pack_config(pack_path)
    env = create_pack_jinja_env()
    rendered_filters = render_value(pack.filters, env=env, context=pack.context)
    rendered_define = render_value(pack.define, env=env, context=pack.context)

    assert rendered_filters["lender"] == "dim_lender/LenderId eq 201"
    assert rendered_filters["dates"] == "dim_calendar/month ge 2025-08-01 and dim_calendar/month le 2025-10-01"
    assert rendered_define == "DEFINE VAR Lender = 201"


def test_merge_odata_filters_supports_dict_list_and_string() -> None:
    dict_merged = merge_odata_filters({"a": "one", "b": "two"}, {"b": "local", "c": "three"})
    assert dict_merged == {"a": "one", "b": "local", "c": "three"}

    list_merged = merge_odata_filters(["alpha"], ["beta", "gamma"])
    assert list_merged == ["alpha", "beta", "gamma"]

    string_merged = merge_odata_filters("first", "second")
    assert string_merged == ["first", "second"]

    inherit_global = merge_odata_filters(["base"], None)
    assert inherit_global == ["base"]


class _StubPipeline:
    def __init__(self) -> None:
        self.calls: list[Tuple[BaseVisualConfig, PipelineOptions]] = []
        self._lock = threading.Lock()
        self.contexts: list = []

    def execute(self, visual: BaseVisualConfig, context) -> VisualExecutionResult:
        with self._lock:
            self.calls.append((visual, context.options))
            self.contexts.append(context)
        outputs = []
        for target in context.options.outputs:
            if visual.type == "frame":
                continue
            target.path.parent.mkdir(parents=True, exist_ok=True)
            target.path.write_text(visual.type, encoding="utf-8")
            outputs.append(PipelineOutputArtifact(kind=target.kind, path=target.path))
        return VisualExecutionResult(config=visual, outputs=outputs)


class _ConcurrentStubPipeline:
    def __init__(self, *, delay: float = 0.05, fail_case: str | None = None) -> None:
        self.calls: list[Tuple[BaseVisualConfig, PipelineOptions]] = []
        self.delay = delay
        self.fail_case = fail_case
        self.running_powerbi = 0
        self.max_running_powerbi = 0
        self._lock = threading.Lock()

    def execute(self, visual: BaseVisualConfig, context) -> VisualExecutionResult:
        is_powerbi = visual.type == "powerbi"
        if is_powerbi:
            with self._lock:
                self.running_powerbi += 1
                self.max_running_powerbi = max(self.max_running_powerbi, self.running_powerbi)
            try:
                if self.fail_case and context.case_key == self.fail_case:
                    raise RuntimeError("boom")
                if self.delay:
                    time.sleep(self.delay)
            finally:
                with self._lock:
                    self.running_powerbi -= 1

        path = context.options.outputs[0].path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(visual.type, encoding="utf-8")

        outputs = [PipelineOutputArtifact(kind=OutputKind.PNG, path=path)]

        with self._lock:
            self.calls.append((visual, context.options))

        return VisualExecutionResult(config=visual, outputs=outputs)


def test_run_pack_routes_visuals_and_emits_pngs(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    pack = PackConfig(
        schema="test-pack",
        context={"lender_id": 7, "month": "2025-11-01"},
        define="DEFINE VAR Lender = {{ lender_id }}",
        calculate={"lender": "'dim_lender'[LenderId] = {{ lender_id }}"},
        filters={"lender": "dim_lender/LenderId eq {{ lender_id }}"},
        slides=[
            PackSlide(
                title="PowerBI Slide",
                id="pbi-slide",
                visual=PackVisualRef(
                    ref="powerbi.yaml",
                    filters={"local": "fact/Status eq 'Active'"},
                    calculate=["'dim_channel'[Name] = \"Broker\""],
                ),
            ),
            PackSlide(
                title="Matrix Visual",
                visual=PackVisualRef(ref="matrix.yaml", calculate=["'dim_channel'[Name] = \"Direct\""]),
            ),
            PackSlide(
                title="Skip Frame",
                visual=PackVisualRef(ref="frame.yaml"),
            ),
        ],
    )

    visuals: Dict[str, BaseVisualConfig] = {
        "powerbi.yaml": BaseVisualConfig(type="powerbi"),
        "matrix.yaml": BaseVisualConfig(type="matrix"),
        "frame.yaml": BaseVisualConfig(type="frame"),
    }

    def _loader(path: Path, payload: Mapping[str, object] | None = None, stack: tuple[Path, ...] = ()) -> BaseVisualConfig:
        return visuals[path.name]

    pipeline = _StubPipeline()
    results = run_pack(
        pack_path,
        pack,
        output_root=tmp_path / "artefacts",
        base_options=PipelineOptions(),
        visual_loader=_loader,
        pipeline=cast(VisualPipeline[Any], pipeline),
        env=create_pack_jinja_env(),
    )

    png_paths = {result.png_path for result in results if result.png_path}
    assert (tmp_path / "artefacts" / f"{slugify('pbi-slide')}.png") in png_paths
    assert (tmp_path / "artefacts" / "matrix_visual.png") in png_paths

    # Frame visual produces no PNG but should not error.
    assert any(result.result.outputs == [] for result in results if result.result.config.type == "frame")

    metadata_by_type: Dict[str, Dict[str, object]] = {call[0].type: cast(Dict[str, object], call[1].metadata) for call in pipeline.calls}
    powerbi_metadata = metadata_by_type["powerbi"]
    assert "powerbi_filters" in powerbi_metadata
    assert "dim_lender/LenderId eq 7" in str(powerbi_metadata["powerbi_filters"])

    matrix_metadata = metadata_by_type["matrix"]
    context_meta = matrix_metadata.get("context")
    assert isinstance(context_meta, dict)
    calculate_payload = context_meta.get("calculate")
    assert isinstance(calculate_payload, list)
    assert calculate_payload[0].startswith("'dim_lender'[LenderId] = 7")
    assert calculate_payload[1] == "'dim_channel'[Name] = \"Direct\""
    assert len(calculate_payload) == 2
    define_payload = context_meta.get("define")
    assert isinstance(define_payload, list)
    assert define_payload == ["DEFINE VAR Lender = 7"]


def test_run_pack_populates_typed_dax_context(tmp_path: Path) -> None:
    register_visual_type(
        "contextual",
        lambda path, payload=None, stack=(): BaseVisualConfig(type="contextual"),
        overwrite=True,
        context_model=VisualContextModel,
    )

    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    pack = PackConfig(
        schema="test-pack",
        calculate=["'dim_channel'[Name] = \"Base\""],
        define="DEFINE MEASURE Test[Value] = 1",
        slides=[
            PackSlide(
                title="Context Slide",
                visual=PackVisualRef(ref="contextual.yaml", calculate=["'dim_channel'[Name] = \"Direct\""]),
            ),
        ],
    )

    visuals: Dict[str, BaseVisualConfig] = {"contextual.yaml": BaseVisualConfig(type="contextual")}

    def _loader(path: Path, payload: Mapping[str, object] | None = None, stack: tuple[Path, ...] = ()) -> BaseVisualConfig:
        return visuals[path.name]

    pipeline = _StubPipeline()
    results = run_pack(
        pack_path,
        pack,
        output_root=tmp_path / "artefacts",
        base_options=PipelineOptions(metadata={"metrics_root": "registry/metrics"}),
        visual_loader=_loader,
        pipeline=cast(VisualPipeline[Any], pipeline),
        env=create_pack_jinja_env(),
    )

    assert results
    assert pipeline.contexts
    visual_ctx = pipeline.contexts[0].visual_context
    assert visual_ctx is not None
    assert visual_ctx.dax.calculate == (
        "'dim_channel'[Name] = \"Base\"",
        "'dim_channel'[Name] = \"Direct\"",
    )
    assert visual_ctx.dax.define == ("DEFINE MEASURE Test[Value] = 1",)


def test_run_pack_honours_only_slides(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    slides = [
        PackSlide(
            title="Keep Me",
            id="keep-1",
            visual=PackVisualRef(ref="one.yaml"),
        ),
        PackSlide(
            title="Also Keep",
            visual=PackVisualRef(ref="two.yaml"),
        ),
        PackSlide(
            title="Skip Me",
            id="skip-this",
            visual=PackVisualRef(ref="three.yaml"),
        ),
        PackSlide(
            title="Slug Target",
            id="Slug-ID",
            visual=PackVisualRef(ref="four.yaml"),
        ),
    ]

    pack = PackConfig(
        schema="test-pack",
        slides=slides,
    )

    visuals: Dict[str, BaseVisualConfig] = {
        "one.yaml": BaseVisualConfig(type="powerbi"),
        "two.yaml": BaseVisualConfig(type="matrix"),
        "three.yaml": BaseVisualConfig(type="powerbi"),
        "four.yaml": BaseVisualConfig(type="powerbi"),
    }

    def _loader(path: Path, payload: Mapping[str, object] | None = None, stack: tuple[Path, ...] = ()) -> BaseVisualConfig:
        return visuals[path.name]

    pipeline = _StubPipeline()
    results = run_pack(
        pack_path,
        pack,
        output_root=tmp_path / "artefacts",
        base_options=PipelineOptions(),
        visual_loader=_loader,
        pipeline=cast(VisualPipeline[Any], pipeline),
        env=create_pack_jinja_env(),
        only_slides=["keep-1", "Also Keep", slugify("Slug Target")],
    )

    executed_titles = {result.slide.title for result in results}
    assert executed_titles == {"Keep Me", "Also Keep", "Slug Target"}
    called_visuals = {call[0].type for call in pipeline.calls}
    assert called_visuals == {"powerbi", "matrix"}

    expected_pngs = {
        tmp_path / "artefacts" / "keep_1.png",
        tmp_path / "artefacts" / "also_keep.png",
        tmp_path / "artefacts" / "slug_id.png",
    }
    emitted_pngs = {result.png_path for result in results if result.png_path}
    assert expected_pngs == emitted_pngs


def test_run_pack_queues_powerbi_and_respects_concurrency(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    pack = PackConfig(
        schema="test-pack",
        slides=[
            PackSlide(title="PBI One", id="pbi-one", visual=PackVisualRef(ref="pbi1.yaml")),
            PackSlide(title="Matrix Slide", visual=PackVisualRef(ref="matrix.yaml")),
            PackSlide(title="PBI Two", id="pbi-two", visual=PackVisualRef(ref="pbi2.yaml")),
        ],
    )

    visuals: Dict[str, BaseVisualConfig] = {
        "pbi1.yaml": BaseVisualConfig(type="powerbi"),
        "pbi2.yaml": BaseVisualConfig(type="powerbi"),
        "matrix.yaml": BaseVisualConfig(type="matrix"),
    }

    def _loader(path: Path, payload: Mapping[str, object] | None = None, stack: tuple[Path, ...] = ()) -> BaseVisualConfig:
        return visuals[path.name]

    pipeline = _ConcurrentStubPipeline(delay=0.05)
    results = run_pack(
        pack_path,
        pack,
        output_root=tmp_path / "artefacts",
        base_options=PipelineOptions(),
        visual_loader=_loader,
        pipeline=cast(VisualPipeline[Any], pipeline),
        env=create_pack_jinja_env(),
        max_powerbi_concurrency=2,
    )

    png_paths = {result.png_path for result in results if result.png_path}
    expected_pngs = {
        tmp_path / "artefacts" / f"{slugify('pbi-one')}.png",
        tmp_path / "artefacts" / f"{slugify('pbi-two')}.png",
        tmp_path / "artefacts" / f"{slugify('Matrix Slide')}.png",
    }
    assert expected_pngs == png_paths
    assert pipeline.max_running_powerbi <= 2
    assert len([item for item in results if item.result.config.type == "powerbi"]) == 2


def test_run_pack_raises_when_powerbi_job_fails(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    failing_slug = slugify("fail-pbi")
    pack = PackConfig(
        schema="test-pack",
        slides=[
            PackSlide(title="OK Slide", id="ok-pbi", visual=PackVisualRef(ref="pbi1.yaml")),
            PackSlide(title="Fail Slide", id="fail-pbi", visual=PackVisualRef(ref="pbi2.yaml")),
        ],
    )

    visuals: Dict[str, BaseVisualConfig] = {
        "pbi1.yaml": BaseVisualConfig(type="powerbi"),
        "pbi2.yaml": BaseVisualConfig(type="powerbi"),
    }

    def _loader(path: Path, payload: Mapping[str, object] | None = None, stack: tuple[Path, ...] = ()) -> BaseVisualConfig:
        return visuals[path.name]

    pipeline = _ConcurrentStubPipeline(delay=0.0, fail_case=failing_slug)

    with pytest.raises(RuntimeError) as excinfo:
        run_pack(
            pack_path,
            pack,
            output_root=tmp_path / "artefacts",
            base_options=PipelineOptions(),
            visual_loader=_loader,
            pipeline=cast(VisualPipeline[Any], pipeline),
            env=create_pack_jinja_env(),
            max_powerbi_concurrency=2,
        )

    assert failing_slug in str(excinfo.value)
    ok_png = tmp_path / "artefacts" / f"{slugify('ok-pbi')}.png"
    assert ok_png.exists()
