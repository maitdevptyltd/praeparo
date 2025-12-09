from __future__ import annotations

from pathlib import Path

from praeparo.visuals.context import merge_context_payload
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


def test_merge_context_payload_handles_mapping_calculate() -> None:
    base = {"calculate": {"lender": "'dim_lender'[LenderId] = 201"}}

    ctx = merge_context_payload(base=base, calculate=None, define=None)

    assert ctx["calculate"] == ["'dim_lender'[LenderId] = 201"]


def test_merge_context_payload_overrides_named_calculate() -> None:
    base = {"calculate": {"lender": "'dim_lender'[LenderId] = 201", "channel": "'dim_channel'[Name] = \"Broker\""}}

    ctx = merge_context_payload(base=base, calculate={"lender": "'dim_lender'[LenderId] = 301"}, define=None)

    assert ctx["calculate"] == ["'dim_lender'[LenderId] = 301", "'dim_channel'[Name] = \"Broker\""]


def test_merge_context_payload_appends_unlabelled_after_named() -> None:
    base = {"calculate": {"lender": "'dim_lender'[LenderId] = 201"}}

    ctx = merge_context_payload(base=base, calculate=["'dim_region'[Name] = \"NSW\""], define=None)

    assert ctx["calculate"] == ["'dim_lender'[LenderId] = 201", "'dim_region'[Name] = \"NSW\""]


def test_merge_context_payload_honours_last_mapping_in_sequence() -> None:
    base = {
        "calculate": [
            {"lender": "'dim_lender'[LenderId] = 201"},
            "'dim_region'[Name] = \"NSW\"",
            {"lender": "'dim_lender'[LenderId] = 301"},
        ]
    }

    ctx = merge_context_payload(base=base, calculate=None, define=None)

    assert ctx["calculate"] == ["'dim_lender'[LenderId] = 301", "'dim_region'[Name] = \"NSW\""]
