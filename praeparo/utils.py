"""Shared utility helpers for DAX expression handling."""

from __future__ import annotations

import re


_FIELD_PATTERN = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\.([A-Za-z_][A-Za-z0-9_]*)\b")


def normalize_dax_expression(expression: str) -> str:
    """Return *expression* with dotted field references converted to bracketed DAX.

    Example:
        ``fact_events.IsAutomated`` → ``'fact_events'[IsAutomated]``

    Already bracketed references are left untouched. String literals and
    function names remain unchanged.
    """

    def replace(match: re.Match[str]) -> str:
        table = match.group(1)
        column = match.group(2)
        return f"'{table}'[{column}]"

    return _FIELD_PATTERN.sub(replace, expression)


__all__ = ["normalize_dax_expression"]
