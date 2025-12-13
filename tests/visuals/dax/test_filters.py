from __future__ import annotations

from praeparo.visuals.dax import combine_filter_groups, normalise_filter_group, wrap_expression_with_filters


def test_normalise_filter_group_removes_duplicates() -> None:
    result = normalise_filter_group([
        " 'dim_calendar'[Month] = ""2025-01"" ",
        "'dim_calendar'[Month] = ""2025-01""",
        {"month": "'dim_calendar'[Month] = 2025-01"},
        "",
    ])
    assert len(result) == 1
    assert "'dim_calendar'[Month]" in result[0]


def test_combine_filter_groups_preserves_order() -> None:
    combined = combine_filter_groups(
        ["'dim_lender'[LenderId] = 201"],
        "'dim_region'[IsActive] = TRUE()",
    )
    assert combined == (
        "'dim_lender'[LenderId] = 201",
        "'dim_region'[IsActive] = TRUE()",
    )


def test_wrap_expression_with_filters_builds_calculate_block() -> None:
    wrapped = wrap_expression_with_filters(
        "SUM('fact_events'[DocumentsSent])",
        ["'dim_region'[IsActive] = TRUE()", "'dim_lender'[LenderId] = 201"],
    )
    assert wrapped.startswith("CALCULATE(\n    SUM('fact_events'[DocumentsSent])")
    assert "'dim_region'[IsActive] = TRUE()" in wrapped
