"""Parse lightweight metric expressions into reusable AST structures."""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Dict, List, Mapping

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


@dataclass(frozen=True)
class MetricReference:
    """Reference to a metric or variant referenced inside an expression."""

    identifier: str


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

        def _emit(node: ast.AST) -> str:
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

    def _record_reference(self, identifier: str) -> None:
        if identifier not in self._seen:
            ref = MetricReference(identifier=identifier)
            self._references.append(ref)
            self._seen[identifier] = ref

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


__all__ = ["MetricReference", "ParsedExpression", "parse_metric_expression"]
