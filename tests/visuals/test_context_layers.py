from __future__ import annotations

from pathlib import Path

import pytest

from praeparo.pack.templating import create_pack_jinja_env, render_value
from praeparo.visuals.context_layers import discover_registry_context_paths, resolve_layered_context_payload
from praeparo.visuals.context import resolve_dax_context


def test_discover_registry_context_paths_sorts_by_relative_path(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    context_root = tmp_path / "registry" / "context"
    context_root.mkdir(parents=True)
    (context_root / "b.yaml").write_text("define: \"VAR B = 1\"\n", encoding="utf-8")
    (context_root / "a.yaml").write_text("define: \"VAR A = 1\"\n", encoding="utf-8")
    (context_root / "nested").mkdir()
    (context_root / "nested" / "c.yaml").write_text("define: \"VAR C = 1\"\n", encoding="utf-8")

    paths = discover_registry_context_paths(metrics_root=metrics_root)

    assert [path.relative_to(context_root).as_posix() for path in paths] == ["a.yaml", "b.yaml", "nested/c.yaml"]


def test_resolve_layered_context_payload_applies_registry_layers_in_order(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    context_root = tmp_path / "registry" / "context"
    context_root.mkdir(parents=True)
    (context_root / "a.yaml").write_text("define: \"VAR A = 1\"\n", encoding="utf-8")
    (context_root / "nested").mkdir()
    (context_root / "nested" / "b.yaml").write_text("define: \"VAR B = 1\"\n", encoding="utf-8")

    payload = resolve_layered_context_payload(metrics_root=metrics_root, env=create_pack_jinja_env())

    assert payload["define"] == ["VAR A = 1", "VAR B = 1"]


def test_resolve_layered_context_payload_last_context_wins_for_named_define(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    first = tmp_path / "first.yaml"
    first.write_text(
        "\n".join(
            [
                "define:",
                "  get_business_hours: \"FUNCTION GetCustomerBusinessHours = () => 1\"",
                "  business_time_holidays: \"VAR Holidays = 1\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    second = tmp_path / "second.yaml"
    second.write_text(
        "\n".join(
            [
                "define:",
                "  get_business_hours: \"FUNCTION GetCustomerBusinessHours = () => 2\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = resolve_layered_context_payload(
        metrics_root=metrics_root,
        context_paths=[first, second],
        env=create_pack_jinja_env(),
    )

    _, define_blocks = resolve_dax_context(base=payload, calculate=None, define=None)
    assert define_blocks == (
        "FUNCTION GetCustomerBusinessHours = () => 2",
        "VAR Holidays = 1",
    )


def test_resolve_layered_context_payload_rejects_unrendered_templates(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    with pytest.raises(ValueError, match="Unrendered Jinja template tokens"):
        resolve_layered_context_payload(
            metrics_root=metrics_root,
            define=["{{ broken }}"],
            env=create_pack_jinja_env(),
        )


def test_resolve_layered_context_payload_hoists_mapping_context_keys_for_non_pack_layers(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    context_root = tmp_path / "registry" / "context"
    context_root.mkdir(parents=True)
    (context_root / "month.yaml").write_text(
        "\n".join(
            [
                "context:",
                "  month: \"2025-11-01\"",
                "  display_date: \"November 2025\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    payload = resolve_layered_context_payload(metrics_root=metrics_root, env=create_pack_jinja_env())

    assert payload["month"] == "2025-11-01"
    assert payload["display_date"] == "November 2025"

    context_section = payload.get("context")
    assert isinstance(context_section, dict)
    assert context_section["month"] == "2025-11-01"


def test_render_value_can_use_hoisted_registry_context_keys(tmp_path: Path) -> None:
    metrics_root = tmp_path / "registry" / "metrics"
    metrics_root.mkdir(parents=True)

    context_root = tmp_path / "registry" / "context"
    context_root.mkdir(parents=True)
    (context_root / "month.yaml").write_text(
        "\n".join(
            [
                "context:",
                "  month: \"2025-11-01\"",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    env = create_pack_jinja_env()
    payload = resolve_layered_context_payload(metrics_root=metrics_root, env=env)

    rendered = render_value(
        "{{ odata_months_back_range('x', month, 3) }}",
        env=env,
        context=payload,
    )

    assert isinstance(rendered, str)
    assert "x ge " in rendered
