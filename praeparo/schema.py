"""Utilities for exporting JSON schemas from Praeparo models."""

from __future__ import annotations

import argparse
import copy
import json
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from .metrics import MetricDefinition
from .metrics.components import MetricComponentDocument
from .models import CartesianChartConfig, FrameConfig, MatrixConfig, PackConfig
from .models.powerbi import PowerBIVisualConfig
from .visuals.context_schema import ContextLayerDocument
from .visuals.registry import iter_visual_schema_registrations

DEFAULT_VISUAL_UMBRELLA_SCHEMA_PATH = Path("schemas/visual_umbrella.schema.json")
_BUILT_IN_VISUAL_TYPES = {"matrix", "frame", "column", "bar", "powerbi"}
DEFAULT_COMPONENT_SCHEMA_PATH = Path("schemas/components.json")
DEFAULT_CONTEXT_LAYER_SCHEMA_PATH = Path("schemas/context_layer.json")


def _compose_property_schema() -> dict[str, Any]:
    return {
        "title": "Compose",
        "description": "List of additional YAML files to merge before validation.",
        "anyOf": [
            {"type": "string"},
            {"type": "array", "items": {"type": "string"}},
        ],
    }


def _authoring_parameters_property_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "title": "Parameters",
        "description": "Template values injected into the configuration before validation.",
        "additionalProperties": {"type": "string"},
        "default": {},
    }


