from __future__ import annotations

from praeparo.powerbi import _normalise_row_keys, _strip_bracket_wrappers


def test_strip_bracket_wrappers_basic() -> None:
    assert _strip_bracket_wrappers("[measure]") == "measure"


def test_strip_bracket_wrappers_with_table_prefix() -> None:
    assert _strip_bracket_wrappers("'adhoc'[measure]") == "measure"


def test_strip_bracket_wrappers_without_brackets_returns_none() -> None:
    assert _strip_bracket_wrappers("dim_calendar") is None


def test_strip_bracket_wrappers_table_column() -> None:
    assert _strip_bracket_wrappers("dim_calendar[month]") == "month"


def test_normalise_row_keys_adds_aliases() -> None:
    row = {"'adhoc'[measure]": 42}
    normalised = _normalise_row_keys(row)
    assert normalised["'adhoc'[measure]"] == 42
    assert normalised["measure"] == 42


def test_normalise_row_keys_preserves_existing_values() -> None:
    row = {"[measure]": 10, "measure": 99}
    normalised = _normalise_row_keys(row)
    assert normalised["measure"] == 99
    assert normalised["[measure]"] == 10
