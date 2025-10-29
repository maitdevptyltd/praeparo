from __future__ import annotations

from praeparo.visuals.dax.planner_core import MeasurePlan, VisualPlan, default_name_strategy, slugify


def test_slugify_converts_text() -> None:
    assert slugify("Monthly Governance") == "monthly_governance"
    assert slugify("Clean  name!!") == "clean_name"


def test_default_name_strategy_includes_reference() -> None:
    result = default_name_strategy("documents_sent.manual", "monthly_governance")
    assert result == "monthly_governance_documents_sent_manual"


def test_visual_plan_structure() -> None:
    plan = VisualPlan(slug="test", measures=(), grain_columns=("col",))
    assert plan.slug == "test"
    assert plan.grain_columns == ("col",)
