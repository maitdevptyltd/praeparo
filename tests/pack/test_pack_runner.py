from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Tuple

import pytest

from praeparo.models import BaseVisualConfig, PackConfig, PackSlide, PackVisualRef
from praeparo.pack.filters import merge_odata_filters
from praeparo.pack.loader import load_pack_config
from praeparo.pack.runner import run_pack
from praeparo.pack.templating import create_pack_jinja_env, render_value
from praeparo.pipeline import PipelineOptions, VisualExecutionResult
from praeparo.pipeline.outputs import OutputKind, PipelineOutputArtifact
from praeparo.visuals.dax.planner_core import slugify


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

    assert rendered_filters["lender"] == "dim_lender/LenderId eq 201"
    assert rendered_filters["dates"] == "dim_calendar/month ge 2025-08-01 and dim_calendar/month le 2025-10-01"


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

    def execute(self, visual: BaseVisualConfig, context) -> VisualExecutionResult:
        self.calls.append((visual, context.options))
        outputs = []
        for target in context.options.outputs:
            if visual.type == "frame":
                continue
            target.path.parent.mkdir(parents=True, exist_ok=True)
            target.path.write_text(visual.type, encoding="utf-8")
            outputs.append(PipelineOutputArtifact(kind=target.kind, path=target.path))
        return VisualExecutionResult(config=visual, outputs=outputs)


def test_run_pack_routes_visuals_and_emits_pngs(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("", encoding="utf-8")

    pack = PackConfig(
        schema="test-pack",
        context={"lender_id": 7, "month": "2025-11-01"},
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

    def _loader(path: Path) -> BaseVisualConfig:
        return visuals[path.name]

    pipeline = _StubPipeline()
    results = run_pack(
        pack_path,
        pack,
        output_root=tmp_path / "artefacts",
        base_options=PipelineOptions(),
        visual_loader=_loader,
        pipeline=pipeline,
        env=create_pack_jinja_env(),
    )

    png_paths = {result.png_path for result in results if result.png_path}
    assert (tmp_path / "artefacts" / f"{slugify('pbi-slide')}.png") in png_paths
    assert (tmp_path / "artefacts" / "matrix_visual.png") in png_paths

    # Frame visual produces no PNG but should not error.
    assert any(result.result.outputs == [] for result in results if result.result.config.type == "frame")

    powerbi_metadata = pipeline.calls[0][1].metadata
    assert "powerbi_filters" in powerbi_metadata
    assert "dim_lender/LenderId eq 7" in str(powerbi_metadata["powerbi_filters"])

    matrix_metadata = pipeline.calls[1][1].metadata
    context_meta = matrix_metadata.get("context")
    assert context_meta and context_meta.get("calculate")
    assert context_meta["calculate"][0].startswith("'dim_lender'[LenderId] = 7")
    assert context_meta["calculate"][1] == "'dim_channel'[Name] = \"Direct\""
    assert len(context_meta["calculate"]) == 2


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

    def _loader(path: Path) -> BaseVisualConfig:
        return visuals[path.name]

    pipeline = _StubPipeline()
    results = run_pack(
        pack_path,
        pack,
        output_root=tmp_path / "artefacts",
        base_options=PipelineOptions(),
        visual_loader=_loader,
        pipeline=pipeline,
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
