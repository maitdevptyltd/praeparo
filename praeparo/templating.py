"""Template utilities for extracting field references."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
import re
from typing import Iterable, Iterator

JINJA_PLACEHOLDER = re.compile(r"\{\{\s*(?P<expr>[^}]+?)\s*\}\}")


@dataclass(frozen=True)
class FieldReference:
    """Represents a data field referenced within a Jinja placeholder."""

    expression: str
    table: str | None
    column: str

    @property
    def dax_reference(self) -> str:
        """Return the DAX column reference for this field."""

        if self.table:
            return f"{self.table}[{self.column}]"
        return f"[{self.column}]"

    @property
    def placeholder(self) -> str:
        """Return the canonical placeholder expression."""

        if self.table:
            return f"{self.table}.{self.column}"
        return self.column


def _clean_expression(expression: str) -> str:
    base = expression.split("|", 1)[0].strip()
    return base


def _parse_field(expression: str) -> FieldReference:
    base = _clean_expression(expression)
    if not base:
        msg = "Encountered empty Jinja placeholder."
        raise ValueError(msg)

    if "." in base:
        table, column = base.split(".", 1)
        table = table.strip() or None
        column = column.strip()
    else:
        table, column = None, base

    if not column:
        msg = f"Invalid field expression: {expression!r}"
        raise ValueError(msg)

    return FieldReference(expression=base, table=table, column=column)


def iter_field_references(template: str) -> Iterator[FieldReference]:
    """Yield field references in the order they appear within *template*."""

    for match in JINJA_PLACEHOLDER.finditer(template):
        yield _parse_field(match.group("expr"))


def extract_field_references(templates: Iterable[str]) -> list[FieldReference]:
    """Extract unique field references from the provided templates preserving order."""

    ordered: "OrderedDict[str, FieldReference]" = OrderedDict()
    for template in templates:
        for reference in iter_field_references(template):
            ordered.setdefault(reference.expression, reference)
    return list(ordered.values())


__all__ = ["FieldReference", "extract_field_references", "iter_field_references"]
