"""Evaluate parsed metric expressions against numeric substitutions."""

from __future__ import annotations

import ast
from typing import Mapping

from praeparo.visuals.dax.expressions import ParsedExpression


def evaluate_expression(parsed: ParsedExpression, substitutions: Mapping[str, float]) -> float:
    """Evaluate *parsed* using numeric substitutions for each referenced identifier."""

    env: dict[str, float] = {}
    for reference in parsed.references:
        value = substitutions.get(reference.identifier)
        if value is not None:
            env[reference.identifier] = float(value)
    return _evaluate_node(parsed.root, env)


def _evaluate_node(node: ast.AST, env: Mapping[str, float]) -> float:
    if isinstance(node, ast.BinOp):
        left = _evaluate_node(node.left, env)
        right = _evaluate_node(node.right, env)
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


__all__ = ["evaluate_expression"]
