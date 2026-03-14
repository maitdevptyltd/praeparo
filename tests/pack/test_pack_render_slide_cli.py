from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, cast

import pytest

from praeparo.cli import main as cli_main
from praeparo.models import BaseVisualConfig, PackConfig, PackSlide, PackVisualRef
from praeparo.pack import PackSlideResult
from praeparo.pipeline import VisualExecutionResult


def test_pack_cli_render_slide_skips_evidence_by_default(monkeypatch, tmp_path: Path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        assert path == pack_path
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg: Path,
        pack: PackConfig,
        *,
        project_root=None,
        output_root: Path,
        max_powerbi_concurrency=None,
        base_options,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        include_evidence=True,
        evidence_only=False,
    ):
        captured["only_slides"] = only_slides
        captured["include_evidence"] = include_evidence
        captured["metadata"] = dict(base_options.metadata)

        slide = pack.slides[0]
        slide_dir = output_root / "[01]_slide-id-1"
        slide_dir.mkdir(parents=True, exist_ok=True)
        png_path = output_root / "slide-id-1.png"
        png_path.write_text("png", encoding="utf-8")
        result = VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[])
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=result,
                png_path=png_path,
                slide_index=1,
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="[01]_slide-id-1",
                artefact_dir=slide_dir,
                visual_type="powerbi",
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    artefacts_dir = tmp_path / "artefacts"
    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "render-slide",
                str(pack_path),
                "--artefact-dir",
                str(artefacts_dir),
                "--slide",
                "slide-id-1",
            ]
        )

    assert exc.value.code == 0
    assert captured["only_slides"] == ("slide-id-1",)
    assert captured["include_evidence"] is False
    assert "result_file" not in cast(dict[str, object], captured["metadata"])

    manifest = json.loads((artefacts_dir / "render.manifest.json").read_text(encoding="utf-8"))
    assert manifest["kind"] == "pack_render_slide"
    assert manifest["requested_slides"] == ["slide-id-1"]

    out = capsys.readouterr().out
    assert "[ok] Wrote render manifest to" in out
    assert "[ok] Slide render completed in" in out


def test_pack_cli_render_slide_can_include_evidence(monkeypatch, tmp_path: Path, capsys) -> None:
    pack_path = tmp_path / "pack.yaml"
    pack_path.write_text("contents", encoding="utf-8")

    captured: Dict[str, object] = {}

    def fake_load_pack_config(path: Path) -> PackConfig:
        assert path == pack_path
        return PackConfig(
            schema="test-pack",
            slides=[PackSlide(title="Slide One", id="slide-id-1", visual=PackVisualRef(ref="one.yaml"))],
        )

    def fake_run_pack(
        pack_path_arg: Path,
        pack: PackConfig,
        *,
        project_root=None,
        output_root: Path,
        max_powerbi_concurrency=None,
        base_options,
        visual_loader=None,
        pipeline=None,
        env=None,
        only_slides=(),
        include_evidence=True,
        evidence_only=False,
    ):
        captured["include_evidence"] = include_evidence

        slide = pack.slides[0]
        slide_dir = output_root / "[01]_slide-id-1"
        slide_dir.mkdir(parents=True, exist_ok=True)
        png_path = output_root / "slide-id-1.png"
        png_path.write_text("png", encoding="utf-8")
        result = VisualExecutionResult(config=BaseVisualConfig(type="powerbi"), outputs=[])
        return [
            PackSlideResult(
                slide=slide,
                visual_path=pack_path_arg,
                result=result,
                png_path=png_path,
                slide_index=1,
                slide_slug="slide-id-1",
                target_slug="slide-id-1",
                artifact_label="[01]_slide-id-1",
                artefact_dir=slide_dir,
                visual_type="powerbi",
            )
        ]

    class FakePipeline:
        def __init__(self, *_, **__):
            pass

    monkeypatch.setattr("praeparo.cli.load_pack_config", fake_load_pack_config)
    monkeypatch.setattr("praeparo.cli.run_pack", fake_run_pack)
    monkeypatch.setattr("praeparo.cli.VisualPipeline", FakePipeline)
    monkeypatch.setattr("praeparo.cli.build_default_query_planner_provider", lambda: None)

    artefacts_dir = tmp_path / "artefacts"
    with pytest.raises(SystemExit) as exc:
        cli_main(
            [
                "pack",
                "render-slide",
                str(pack_path),
                "--artefact-dir",
                str(artefacts_dir),
                "--slide",
                "slide-id-1",
                "--include-evidence",
            ]
        )

    assert exc.value.code == 0
    assert captured["include_evidence"] is True

    out = capsys.readouterr().out
    assert "[ok] Wrote render manifest to" in out
