from __future__ import annotations

from pathlib import Path

from praeparo.visuals.context_models import VisualContextModel


def test_visual_context_model_defaults() -> None:
    ctx = VisualContextModel()

    assert ctx.metrics_root == Path("registry/metrics").expanduser().resolve(strict=False)
    assert ctx.seed == 42
    assert ctx.scenario is None
    assert ctx.ignore_placeholders is False
    assert ctx.grain is None


def test_visual_context_model_parses_grain_sequence() -> None:
    ctx = VisualContextModel(grain=("'dim_calendar'[Month]", "'dim_customer'[Name]"))
    assert ctx.grain == ("'dim_calendar'[Month]", "'dim_customer'[Name]")
