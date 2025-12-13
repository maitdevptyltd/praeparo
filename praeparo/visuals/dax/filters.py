"""Filter normalisation helpers shared by visual planners."""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

from praeparo import normalize_dax_expression


def normalise_filter_group(values: object | None) -> tuple[str, ...]:
    """Normalise a filter group into a tuple of unique, formatted expressions.

    Filters are typically provided as strings, but context layering can yield
    sequences containing one-item mappings for "named" entries. We flatten those
    mapping values so downstream DAX never receives Python repr strings such as
    ``{'lender': \"'dim_lender'[LenderId] = 201\"}``.
    """

    if not values:
        return ()
    iterable: Iterable[object]
    if isinstance(values, str):
        iterable = (values,)
    elif isinstance(values, Mapping):
        iterable = tuple(values.values())
    elif isinstance(values, Sequence) and not isinstance(values, (bytes, bytearray)):
        iterable = values
    else:
        iterable = (values,)

    normalised: list[str] = []
    seen: set[str] = set()
    for item in iterable:
        if item is None:
            continue
        if isinstance(item, Mapping):
            for value in item.values():
                if value is None:
                    continue
                stripped = normalize_dax_expression(str(value).strip())
                if not stripped or stripped in seen:
                    continue
                seen.add(stripped)
                normalised.append(stripped)
            continue
        stripped = normalize_dax_expression(str(item).strip())
        if not stripped or stripped in seen:
            continue
        seen.add(stripped)
        normalised.append(stripped)
    return tuple(normalised)


def combine_filter_groups(*groups: object | None) -> tuple[str, ...]:
    """Combine multiple filter groups ensuring uniqueness and stable order."""

    combined: list[str] = []
    for group in groups:
        combined.extend(normalise_filter_group(group))
    if not combined:
        return ()
    seen: set[str] = set()
    result: list[str] = []
    for value in combined:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return tuple(result)


def wrap_expression_with_filters(expression: str, filters: Sequence[str]) -> str:
    """Wrap a DAX expression in CALCULATE with the provided filter expressions."""

    cleaned = [item.strip() for item in filters if item and item.strip()]
    if not cleaned:
        return expression.strip()

    arguments: list[str] = [_indent_block(expression.strip())]
    for filter_expression in cleaned:
        arguments.append(_indent_block(filter_expression))

    body = ",\n".join(arg for arg in arguments if arg)
    return f"CALCULATE(\n{body}\n)"


def _indent_block(text: str, indent: str = "    ") -> str:
    lines = text.splitlines()
    if not lines:
        return ""
    return "\n".join(f"{indent}{line.rstrip()}" for line in lines)


__all__ = ["combine_filter_groups", "normalise_filter_group", "wrap_expression_with_filters"]
