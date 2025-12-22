from __future__ import annotations

from praeparo.models.scoped_calculate import ScopedCalculateFilters


def test_scoped_calculate_filters_parses_shorthand_define() -> None:
    scoped = ScopedCalculateFilters.model_validate("'dim_lender'[LenderId] = 200")

    assert scoped.define == ["'dim_lender'[LenderId] = 200"]
    assert scoped.evaluate == []


def test_scoped_calculate_filters_parses_named_entries() -> None:
    scoped = ScopedCalculateFilters.model_validate(
        {
            "scope": "'dim_matter'[LoanTypeLegacy] = \"New Loan\"",
            "period": {"evaluate": "'Time Intelligence'[Period] = \"Current Month\""},
        }
    )

    assert scoped.define == ["'dim_matter'[LoanTypeLegacy] = \"New Loan\""]
    assert scoped.evaluate == ["'Time Intelligence'[Period] = \"Current Month\""]


def test_scoped_calculate_filters_parses_mixed_list() -> None:
    scoped = ScopedCalculateFilters.model_validate(
        [
            "'dim_calendar'[IsCurrent] = TRUE()",
            {"period": {"evaluate": "'Time Intelligence'[Period] = \"Current Month\""}},
        ]
    )

    assert scoped.define == ["'dim_calendar'[IsCurrent] = TRUE()"]
    assert scoped.evaluate == ["'Time Intelligence'[Period] = \"Current Month\""]


def test_scoped_calculate_filters_schema_exposes_union_inputs() -> None:
    schema = ScopedCalculateFilters.model_json_schema()

    assert "anyOf" in schema