def _inject_compose_property(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.setdefault("properties", {})
    properties.setdefault("compose", _compose_property_schema())
    return schema


def _inject_authoring_parameters_property(schema: dict[str, Any]) -> dict[str, Any]:
    properties = schema.setdefault("properties", {})
    if "parameters" not in properties:
        properties["parameters"] = _authoring_parameters_property_schema()
    return schema


def matrix_json_schema() -> dict[str, Any]:
    """Return the JSON schema for matrix configurations."""

    schema = MatrixConfig.model_json_schema()
    _inject_authoring_parameters_property(schema)
    _inject_compose_property(schema)
    return schema


def metric_json_schema() -> dict[str, Any]:
    """Return the JSON schema for metric definitions."""

    return MetricDefinition.model_json_schema()


def component_json_schema() -> dict[str, Any]:
    """Return the JSON schema for metric component documents."""

    return MetricComponentDocument.model_json_schema()


def context_layer_json_schema() -> dict[str, Any]:
    """Return the JSON schema for generic context-layer documents."""

    return ContextLayerDocument.model_json_schema()


def pack_json_schema() -> dict[str, Any]:
    """Return the JSON schema for pack configurations."""

    return PackConfig.model_json_schema()


def _write_schema(path: Path, schema: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")


def write_matrix_schema(path: Path) -> None:
    """Write the matrix configuration schema to *path*."""

    _write_schema(path, matrix_json_schema())


def write_metric_schema(path: Path) -> None:
    """Write the metric definition schema to *path*."""

    _write_schema(path, metric_json_schema())


def write_component_schema(path: Path) -> None:
    """Write the metric component schema to *path*."""

    _write_schema(path, component_json_schema())


def write_context_layer_schema(path: Path) -> None:
    """Write the generic context-layer schema to *path*."""

    _write_schema(path, context_layer_json_schema())


def write_pack_schema(path: Path) -> None:
    """Write the pack configuration schema to *path*."""

    _write_schema(path, pack_json_schema())


def cartesian_json_schema() -> dict[str, Any]:
    """Return the JSON schema for cartesian chart configurations."""

    schema = CartesianChartConfig.model_json_schema()
    _inject_authoring_parameters_property(schema)
    _inject_compose_property(schema)
    return schema


def write_cartesian_schema(path: Path) -> None:
    """Write the cartesian chart configuration schema to *path*."""

    _write_schema(path, cartesian_json_schema())


def _extract_type_values(schema: Mapping[str, Any]) -> tuple[str, ...]:
    properties = schema.get("properties")
    if not isinstance(properties, Mapping):
        raise ValueError("Visual schemas must define top-level properties.")
    type_schema = properties.get("type")
    if not isinstance(type_schema, Mapping):
        raise ValueError("Visual schemas must define a top-level type discriminator.")
    const_value = type_schema.get("const")
    if isinstance(const_value, str) and const_value.strip():
        return (const_value.strip(),)
    enum_values = type_schema.get("enum")
    if isinstance(enum_values, Sequence) and not isinstance(enum_values, (str, bytes)):
        values = tuple(
            value.strip()
            for value in enum_values
            if isinstance(value, str) and value.strip()
        )
        if values:
            return values
    default_value = type_schema.get("default")
    if isinstance(default_value, str) and default_value.strip():
        return (default_value.strip(),)
    raise ValueError("Visual schemas must declare discriminator values via type.const, type.enum, or type.default.")


def _rewrite_refs(value: Any, *, prefix: str) -> Any:
    if isinstance(value, dict):
        rewritten: dict[str, Any] = {}
        for key, item in value.items():
            if key == "$ref" and isinstance(item, str) and item.startswith("#/$defs/"):
                rewritten[key] = f"#/$defs/{prefix}{item.removeprefix('#/$defs/')}"
            else:
                rewritten[key] = _rewrite_refs(item, prefix=prefix)
        return rewritten
    if isinstance(value, list):
        return [_rewrite_refs(item, prefix=prefix) for item in value]
    return value


def _safe_schema_key(raw_key: str) -> str:
    cleaned = re.sub(r"[^0-9A-Za-z_]+", "_", raw_key).strip("_")
    return cleaned or "VisualSchema"


def _build_visual_branch_schema(
    schema_key: str,
    schema: dict[str, Any],
    *,
    include_compose: bool,
    authoring_parameters: bool,
) -> tuple[str, dict[str, Any], dict[str, Any], tuple[str, ...]]:
    branch_schema = copy.deepcopy(schema)
    if include_compose:
        _inject_compose_property(branch_schema)
    if authoring_parameters:
        _inject_authoring_parameters_property(branch_schema)

    type_values = _extract_type_values(branch_schema)
    prefix = f"{_safe_schema_key(schema_key)}__"
    branch_defs = branch_schema.pop("$defs", {})
    branch_root = _rewrite_refs(branch_schema, prefix=prefix)
    rewritten_defs = {
        f"{prefix}{name}": _rewrite_refs(definition, prefix=prefix)
        for name, definition in branch_defs.items()
    }
    return _safe_schema_key(schema_key), branch_root, rewritten_defs, type_values


def visual_umbrella_json_schema() -> dict[str, Any]:
    """Return a deterministic umbrella schema for supported visual YAML families."""

    mapping: dict[str, str] = {}
    definitions: dict[str, Any] = {}
    one_of: list[dict[str, str]] = []

    branch_specs: list[tuple[str, dict[str, Any], bool, bool]] = [
        ("MatrixConfig", MatrixConfig.model_json_schema(), True, True),
        ("FrameConfig", FrameConfig.model_json_schema(), True, True),
        ("CartesianChartConfig", CartesianChartConfig.model_json_schema(), True, True),
        ("PowerBIVisualConfig", PowerBIVisualConfig.model_json_schema(), True, False),
    ]

    for type_name, registration in sorted(iter_visual_schema_registrations(), key=lambda item: item[0]):
        if type_name in _BUILT_IN_VISUAL_TYPES:
            continue
        branch_specs.append(
            (
                f"{type_name}_visual",
                registration.build_schema(),
                registration.include_compose,
                registration.authoring_parameters,
            )
        )

    for schema_key, schema, include_compose, authoring_parameters in branch_specs:
        resolved_key, branch_root, branch_defs, type_values = _build_visual_branch_schema(
            schema_key,
            schema,
            include_compose=include_compose,
            authoring_parameters=authoring_parameters,
        )

        if resolved_key in definitions:
            msg = f"Visual umbrella schema key collision: {resolved_key}"
            raise ValueError(msg)

        definitions[resolved_key] = branch_root
        definitions.update(branch_defs)
        branch_ref = f"#/$defs/{resolved_key}"
        one_of.append({"$ref": branch_ref})

        for type_value in type_values:
            if type_value in mapping:
                msg = f"Visual umbrella schema already defines type '{type_value}'."
                raise ValueError(msg)
            mapping[type_value] = branch_ref

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "PraeparoVisualUmbrellaConfig",
        "description": (
            "Conditional YAML schema for Praeparo visual definitions. Branches are selected "
            "by the top-level 'type' field."
        ),
        "discriminator": {
            "propertyName": "type",
            "mapping": mapping,
        },
        "oneOf": one_of,
        "$defs": definitions,
    }


def write_visual_umbrella_schema(path: Path = DEFAULT_VISUAL_UMBRELLA_SCHEMA_PATH) -> None:
    """Write the umbrella visual schema to *path*."""

    _write_schema(path, visual_umbrella_json_schema())


def run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Export Praeparo JSON schemas.")
    parser.add_argument(
        "dest",
        nargs="?",
        type=Path,
        help="Destination for the visual umbrella schema JSON file.",
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=None,
        help="Destination for the matrix schema JSON file.",
    )
    parser.add_argument(
        "--charts",
        type=Path,
        default=None,
        help="Destination for the cartesian chart schema JSON file (omit to skip).",
    )
    parser.add_argument(
        "--metrics",
        type=Path,
        default=None,
        help="Destination for the metric schema JSON file (omit to skip).",
    )
    parser.add_argument(
        "--components",
        type=Path,
        default=None,
        help=(
            "Destination for the metric component schema JSON file "
            f"(omit to skip; committed artefact typically {DEFAULT_COMPONENT_SCHEMA_PATH})."
        ),
    )
    parser.add_argument(
        "--context-layer",
        type=Path,
        default=None,
        help=(
            "Destination for the generic context-layer schema JSON file "
            f"(omit to skip; committed artefact typically {DEFAULT_CONTEXT_LAYER_SCHEMA_PATH})."
        ),
    )
    parser.add_argument(
        "--pack",
        type=Path,
        default=None,
        help="Destination for the pack schema JSON file (omit to skip).",
    )
    args = parser.parse_args(argv)

    advanced_targets = {
        "matrix": args.matrix,
        "charts": args.charts,
        "metrics": args.metrics,
        "components": args.components,
        "context_layer": args.context_layer,
        "pack": args.pack,
    }
    if any(target is not None for target in advanced_targets.values()):
        if args.dest is not None:
            parser.error(
                "positional dest cannot be combined with "
                "--matrix/--charts/--metrics/--components/--context-layer/--pack"
            )

        # Advanced exports are explicit on purpose. Each flag writes only the schema
        # it names so specialized tooling can refresh one contract without mutating
        # sibling artefacts as a side effect.
        if args.matrix is not None:
            write_matrix_schema(args.matrix)
            print(f"Wrote matrix schema to {args.matrix}")

        if args.charts is not None:
            write_cartesian_schema(args.charts)
            print(f"Wrote cartesian schema to {args.charts}")

        if args.metrics is not None:
            write_metric_schema(args.metrics)
            print(f"Wrote metric schema to {args.metrics}")

        if args.components is not None:
            write_component_schema(args.components)
            print(f"Wrote metric component schema to {args.components}")

        if args.context_layer is not None:
            write_context_layer_schema(args.context_layer)
            print(f"Wrote context-layer schema to {args.context_layer}")

        if args.pack is not None:
            write_pack_schema(args.pack)
            print(f"Wrote pack schema to {args.pack}")

        return 0

    destination = args.dest or DEFAULT_VISUAL_UMBRELLA_SCHEMA_PATH
    write_visual_umbrella_schema(destination)
    print(f"Wrote visual umbrella schema to {destination}")
    return 0


def main() -> None:
    raise SystemExit(run())


__all__ = [
    "DEFAULT_COMPONENT_SCHEMA_PATH",
    "DEFAULT_CONTEXT_LAYER_SCHEMA_PATH",
    "DEFAULT_VISUAL_UMBRELLA_SCHEMA_PATH",
    "cartesian_json_schema",
    "component_json_schema",
    "context_layer_json_schema",
    "matrix_json_schema",
    "metric_json_schema",
    "pack_json_schema",
    "visual_umbrella_json_schema",
    "write_cartesian_schema",
    "write_component_schema",
    "write_context_layer_schema",
    "write_matrix_schema",
    "write_metric_schema",
    "write_pack_schema",
    "write_visual_umbrella_schema",
    "run",
    "main",
]


if __name__ == "__main__":
    main()
