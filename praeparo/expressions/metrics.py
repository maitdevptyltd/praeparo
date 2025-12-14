"""Parse and compile registry/visual metric expressions.

This module owns the lightweight arithmetic expression language used by Praeparo.
It lives in a neutral package so `MetricDaxBuilder` can compile expression-based
registry metrics without importing visual-specific modules, avoiding circular
imports. Visuals continue to re-export these symbols from
`praeparo.visuals.dax.expressions` for backward compatibility.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Dict, List, Mapping, TYPE_CHECKING

from praeparo.utils import normalize_dax_expression
from praeparo.visuals.dax.utils import split_metric_identifier

if TYPE_CHECKING:
    from praeparo.metrics.dax import MetricDaxBuilder, MetricMeasureDefinition
    from praeparo.visuals.dax.cache import MetricCompilationCache

_BINOP_SYMBOLS = {
    ast.Add: "+",
    ast.Sub: "-",
    ast.Mult: "*",
    ast.Div: "/",
}

_UNARY_SYMBOLS = {
    ast.UAdd: "+",
    ast.USub: "-",
}

_EXPRESSION_CALL_ALIASES = {
    "MIN": "min",
    "MAX": "max",
}

_EXPRESSION_CALLS = {
    "ratio_to",
    "min",
    "max",
}


@dataclass(frozen=True)
class MetricReference:
    """Reference to a metric or variant referenced inside an expression."""

    identifier: str
    ratio_to_ref: str | None = None


@dataclass(frozen=True)
class ParsedExpression:
    """Parsed representation of an expression plus its metric dependencies."""

    root: ast.AST
    references: List[MetricReference]

    def to_dax(self, substitutions: Mapping[str, str]) -> str:
        """Render the parsed expression to DAX using *substitutions*."""

        missing = [ref.identifier for ref in self.references if ref.identifier not in substitutions]
        if missing:
            names = ", ".join(f"'{name}'" for name in missing)
            raise KeyError(f"Missing DAX substitution(s) for expression reference(s): {names}")

        call_counter = 0

        def _emit(node: ast.AST) -> str:
            nonlocal call_counter

            if isinstance(node, ast.BinOp):
                operator = _BINOP_SYMBOLS.get(type(node.op))
                if operator is None:
                    raise ValueError(f"Operator '{ast.dump(node.op)}' is not supported.")
                left = _emit(node.left)
                right = _emit(node.right)
                return f"({left} {operator} {right})"
            if isinstance(node, ast.UnaryOp):
                operator = _UNARY_SYMBOLS.get(type(node.op))
                if operator is None:
                    raise ValueError(f"Unary operator '{ast.dump(node.op)}' is not supported.")
                operand = _emit(node.operand)
                return f"{operator}{operand}"
            if isinstance(node, ast.Constant):
                value = node.value
                if isinstance(value, (int, float)):
                    return str(value)
                raise TypeError(f"Unsupported constant type: {type(value)!r}")
            if isinstance(node, ast.Name):
                identifier = node.id
                return f"({substitutions[identifier]})"
            if isinstance(node, ast.Attribute):
                identifier = _flatten_attribute(node)
                return f"({substitutions[identifier]})"
            if isinstance(node, ast.Call):
                func = _parse_expression_call(node)
                if func == "ratio_to":
                    numerator_id, _ = _parse_ratio_to_call(node)
                    denominator_id = _lookup_ratio_to_denominator(self.references, numerator_id)
                    numerator_expr = f"({substitutions[numerator_id]})"
                    denominator_expr = f"({substitutions[denominator_id]})"
                    return f"DIVIDE({numerator_expr}, {denominator_expr})"

                if node.keywords:
                    raise TypeError(f"{func}() does not accept keyword arguments.")
                if len(node.args) < 2:
                    raise ValueError(f"{func}() requires at least two arguments.")

                call_counter += 1
                values_var = f"__values_{call_counter}"
                values_expr = ", ".join(_emit(arg) for arg in node.args)
                reducer = "MINX" if func == "min" else "MAXX"

                # Keep blank propagation explicit so clamp-style expressions do not
                # convert missing ratios into a misleading "met" score.
                return (
                    "("
                    f"VAR {values_var} = {{{values_expr}}} "
                    f"RETURN IF("
                    f"COUNTROWS(FILTER({values_var}, ISBLANK([Value]))) > 0, "
                    "BLANK(), "
                    f"{reducer}({values_var}, [Value])"
                    ")"
                    ")"
                )
            raise TypeError(f"Unsupported expression node: {ast.dump(node)}")

        return _emit(self.root)


def parse_metric_expression(expression: str) -> ParsedExpression:
    """Parse *expression* into an AST ensuring only supported constructs exist."""

    if not expression:
        raise ValueError("Expression cannot be empty.")

    tree = ast.parse(expression, mode="eval")
    parser = _ExpressionVisitor()
    parser.visit(tree.body)
    return ParsedExpression(root=tree.body, references=parser.references)


def resolve_expression_metric(
    *,
    metric_key: str,
    expression: str,
    builder: "MetricDaxBuilder",
    cache: "MetricCompilationCache",
    label: str | None = None,
    value_type: str = "number",
) -> "MetricMeasureDefinition":
    """Compile an inline expression metric into a measure definition."""

    # Delay imports so MetricDaxBuilder can import this module without triggering
    # praeparo.visuals.* → praeparo.metrics.* circular dependencies.
    from praeparo.metrics.dax import MetricMeasureDefinition
    from praeparo.visuals.dax.cache import resolve_metric_reference

    parsed = parse_metric_expression(expression)
    substitutions: dict[str, str] = {}

    for reference in parsed.references:
        if reference.identifier == metric_key:
            raise ValueError(f"Expression metric '{metric_key}' cannot reference itself.")
        base_key, variant_path = split_metric_identifier(reference.identifier)
        _, definition = resolve_metric_reference(
            builder=builder,
            cache=cache,
            metric_key=base_key,
            variant_path=variant_path,
        )
        substitutions[reference.identifier] = definition.expression

    dax_expression = parsed.to_dax(substitutions)
    expression_text = normalize_dax_expression(dax_expression)
    return MetricMeasureDefinition(
        key=metric_key,
        label=label or metric_key,
        expression=expression_text,
        filters=tuple(),
        description=None,
        variant_path=None,
        value_type=value_type,
    )


class _ExpressionVisitor(ast.NodeVisitor):
    """Validate nodes and capture metric references in encounter order."""

    def __init__(self) -> None:
        self._references: List[MetricReference] = []
        self._seen: Dict[str, MetricReference] = {}

    @property
    def references(self) -> List[MetricReference]:
        return list(self._references)

    def visit_BinOp(self, node: ast.BinOp) -> None:  # noqa: N802 - AST naming
        if type(node.op) not in _BINOP_SYMBOLS:
            raise ValueError(f"Operator '{ast.dump(node.op)}' is not supported.")
        self.visit(node.left)
        self.visit(node.right)

    def visit_UnaryOp(self, node: ast.UnaryOp) -> None:  # noqa: N802
        if type(node.op) not in _UNARY_SYMBOLS:
            raise ValueError(f"Unary operator '{ast.dump(node.op)}' is not supported.")
        self.visit(node.operand)

    def visit_Constant(self, node: ast.Constant) -> None:  # noqa: N802
        if not isinstance(node.value, (int, float)):
            raise TypeError(f"Unsupported constant type: {type(node.value)!r}")

    def visit_Name(self, node: ast.Name) -> None:  # noqa: N802
        identifier = node.id
        self._record_reference(identifier)

    def visit_Attribute(self, node: ast.Attribute) -> None:  # noqa: N802
        identifier = _flatten_attribute(node)
        self._record_reference(identifier)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        func = _parse_expression_call(node)
        if func in ("min", "max"):
            if node.keywords:
                raise TypeError(f"{func}() does not accept keyword arguments.")
            if len(node.args) < 2:
                raise ValueError(f"{func}() requires at least two arguments.")

            for arg in node.args:
                self.visit(arg)
            return

        numerator_id, denominator_id = _parse_ratio_to_call(node)

        # Record denominator first so dependency discovery works even if the only
        # mention is inside a ratio_to() call.
        self._record_reference(denominator_id)
        self._record_reference(numerator_id, ratio_to_ref=denominator_id)

    def _record_reference(self, identifier: str, *, ratio_to_ref: str | None = None) -> None:
        existing = self._seen.get(identifier)
        if existing is None:
            ref = MetricReference(identifier=identifier, ratio_to_ref=ratio_to_ref)
            self._references.append(ref)
            self._seen[identifier] = ref
            return

        if ratio_to_ref is None:
            return

        if existing.ratio_to_ref is None:
            updated = MetricReference(identifier=identifier, ratio_to_ref=ratio_to_ref)
            index = self._references.index(existing)
            self._references[index] = updated
            self._seen[identifier] = updated
            return

        if existing.ratio_to_ref != ratio_to_ref:
            raise ValueError(
                f"ratio_to() cannot be called multiple times for '{identifier}' "
                "with different denominators."
            )

    def generic_visit(self, node: ast.AST) -> None:  # noqa: D401
        raise TypeError(f"Unsupported expression node: {ast.dump(node)}")


def _flatten_attribute(node: ast.Attribute) -> str:
    """Flatten nested attribute chains into dotted metric identifiers."""

    parts: List[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    else:
        raise TypeError(f"Unsupported attribute structure: {ast.dump(node)}")
    return ".".join(reversed(parts))


def _parse_ratio_to_call(node: ast.Call) -> tuple[str, str]:
    """Validate and extract identifiers from a ratio_to() call."""

    if not isinstance(node.func, ast.Name) or node.func.id != "ratio_to":
        raise TypeError("Only ratio_to() calls are supported by this helper.")
    if node.keywords:
        raise TypeError("ratio_to() does not accept keyword arguments.")
    if len(node.args) not in (1, 2):
        raise ValueError("ratio_to() requires one or two arguments.")

    numerator_id = _flatten_metric_identifier(node.args[0])

    if len(node.args) == 1:
        if "." not in numerator_id:
            raise ValueError("ratio_to() requires a dotted metric key to infer the parent denominator.")
        denominator_id = numerator_id.rsplit(".", 1)[0]
        return numerator_id, denominator_id

    denominator_arg = node.args[1]
    if not isinstance(denominator_arg, ast.Constant) or not isinstance(denominator_arg.value, str):
        raise TypeError("Second argument to ratio_to() must be a string metric key.")

    denominator_id = denominator_arg.value.strip()
    if not denominator_id:
        raise ValueError("Second argument to ratio_to() must be a non-empty string metric key.")
    return numerator_id, denominator_id


def _parse_expression_call(node: ast.Call) -> str:
    if not isinstance(node.func, ast.Name):
        raise TypeError(_unsupported_expression_call_message())

    name = _EXPRESSION_CALL_ALIASES.get(node.func.id, node.func.id)
    if name not in _EXPRESSION_CALLS:
        raise TypeError(_unsupported_expression_call_message())
    return name


def _unsupported_expression_call_message() -> str:
    supported = ["ratio_to()", "min()", "max()", "MIN()", "MAX()"]
    formatted = ", ".join(f"`{name}`" for name in supported)
    return f"Only {formatted} calls are supported in expressions."


def _flatten_metric_identifier(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _flatten_attribute(node)
    raise TypeError("First argument to ratio_to() must be a metric reference.")


def _lookup_ratio_to_denominator(references: List[MetricReference], numerator_id: str) -> str:
    for reference in references:
        if reference.identifier == numerator_id and reference.ratio_to_ref:
            return reference.ratio_to_ref
    raise KeyError(f"ratio_to() denominator could not be resolved for '{numerator_id}'.")


__all__ = ["MetricReference", "ParsedExpression", "parse_metric_expression", "resolve_expression_metric"]
