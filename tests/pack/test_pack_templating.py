from __future__ import annotations

from praeparo.pack.templating import create_pack_jinja_env, render_value


def test_render_value_handles_nested_structures() -> None:
    env = create_pack_jinja_env()
    payload = {
        "outer": {"inner": "Value is {{ lender_id }}"},
        "list": ["{{ month }}", "static"],
    }

    rendered = render_value(payload, env=env, context={"lender_id": 7, "month": "2025-11-01"})

    assert rendered["outer"]["inner"] == "Value is 7"
    assert rendered["list"][0] == "2025-11-01"
    assert rendered["list"][1] == "static"
