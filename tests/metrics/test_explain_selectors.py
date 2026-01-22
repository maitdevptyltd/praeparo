from __future__ import annotations

from pathlib import Path
import sys

import pytest

from praeparo.metrics.cli import run
from praeparo.metrics.explain import build_metric_binding_explain_plan
from praeparo.metrics.selectors import (
    PlaceholderSelector,
    SlideSelector,
    detect_selector_file_kind,
    parse_selector,
    resolve_pack_placeholder,
    resolve_pack_slide,
)
from praeparo.metrics import load_metric_catalog
from praeparo.pack.loader import load_pack_config


def _write_minimal_cartesian_visual(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema: draft-1",
                "type: column",
                "category:",
                "  field: \"'dim_calendar'[Month]\"",
                "value_axes:",
                "  primary:",
                "    label: Value",
                "series:",
                "  - id: pct_in_1d",
                "    label: \"% in 1 day\"",
                "    metric:",
                "      key: documents_sent.within_1d",
                "      calculate:",
                "        - fact_documents[NumeratorOnly] = 1",
                "      ratio_to: documents_sent",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_minimal_pack(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(
            [
                "schema: test-pack",
                "slides:",
                "  - title: Home",
                "    id: home",
                "    visual:",
                "      ref: visual.yaml",
                "  - title: Placeholder slide",
                "    placeholders:",
                "      chart:",
                "        visual:",
                "          ref: visual.yaml",
                "      hero:",
                "        image: hero.png",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _write_metric_registry(metrics_root: Path) -> None:
    metrics_root.mkdir(parents=True, exist_ok=True)
    (metrics_root / "documents_sent.yaml").write_text(
        "\n".join(
            [
                "schema: draft-1",
                "key: documents_sent",
                "display_name: Documents sent",
                "section: Test",
                "define: \"COUNTROWS ( 'fact_documents' )\"",
                "variants:",
                "  within_1d:",
                "    display_name: Within 1d",
                "    calculate:",
                "      - fact_documents[DeltaDays] <= 1",
            ]
        )
        + "\n",
        encoding="utf-8",
    )


def _extract_var_block(statement: str, *, var_name: str) -> str:
    lines = statement.splitlines()
    start = None
    for idx, line in enumerate(lines):
        if line.startswith(f"VAR {var_name} ="):
            start = idx
            break
    assert start is not None, f"Missing VAR {var_name} in statement"

    block_lines: list[str] = []
    for idx in range(start, len(lines)):
        line = lines[idx]
        if idx != start and line.startswith("VAR "):
            break
        if idx != start and line.startswith("RETURN"):
            break
        block_lines.append(line)
    return "\n".join(block_lines)


def test_parse_selector_metric_and_file_tokens(tmp_path: Path) -> None:
    visual_path = tmp_path / "visual.yaml"
    pack_path = tmp_path / "pack.yaml"
    _write_minimal_cartesian_visual(visual_path)
    _write_minimal_pack(pack_path)

    metric = parse_selector("documents_sent.within_1d", cwd=tmp_path)
    assert metric.metric_identifier == "documents_sent.within_1d"  # type: ignore[attr-defined]

    file_sel = parse_selector("visual.yaml#pct_in_1d", cwd=tmp_path)
    assert file_sel.path == visual_path.resolve(strict=False)  # type: ignore[attr-defined]
    assert file_sel.segments == ("pct_in_1d",)  # type: ignore[attr-defined]

    pack_sel = parse_selector("pack.yaml#home#pct_in_1d", cwd=tmp_path)
    assert pack_sel.path == pack_path.resolve(strict=False)  # type: ignore[attr-defined]
    assert pack_sel.segments[0] == "home"  # type: ignore[attr-defined]


def test_detect_selector_file_kind(tmp_path: Path) -> None:
    visual_path = tmp_path / "visual.yaml"
    pack_path = tmp_path / "pack.yaml"
    _write_minimal_cartesian_visual(visual_path)
    _write_minimal_pack(pack_path)

    assert detect_selector_file_kind(visual_path) == "visual"
    assert detect_selector_file_kind(pack_path) == "pack"


def test_pack_slide_and_placeholder_resolution(tmp_path: Path) -> None:
    pack_path = tmp_path / "pack.yaml"
    _write_minimal_pack(pack_path)
    pack = load_pack_config(pack_path)

    slide_index, slide = resolve_pack_slide(pack, SlideSelector.parse("0"))
    assert slide_index == 0
    assert slide.title == "Home"

    slide_index, slide = resolve_pack_slide(pack, SlideSelector.parse("home"))
    assert slide_index == 0

    _, placeholder_slide = resolve_pack_slide(pack, SlideSelector.parse("1"))
    placeholder_id, placeholder = resolve_pack_placeholder(placeholder_slide, PlaceholderSelector.parse("0"))
    assert placeholder_id == "chart"
    assert placeholder.visual is not None


def test_explain_binding_ratio_does_not_apply_define_filters_to_denominator(tmp_path: Path) -> None:
    metrics_root = tmp_path / "metrics"
    _write_metric_registry(metrics_root)
    catalog = load_metric_catalog([metrics_root])

    numerator_filter = "fact_documents[NumeratorOnly] = 1"
    group_filter = "'Time Intelligence'[Period] = \"Current Month\""

    plan = build_metric_binding_explain_plan(
        catalog,
        metric_reference="documents_sent.within_1d",
        metric_identifier="visual.yaml#pct_in_1d",
        context_calculate_filters=[group_filter],
        numerator_define_filters=[numerator_filter],
        ratio_to="documents_sent",
        limit=100,
    )

    denom_block = _extract_var_block(plan.statement, var_name="__denominator_value")
    assert group_filter in denom_block
    assert numerator_filter not in denom_block

    numer_block = _extract_var_block(plan.statement, var_name="__metric_value")
    assert group_filter in numer_block
    assert numerator_filter in numer_block


def test_metrics_cli_loads_plugins_before_listing_bindings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys) -> None:
    monkeypatch.chdir(tmp_path)

    plugin_module = tmp_path / "test_plugin.py"
    plugin_module.write_text(
        "\n".join(
            [
                "from __future__ import annotations",
                "",
                "from pathlib import Path",
                "from typing import Mapping, Tuple, Sequence",
                "",
                "from pydantic import BaseModel, ConfigDict, Field",
                "",
                "from praeparo.models.visual_base import BaseVisualConfig",
                "from praeparo.models.scoped_calculate import ScopedCalculateFilters",
                "from praeparo.visuals.registry import register_visual_type",
                "from praeparo.visuals.bindings import VisualMetricBinding, register_visual_bindings_adapter",
                "",
                "class PluginVisualConfig(BaseVisualConfig):",
                "    model_config = ConfigDict(extra='forbid')",
                "    type: str = Field(default='plugin_visual')",
                "    metrics: list[str] = Field(default_factory=list)",
                "",
                "def _loader(path: Path, payload: Mapping[str, object], stack: Tuple[Path, ...]):",
                "    return PluginVisualConfig.model_validate(payload)",
                "",
                "class _Adapter:",
                "    def list_bindings(self, visual: BaseVisualConfig, *, source_path=None) -> Sequence[VisualMetricBinding]:",
                "        assert isinstance(visual, PluginVisualConfig)",
                "        return tuple(",
                "            VisualMetricBinding(",
                "                binding_id=metric,",
                "                selector_segments=(metric,),",
                "                label=metric,",
                "                metric_key=metric,",
                "                calculate=ScopedCalculateFilters(),",
                "            )",
                "            for metric in visual.metrics",
                "        )",
                "    def resolve_binding(self, visual: BaseVisualConfig, selector_segments: Sequence[str], *, source_path=None):",
                "        raise NotImplementedError",
                "",
                "register_visual_type('plugin_visual', _loader, overwrite=True)",
                "register_visual_bindings_adapter('plugin_visual', _Adapter(), overwrite=True)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    monkeypatch.syspath_prepend(str(tmp_path))

    visual_path = tmp_path / "visual.yaml"
    visual_path.write_text(
        "\n".join(
            [
                "type: plugin_visual",
                "metrics:",
                "  - documents_sent",
                "  - documents_sent.within_1d",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    code = run(["explain", "visual.yaml", "--list-bindings", "--plugin", "test_plugin"])
    assert code == 0

    out = capsys.readouterr().out
    assert "visual.yaml#documents_sent" in out
    assert "visual.yaml#documents_sent.within_1d" in out
