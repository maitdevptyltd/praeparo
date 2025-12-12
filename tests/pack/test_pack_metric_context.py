from __future__ import annotations

import pytest
from pydantic import ValidationError

from praeparo.models import PackConfig, PackMetricBinding


def _minimal_slide(**overrides):
    payload = {"title": "Slide 1"}
    payload.update(overrides)
    return payload


def test_context_metrics_list_shorthand_defaults_alias() -> None:
    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {"metrics": ["documents_verified.within_1_day"]},
            "slides": [_minimal_slide()],
        }
    )

    assert pack.context.metrics is not None
    bindings = pack.context.metrics.bindings or []
    binding = bindings[0]
    assert binding.key == "documents_verified.within_1_day"
    assert binding.alias == "documents_verified_within_1_day"


def test_context_metrics_mapping_shorthand_normalises_bindings() -> None:
    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {"metrics": {"documents_verified": "verified_total"}},
            "slides": [_minimal_slide()],
        }
    )

    assert pack.context.metrics is not None
    bindings = pack.context.metrics.bindings or []
    binding = bindings[0]
    assert binding.key == "documents_verified"
    assert binding.alias == "verified_total"


def test_context_metrics_object_form_supports_variant_and_expression() -> None:
    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {
                "metrics": [
                    {"key": "documents_verified", "variant": "within_1_day"},
                    {
                        "alias": "pct_verified_1d",
                        "expression": "documents_verified.within_1_day / documents_verified",
                    },
                ]
            },
            "slides": [_minimal_slide()],
        }
    )

    bindings = pack.context.metrics.bindings or []
    assert bindings[0].full_key == "documents_verified.within_1_day"
    assert bindings[0].alias == "documents_verified_within_1_day"
    assert bindings[1].alias == "pct_verified_1d"


def test_variant_disallowed_with_dotted_key() -> None:
    with pytest.raises(ValidationError):
        PackMetricBinding.model_validate(
            {"key": "documents_verified.within_1_day", "variant": "within_2_days"}
        )


def test_expression_only_requires_alias() -> None:
    with pytest.raises(ValidationError):
        PackMetricBinding.model_validate({"expression": "documents_sent / 2"})


def test_slide_alias_collision_requires_override() -> None:
    with pytest.raises(ValidationError, match="override"):
        PackConfig.model_validate(
            {
                "schema": "test-pack",
                "context": {"metrics": {"documents_verified": "total"}},
                "slides": [
                    {
                        "title": "Slide 1",
                        "context": {"metrics": {"documents_sent": "total"}},
                    }
                ],
            }
        )


def test_slide_alias_collision_with_override_passes() -> None:
    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {"metrics": {"documents_verified": "total"}},
            "slides": [
                {
                    "title": "Slide 1",
                    "context": {
                        "metrics": [
                            {
                                "key": "documents_sent",
                                "alias": "total",
                                "override": True,
                            }
                        ]
                    },
                }
            ],
        }
    )

    assert pack.slides[0].context is not None
    assert pack.slides[0].context.metrics is not None
    slide_bindings = pack.slides[0].context.metrics.bindings or []
    assert slide_bindings[0].override is True


def test_slide_alias_collision_identical_binding_no_override() -> None:
    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {"metrics": {"documents_verified": "total"}},
            "slides": [
                {
                    "title": "Slide 1",
                    "context": {"metrics": {"documents_verified": "total"}},
                }
            ],
        }
    )

    assert pack.slides[0].context is not None
    assert pack.slides[0].context.metrics is not None
    slide_bindings = pack.slides[0].context.metrics.bindings or []
    assert slide_bindings[0].override is False


def test_context_metrics_wrapper_supports_calculate_and_bindings() -> None:
    pack = PackConfig.model_validate(
        {
            "schema": "test-pack",
            "context": {
                "metrics": {
                    "calculate": {"month": "'dim_calendar'[month] = DATEVALUE(\"2025-11-01\")"},
                    "bindings": {"documents_verified": "total_verified"},
                }
            },
            "slides": [_minimal_slide()],
        }
    )

    assert pack.context.metrics is not None
    assert pack.context.metrics.calculate is not None
    bindings = pack.context.metrics.bindings or []
    assert bindings[0].alias == "total_verified"
