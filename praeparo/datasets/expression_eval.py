"""Evaluate parsed metric expressions against numeric substitutions."""

from __future__ import annotations

import ast
from typing import Mapping

from praeparo.visuals.dax.expressions import ParsedExpression

_EXPRESSION_CALL_ALIASES = {
    "MIN": "min",
    "MAX": "max",
}


def evaluate_expression(parsed: ParsedExpression, substitutions: Mapping[str, float]) -> float | None:
    """Evaluate *parsed* using numeric substitutions for each referenced identifier."""

    env: dict[str, float] = {}
    for reference in parsed.references:
        value = substitutions.get(reference.identifier)
        if value is not None:
            env[reference.identifier] = float(value)
    return _evaluate_node(parsed.root, env)


def _evaluate_node(node: ast.AST, env: Mapping[str, float]) -> float | None:
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, env)
        right = _evaluate_node(node.right, env)
        if left is None or right is None:
            return None
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right if right else 0.0
        msg = f"Unsupported binary operator: {ast.dump(node.op)}"
        raise ValueError(msg)
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate_node(node.operand, env)
        if operand is None:
            return None
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        msg = f"Unsupported unary operator: {ast.dump(node.op)}"
        raise ValueError(msg)
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, (int, float)):
            return float(value)
        msg = f"Unsupported constant type: {type(value)!r}"
        raise TypeError(msg)
    if isinstance(node, ast.Name):
        return env.get(node.id, 0.0)
    if isinstance(node, ast.Attribute):
        identifier = _flatten_attribute(node)
        return env.get(identifier, 0.0)
    if isinstance(node, ast.Call):
        func = _parse_expression_call(node)
        if func == "ratio_to":
            numerator_id, denominator_id, fallback_value = _parse_ratio_to_call(node)
            numerator_value = env.get(numerator_id)
            denominator_value = env.get(denominator_id)
            if denominator_value is None or denominator_value == 0:
                return float(fallback_value) if fallback_value is not None else None
            if numerator_value is None:
                return None
            return float(numerator_value) / float(denominator_value)

        if node.keywords:
            raise TypeError(f"{func}() does not accept keyword arguments.")
        if len(node.args) < 2:
            raise ValueError(f"{func}() requires at least two arguments.")

        values: list[float] = []
        for arg in node.args:
            value = _evaluate_node(arg, env)
            if value is None:
                return None
            values.append(float(value))
        return min(values) if func == "min" else max(values)
    msg = f"Unsupported expression node: {ast.dump(node)}"
    raise TypeError(msg)


def _flatten_attribute(node: ast.Attribute) -> str:
    parts: list[str] = []
    current: ast.AST | None = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def _parse_ratio_to_call(node: ast.Call) -> tuple[str, str, float | int | None]:
    if not isinstance(node.func, ast.Name) or node.func.id != "ratio_to":
        raise TypeError("Only ratio_to() calls are supported in expressions.")
    if node.keywords:
        raise TypeError("ratio_to() does not accept keyword arguments.")
    if len(node.args) not in (1, 2, 3):
        raise ValueError("ratio_to() requires one, two, or three arguments.")

    numerator_id = _flatten_metric_identifier(node.args[0])

    if len(node.args) == 1:
        if "." not in numerator_id:
            raise ValueError("ratio_to() requires a dotted metric key to infer the parent denominator.")
        denominator_id = numerator_id.rsplit(".", 1)[0]
        return numerator_id, denominator_id, None

    second_arg = node.args[1]
    if len(node.args) == 2:
        if isinstance(second_arg, ast.Constant) and isinstance(second_arg.value, str):
            denominator_id = second_arg.value.strip()
            if not denominator_id:
                raise ValueError("Second argument to ratio_to() must be a non-empty string metric key.")
            return numerator_id, denominator_id, None

        fallback_value = _parse_numeric_literal(second_arg, argument_name="Second")
        if "." not in numerator_id:
            raise ValueError("ratio_to() requires a dotted metric key to infer the parent denominator.")
        denominator_id = numerator_id.rsplit(".", 1)[0]
        return numerator_id, denominator_id, fallback_value

    if not isinstance(second_arg, ast.Constant) or not isinstance(second_arg.value, str):
        raise TypeError("Second argument to ratio_to() must be a string metric key when a fallback is provided.")

    denominator_id = second_arg.value.strip()
    if not denominator_id:
        raise ValueError("Second argument to ratio_to() must be a non-empty string metric key.")

    fallback_value = _parse_numeric_literal(node.args[2], argument_name="Third")
    return numerator_id, denominator_id, fallback_value


def _parse_expression_call(node: ast.Call) -> str:
    if not isinstance(node.func, ast.Name):
        raise TypeError("Only ratio_to(), min(), max(), MIN(), and MAX() calls are supported in expressions.")

    name = _EXPRESSION_CALL_ALIASES.get(node.func.id, node.func.id)
    if name not in ("ratio_to", "min", "max"):
        raise TypeError("Only ratio_to(), min(), max(), MIN(), and MAX() calls are supported in expressions.")
    return name


def _flatten_metric_identifier(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return _flatten_attribute(node)
    raise TypeError("First argument to ratio_to() must be a metric reference.")


def _parse_numeric_literal(node: ast.AST, *, argument_name: str) -> float | int:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value

    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        operand = node.operand
        if isinstance(operand, ast.Constant) and isinstance(operand.value, (int, float)) and not isinstance(
            operand.value, bool
        ):
            numeric_value: float | int = operand.value
            if isinstance(node.op, ast.USub):
                return -numeric_value
            return +numeric_value

    raise TypeError(f"{argument_name} argument to ratio_to() must be a numeric literal.")


__all__ = ["evaluate_expression"]
