from __future__ import annotations

from praeparo.models.scoped_calculate import ScopedCalculateMap


def test_scoped_calculate_map_parses_shorthand_define() -> None:
    scoped = ScopedCalculateMap.from_raw({"month": "'dim_calendar'[month] = DATEVALUE(\"2025-11-01\")"})

    assert scoped.flatten_define() == ["'dim_calendar'[month] = DATEVALUE(\"2025-11-01\")"]
    assert scoped.flatten_evaluate() == []


def test_scoped_calculate_map_parses_evaluate_entries() -> None:
    scoped = ScopedCalculateMap.from_raw({"period": {"evaluate": "'Time Intelligence'[Period] = \"Current Month\""}})

    assert scoped.flatten_define() == []
    assert scoped.flatten_evaluate() == ["'Time Intelligence'[Period] = \"Current Month\""]


def test_scoped_calculate_map_merge_overrides_by_scope() -> None:
    root = ScopedCalculateMap.from_raw(
        {
            "period": {
                "define": "fact_documents[DummyDefine] = 1",
                "evaluate": "'Time Intelligence'[Period] = \"Current Month\"",
            }
        }
    )
    slide = ScopedCalculateMap.from_raw(
        {
            "period": {
                "evaluate": "'Time Intelligence'[Period] = \"Prior Month\"",
            }
        }
    )

    merged = ScopedCalculateMap.merge(root, slide)

    assert merged.root["period"].define == ["fact_documents[DummyDefine] = 1"]
    assert merged.root["period"].evaluate == ["'Time Intelligence'[Period] = \"Prior Month\""]


def test_scoped_calculate_map_merge_preserves_unlabelled_list_semantics() -> None:
    root = ScopedCalculateMap.from_raw(["A", "B"])
    slide = ScopedCalculateMap.from_raw(["C"])

    merged = ScopedCalculateMap.merge(root, slide)

    assert merged.flatten_define() == ["A", "B", "C"]
    assert merged.flatten_evaluate() == []
